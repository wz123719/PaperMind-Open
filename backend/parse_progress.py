"""Progress hooks for pinned Docling 2.58; counters advance only on real yields."""
def progress_pipeline(report,config,records,*,session=None,source_path=None):
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
    from docling.models.code_formula_model import CodeFormulaModel

    class LocalFormulaStage:
        elements_batch_size=1
        def __init__(self):self.completed=0
        def prepare_element(self,conv_res,element):
            if getattr(getattr(element,'label',None),'value',None)!='formula' or not element.prov:return None
            from types import SimpleNamespace
            return SimpleNamespace(item=element,document=conv_res.document)
        def __call__(self,doc,element_batch):
            import pymupdf as fitz
            from .math_regions import crop_math,additive_parts
            from .local_math_backend import recognize_region
            from .geometry import region
            with fitz.open(source_path) as pdf:
                for prepared in element_batch:
                    item=prepared.item;prov=item.prov[0];index=prov.page_no-1
                    if not 0<=index<len(pdf):yield item;continue
                    page=pdf[index];size=doc.pages[prov.page_no].size
                    b=prov.bbox.to_top_left_origin(page_height=size.height)
                    clip=fitz.Rect(b.l*page.rect.width/size.width,b.t*page.rect.height/size.height,
                        b.r*page.rect.width/size.width,b.b*page.rect.height/size.height)*page.derotation_matrix
                    page.set_rotation(0)
                    report({'stage':'formula_enrichment','completed_formulas':self.completed,'message':'独立数学布局与图像候选增强：阶段内处理中'})
                    from .algorithm_layout import boxed_algorithms
                    if any(obj['rect'].contains(clip.tl+(clip.br-clip.tl)*.5) for obj in boxed_algorithms(page)):
                        records[item.self_ref]={'source':'deferred_algorithm_layout','latex':item.text,'raw_docling_text':item.text,
                            'check_status':'needs_algorithm_partition','verification':'unverified','candidates':[],
                            'route_history':[{'route':'pdf_caption_closed_rule_algorithm','status':'deferred_to_structure_mapping'}]}
                        self.completed+=1;yield item;continue
                    localized=crop_math(page,clip)
                    if localized:
                        result=recognize_region(page,localized,session,additive_parts(page,localized))
                        result['raw_docling_text']=item.text
                        result['refined_regions']=[region(index,localized['bbox'],page.rect.width,page.rect.height)]
                        records[item.self_ref]=result;item.text=result['latex']
                    self.completed+=1
                    report({'stage':'formula_enrichment','completed_formulas':self.completed,'message':'独立数学布局与图像候选增强：阶段内处理中'})
                    yield item

    class FormulaProgress:
        elements_batch_size=1
        def __init__(self,model):
            from .math_recognition import MathRecognizer
            self.model=model;self.completed=0;self.recognizer=MathRecognizer(model,config)
        def __getattr__(self,name):return getattr(self.model,name)
        def __call__(self,doc,element_batch):
            report({'stage':'formula_enrichment','completed_formulas':self.completed,'message':'公式增强：阶段内处理中'})
            for el in element_batch:
                result=self.recognizer.recognize(el.image)
                el.item.text=result['latex'];records[el.item.self_ref]=result
                self.completed+=1
                yield el.item
            report({'stage':'formula_enrichment','completed_formulas':self.completed,'message':'公式增强：阶段内处理中'})

    class MeasuredPipeline(StandardPdfPipeline):
        def __init__(self,pipeline_options):
            report({'stage':'model_initialization','message':'初始化布局、表格与公式模型：阶段内处理中'})
            super().__init__(pipeline_options);self.completed_pages=0
            self.enrichment_pipe=[FormulaProgress(m) if isinstance(m,CodeFormulaModel) and m.enabled else m for m in self.enrichment_pipe]
            if session is not None:self.enrichment_pipe.insert(0,LocalFormulaStage())
        def _apply_on_pages(self,conv_res,page_batch):
            report({'stage':'layout_tables','completed_pages':self.completed_pages,'message':'版面与表格识别：阶段内处理中'})
            for page in super()._apply_on_pages(conv_res,page_batch):
                self.completed_pages+=1
                report({'stage':'layout_tables','completed_pages':self.completed_pages,'message':'版面与表格识别：阶段内处理中'})
                yield page
        def _assemble_document(self,conv_res):
            report({'stage':'reading_order','completed_pages':self.completed_pages,'message':'组装阅读顺序：阶段内处理中'})
            return super()._assemble_document(conv_res)
        def _enrich_document(self,conv_res):
            report({'stage':'formula_enrichment' if config['formulas'] else 'enrichment',
                'message':'增强识别：阶段内处理中'})
            return super()._enrich_document(conv_res)
    return MeasuredPipeline
