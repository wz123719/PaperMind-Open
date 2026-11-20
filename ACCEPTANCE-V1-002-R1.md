# V1-002 R1 优化复验报告

2026-11-13；冻结版本structure-v5。结论：开发侧内容48/50（96%）、真实语义定位50/50（100%），数值门槛达到；**整体质量验收仍未通过，禁止进入V1-003**。完整多层表头要求仍有缺口，留出样本处理失败，独立真人复核尚未完成。此报告如实记录未通过项，不将开发代理自检冒充独立验收。

## 验收判定

|项目|结果|证据/限制|
|---|---|---|
|原50项内容|48/50，达到至少48项的数值门槛|两个partial仍计失败；原目标、50分母及基线副本不变|
|真实语义定位|50/50，开发代理原文复核达到数值门槛|与40区域/640几何测试分别统计；独立真人待复核|
|Adam真实增强|完成，227.594秒|formulas=true；17步骤及regret bound原文核对完成；不是公式关闭运行|
|运行稳定性|开发验证通过|真实1200秒硬超时、实际强杀后同一运行租约恢复并第二次成功、无解析/识别残留进程|
|工程回归|80 passed，6 warnings|原60项+9项子进程/故障测试+11项来源结构测试；35.30秒|
|前端|类型检查、构建、真实浏览器流程通过|606.58kB主JS，保留Vite大块提示；见浏览器证据|
|完整表格关系|未通过|Transformer表内指数未结构化，LoRA E2E上级表头不完整|
|留出样本|失败|Layer Normalization v1三次局部识别超时，无发布结果；10项目均未验证|
|独立复核|待完成|已交付来源裁图/完整候选/逐项结果供独立人员复核|

原报告39/50内容、46/50语义定位为历史基线。原11个内容失败项均完成对应修复，本轮严格复验另发现两个旧报告过宽的表格判定（transformer-08、lora-09），改计partial；这是原项目评分纠正，不是删除失败项或换分母，也不声称旧报告已充分验证数学结构。

## 实现与组件选择

Worker独立子进程覆盖初始化、版面、表格、数学增强、结构映射及资源生成，默认1200秒总时限；独立图像推理调用另限60秒。Windows挂起启动后纳入嵌套Job Object，父Worker强杀也关闭后代。进度只上报实测阶段、完成数量和耗时。私有目录不经子进程发布，父进程校验完整产物与租约后原子更新成功结果；无complete帧即使退出码0也失败。有限重试和显式用户重试预算保持原契约。

Docling CodeFormulaV2的真实运行在增强阶段1200秒自动失败（已完成30公式），不宣称它完成Adam。对照后采用明确配置的替代路径：Docling布局/表格 + PDF数学字形/线段结构 + RapidLaTeXOCR 0.0.9图像候选。公式开启且确实执行本地增强，保留每个来源区域、原始文本、候选、选择依据和检查状态，不是失败后偷偷关闭公式。图像OCR在9个定向公式来源直接识别仅3/9正确，因此没有把其输出自动标正确；字形图与局部切分的依据见[组件对照](evidence/v2-r1/component-comparison.md)。该9项用于定向比较，不是泛化准确率。

生产规则依据字体编码、真实字形位置/线段/像素带、通用算法行、表格网格/数值子行和明确面板标识，不读取论文名称或QA目标，不含固定公式答案。原始候选和差异均保留。语法检查与可编译性不能证明数学含义正确；产品仍显示未核验。

Rapid运行环境隔离，主程序numpy未降级；setup-math.py按固定依赖及4个模型文件本地哈希安装/校验。模型来自[官方RapidAI组件](https://github.com/RapidAI/RapidLaTeXOCR)声明的Release地址；上游摘要因API限流未取得，不冒充官方哈希认证。模型及运行清单SHA256：`c1d8b16bdba0471dfa5be0d5064b5297b9f3cd2a19e5bd440962d667ccfb39e8`。完整冻结源码/依赖哈希在[frozen-version.json](evidence/v2-r1/frozen-version.json)，交付检查确认未变。

表格使用结构化单元格为主数据，保留行列/跨度/来源/原文/完整表头路径，派生Markdown；异常表格保留独立网格/子行候选及差异。算法保存17步骤、缩进、数学片段和独立区域。复合图保存面板、标题、图注及独立区域，行内公式保留父段落；前端支持整体、递归子项与区域切页。

## 实际五篇运行

|样本|冻结运行ID|增强|成功尝试耗时（秒）|
|---|---|---|---:|
|transformer|`0184a6fa-8212-482b-a0de-6f119573bb95`|pdf_math_layout+RapidLaTeXOCR / formulas=true|80.125|
|bert|`924053fe-8b13-4c93-8755-bf13db4e5b28`|pdf_math_layout+RapidLaTeXOCR / formulas=true|72.907|
|resnet|`638476f9-53f9-403b-8ce4-fcb5e9d43afa`|pdf_math_layout+RapidLaTeXOCR / formulas=true|79.406|
|adam|`20546305-c941-4f27-8d39-44d0f2467b24`|pdf_math_layout+RapidLaTeXOCR / formulas=true|227.594|
|lora|`cd7c9811-e41f-4643-bc02-39c197418e70`|pdf_math_layout+RapidLaTeXOCR / formulas=true|130.703|

耗时为该成功尝试的完整解析耗时，不包含排队、先前失败或人为等待。Transformer第一次被QA主动强杀，租约到期后同一运行第二次成功；另有浏览器发起的同配置成功运行82689330，全部块类型、文本与区域与此冻结复核运行一致。完整配置、版本、源PDF哈希、模型清单、警告及块数量见[trials.json](evidence/v2-r1/trials.json)。

## 超时、恢复和发布边界

- 实际CodeFormula运行cf6f1356在公式增强1200秒硬超时，任务3/3失败，artifact_root为空、无残留解析进程，旧Adam成功head保持cbd71e80；见[实测超时](evidence/v2-r1/real-hard-timeout.json)。此处是新自动硬超时，与旧版33.6分钟人工中止分开记录。
- 实际Transformer运行0184a6fa被强杀Worker后，解析后代全部退出；旧结构及全部旧产物哈希未变，半成品无发布；实际租约到期后同一运行在第2次尝试成功。见[中断恢复记录](evidence/v2-r1/final-recovery.json)。
- 模型初始化/公式/映射/资源卡住、租约失效、Worker强杀、三次预算用尽及退出0但无complete帧由真实子进程/孙进程故障测试覆盖。
- 交付时实际API读取原5个历史运行及新5个运行的结构、Markdown、JSON、共285个来源资源，全部200且与各自发布文件字节一致；引用目标均存在。失败运行各产物接口409，无解析或独立OCR子进程残留；见[最终API和哈希验证](evidence/v2-r1/final-verification.json)。

## 浏览器验证

API已重启加载structure-v5；实际浏览器提交Transformer重解析，看到queued→running→succeeded、实际阶段/8页计数/耗时与可读旧结果。97个attention搜索命中并跳原文；PDF文字层实际复制得到“Alpha reference region”。Adam步骤15独立行高亮及90度旋转、BERT分式区域100%/140%、Transformer5区域整体和面板标题子项、旧成功历史、跨页组切第2页、60%缩放和第7页非默认CropBox均实际操作。几何合成样本明确不计入真实50项。操作详情与截图在[browser-operations.md](evidence/v2-r1/browser-operations.md)，实际新任务事件另存[browser-run-events.json](evidence/v2-r1/browser-run-events.json)。

![Adam独立参数更新行](evidence/v2-r1/ui-adam-step15.png)

![复合图完整关联与独立区域](evidence/v2-r1/ui-transformer-compound.png)

## 留出样本与剩余风险

来源：[Layer Normalization v1](https://arxiv.org/abs/1607.06450v1)，14页，PDF SHA256 `c464f839fb8d59f7fde92f9b4caa67c2d1f2f196b88f93fb60502249df0aaef7`。十项目在首次应用解析前仅依据原文登记，源图由Poppler渲染；未用其应用输出调优，也不保证上游模型训练集未见该论文。真实增强运行225d1286的三次尝试均在局部图像识别60秒上限失败，最终3/3，无发布head、各读取接口409。十项均记未验证，不把“没有输出”描述为十项数学内容识别错误，也不从原文阅读推算解析正确。详见[留出复验](evidence/v2-r1/holdout-review.json)。

剩余问题：Transformer表内指数仍平铺；LoRA Table2 E2E上级表头尚未覆盖所有指标列。50项之外仍存在Adam替代更新式额外hat、部分内联数学误检测/上下限丢失、普通正文残留glyph标记等问题；不能把48/50外推为全文或未知论文95%。PDF字形/线段图只适用于可映射来源，扫描页、复杂矩阵、未知字体仍需其它识别组件。独立图像OCR的长重复/超时已在留出样本复现，该替代路径的泛化能力尚未验证。

后续仍在V1-002范围：补全通用表内数学与多层表头恢复；评估有界解码、可取消局部推理的替代组件，按相同原50项及新冻结留出协议对照；保留本次失败证据。完成独立人员复核后才能作最终放行决定，不新增V1-003任务。

## 原50项逐项前后结果

C=内容，L=真实语义定位。correct才计正确，partial计失败。下列每项均链接冻结运行来源叠框，完整块数据与旧/新差异保存在[review-comparisons.json](evidence/v2-r1/review-comparisons.json)，逐项机器可读结果为[quality-review.json](evidence/v2-r1/quality-review.json)。

|项目|旧C/L|新C/L|原目标与复核说明|
|---|---|---|---|
|[transformer-01](evidence\v2-r1\review\transformer-01.png)|correct/correct|correct/correct|Heading and following paragraph order；Introduction标题及四段正文顺序与原文一致；本轮文字和区域与旧版一致，已复看来源。|
|[transformer-02](evidence\v2-r1\review\transformer-02.png)|correct/correct|correct/correct|Heading and following paragraph order；Background的Extended Neural GPU、self-attention、memory与Transformer段落按原文顺序保留。|
|[transformer-03](evidence\v2-r1\review\transformer-03.png)|correct/correct|correct/correct|Heading and following paragraph order；Model Architecture标题与encoder/decoder正文连接正确，原文来源完整。|
|[transformer-04](evidence\v2-r1\review\transformer-04.png)|correct/correct|correct/correct|Encoder/decoder architecture, caption, source region；Figure1包含完整编码器/解码器、输入输出和positional encoding，图注关联保留。|
|[transformer-05](evidence\v2-r1\review\transformer-05.png)|partial/partial|correct/correct|Scaled dot-product / multi-head diagrams and caption；新增figure_group关联左右面板、两个标题和图注，五个独立区域完整；浏览器整体和面板标题定位已核验。关联在产品中仍标候选，不伪造核验状态。|
|[transformer-06](evidence\v2-r1\review\transformer-06.png)|correct/correct|correct/correct|Equation (1): softmax(QK^T/sqrt(d_k))V, all operators/factors；Attention的softmax、QK转置、sqrt(d_k)分母及末尾V均与原文相同；细化区域包含完整公式而不含正文。|
|[transformer-07](evidence\v2-r1\review\transformer-07.png)|correct/correct|correct/correct|Equation (2): max(0,xW_1+b_1)W_2+b_2；FFN的max、括号、W1/b1/W2/b2及乘加顺序一致；区域与公式行对应。|
|[transformer-08](evidence\v2-r1\review\transformer-08.png)|correct/correct|partial/correct|Self-attention row: O(n^2 d), O(1), O(1); headers and row association；Self-Attention列关系与O(1)正确，但主数据仍为O(n 2 · d)，未保存n的指数结构，且原始cell含解码替代符。严格按O(n²d)目标不能计正确。旧报告对此判得过宽，本轮纠正评分，不删项目。|
|[transformer-09](evidence\v2-r1\review\transformer-09.png)|correct/correct|correct/correct|Transformer big row: BLEU 28.4 / 41.8, headers and row association；Transformer(big)行EN-DE28.4/EN-FR41.8与BLEU多层列头对应正确；区域完整。|
|[transformer-10](evidence\v2-r1\review\transformer-10.png)|correct/correct|correct/correct|Heading and full following paragraph order；Conclusion标题及四段正文、未来方向和代码链接顺序保留，原文第10页来源完整。|
|[bert-01](evidence\v2-r1\review\bert-01.png)|correct/correct|correct/correct|Abstract content order, no right-column interleaving；Abstract两段和80.5/86.7/93.2/83.1等结果与原文一致，左右栏未混排。|
|[bert-02](evidence\v2-r1\review\bert-02.png)|correct/correct|correct/correct|Heading and left-column text order；Related Work标题及总述段顺序与来源一致。|
|[bert-03](evidence\v2-r1\review\bert-03.png)|correct/correct|correct/correct|Pre-training / fine-tuning architecture, source region and caption；Figure1完整保留预训练/微调、NSP/MaskLM/问答两面板及图注。|
|[bert-04](evidence\v2-r1\review\bert-04.png)|correct/correct|correct/correct|Heading and following body order；3 BERT及正文顺序正确；minimal difference跨左右栏续文仍关联为双区域。|
|[bert-05](evidence\v2-r1\review\bert-05.png)|correct/correct|correct/correct|15% token choice and 80%/10%/10% replacement details retained；Masked LM的15%、80%MASK、10%随机、10%原词及段落顺序完整。|
|[bert-06](evidence\v2-r1\review\bert-06.png)|correct/correct|correct/correct|Token + segment + position embeddings, caption and region；Figure2 token/segment/position embeddings及caption完整，来源区域正确。|
|[bert-07](evidence\v2-r1\review\bert-07.png)|incorrect/partial|correct/correct|Start probability exp(S dot T_i)/sum_j exp(S dot T_j), full expression；P_i=e^(S·T_i)/(sum_j e^(S·T_j))分式、指数和求和下标均正确，父段落关联保留；b259独立区域及浏览器100%/140%高亮正确。|
|[bert-08](evidence\v2-r1\review\bert-08.png)|correct/correct|correct/correct|GLUE table: BERT BASE/LARGE rows, MNLI-m 84.6/86.7 association；Table1 BASE/LARGE MNLI-m84.6/86.7及目标行数据、模型与列头关系正确。|
|[bert-09](evidence\v2-r1\review\bert-09.png)|correct/correct|correct/correct|SQuAD 1.1: BERT LARGE (Ens.+TriviaQA), Test EM 87.4 / F1 93.2; verify headers and association；Table2 LARGE Ens.+TriviaQA Test EM87.4/F1 93.2与Dev/Test和EM/F1层级关系正确。|
|[bert-10](evidence\v2-r1\review\bert-10.png)|correct/correct|correct/correct|Ablation table: BERT BASE / No NSP / LTR & No NSP, row associations and numbers；Table5 BASE/No NSP/LTR & No NSP各任务数值与Dev Set多层表头关系一致。|
|[resnet-01](evidence\v2-r1\review\resnet-01.png)|correct/correct|correct/correct|Abstract and introduction remain in correct columns；Abstract两段连续保留，与右栏Introduction分离。|
|[resnet-02](evidence\v2-r1\review\resnet-02.png)|correct/correct|correct/correct|Residual building block F(x)+x and caption；Figure2 F(x)、identity shortcut、加法与relu完整，caption关联保留。|
|[resnet-03](evidence\v2-r1\review\resnet-03.png)|correct/correct|correct/correct|Heading and residual learning subsection order；第3节和3.1层级及residual mapping三段顺序与原文一致。|
|[resnet-04](evidence\v2-r1\review\resnet-04.png)|incorrect/correct|correct/correct|y=F(x,{W_i})+x, complete symbols and indices；公式1 y=F(x,{Wi})+x正确，不再包含原模型额外生成的errow；原始候选另存，来源仅公式行。|
|[resnet-05](evidence\v2-r1\review\resnet-05.png)|correct/correct|correct/correct|y=F(x,{W_i})+W_s x, complete symbols and indices；公式2 y=F(x,{Wi})+Ws x保持正确，s下标及完整区域未退化。|
|[resnet-06](evidence\v2-r1\review\resnet-06.png)|correct/correct|correct/correct|Example network architectures, source image and caption；Figure3 VGG19/plain34/residual34三架构、caption和来源完整。|
|[resnet-07](evidence\v2-r1\review\resnet-07.png)|correct/correct|correct/correct|Heading and following paragraph order；4 Experiments、4.1 ImageNet Classification及数据集说明顺序一致。|
|[resnet-08](evidence\v2-r1\review\resnet-08.png)|incorrect/correct|correct/correct|50-layer conv2_x bottleneck: 1x1/64, 3x3/64, 1x1/256 repeated 3; cell associations；Table1主数据恢复7列；conv2_x的50-layer bottleneck三层及×3同格，后续重复次数与各层对应；共享输出尺寸和池化单元格跨行列关系保留。|
|[resnet-09](evidence\v2-r1\review\resnet-09.png)|correct/correct|correct/correct|34-layer plain 28.54, residual 25.03; headers and row associations；Table2 34层plain28.54/ResNet25.03及18层数据正确；caption未知状态如实保留，不冒充已确认引用。|
|[resnet-10](evidence\v2-r1\review\resnet-10.png)|correct/correct|correct/correct|ResNet-152: top-1 21.43, top-5 5.71; headers and row associations；Table3 ResNet152 top1 21.43/top5 5.71及其它行列对应一致，没有数值回归。|
|[adam-01](evidence\v2-r1\review\adam-01.png)|correct/correct|correct/correct|Abstract reading order and method description；真实公式增强开启运行中的Abstract正文与原文一致，未使用旧公式关闭运行替代。|
|[adam-02](evidence\v2-r1\review\adam-02.png)|correct/correct|correct/correct|Introduction heading and following body order；Introduction随机梯度背景与Adam特点两段顺序一致。|
|[adam-03](evidence\v2-r1\review\adam-03.png)|incorrect/correct|correct/correct|Entire Adam pseudocode, moment updates and bias correction (not merely bbox)；Algorithm1图注和17步骤分行保存；Require、初始化、while缩进、m/v更新、校正、参数更新和return顺序正确；g_t²、beta幂次、widehat、epsilon及默认值与原文核对一致。|
|[adam-04](evidence\v2-r1\review\adam-04.png)|incorrect/correct|correct/correct|Section 2 and 2.1 hierarchy and order；第2节/2.1层级正确；Note that引导段现在先于替代更新公式，公式区域不再进入2.1标题。该目标仅评层级与顺序；b14仍有额外hat字符、b17内联epsilon未结构化，另列残留缺陷。|
|[adam-05](evidence\v2-r1\review\adam-05.png)|incorrect/partial|correct/correct|First/second moment exponential moving averages, symbols and powers；b205/b206独立步骤保存m_t=beta1*m_(t-1)+(1-beta1)*g_t与v_t=beta2*v_(t-1)+(1-beta2)*g_t²，符号、指数及两行来源对应。|
|[adam-06](evidence\v2-r1\review\adam-06.png)|incorrect/partial|correct/correct|Bias-corrected parameter update, denominator and epsilon；b207/b208/b209保留两项bias correction的beta^t及theta更新sqrt(vhat)+epsilon；可分别定位，浏览器参数更新行与90度旋转高亮已核验。|
|[adam-07](evidence\v2-r1\review\adam-07.png)|correct/correct|correct/correct|Initialization bias correction heading and body order；Initialization Bias Correction标题及解释正文顺序保持；此项不代表正文中所有内联公式都已正确结构化。|
|[adam-08](evidence\v2-r1\review\adam-08.png)|missing/correct|correct/correct|Theoretical regret bound / convergence formula: full source expression, not approximate text；真实增强完成；regret bound三项与原文逐项核对：D²/2alpha(1-beta1)、sqrt(T vhat)、第二项G∞与sqrt(1-beta2)/(1-gamma)²关系及norm2、末项D∞²G∞sqrt(1-beta2)/(2alpha(1-beta1)(1-lambda)²)与三组sum_i=1^d完整。原始识别及图像/字形候选保留。|
|[adam-09](evidence\v2-r1\review\adam-09.png)|correct/correct|correct/correct|Optimization plots and caption with complete source region；Figure1 MNIST和IMDB两组优化曲线、图例及caption来源完整。|
|[adam-10](evidence\v2-r1\review\adam-10.png)|correct/correct|correct/correct|Empirical optimization plots and caption with complete source region；Figure2 dropout主图与右侧两个缩放图、caption及来源完整。|
|[lora-01](evidence\v2-r1\review\lora-01.png)|correct/correct|correct/correct|Low-rank reparametrization diagram, A/B matrices, source region and caption；Figure1 W、A/B、加法及x/h路径完整，caption关系保留。|
|[lora-02](evidence\v2-r1\review\lora-02.png)|correct/correct|correct/correct|Abstract content and order；Abstract成本、LoRA方法、10000倍参数、3倍硬件与实验链接顺序一致。|
|[lora-03](evidence\v2-r1\review\lora-03.png)|correct/correct|correct/correct|Heading and following body order；Problem Statement标题、语言模型、数据集与微调目标引导段顺序一致。|
|[lora-04](evidence\v2-r1\review\lora-04.png)|correct/correct|correct/correct|Conditional log-likelihood pre-training objective, sums and conditioning；公式1 max_Phi、数据集sum_(x,y)inZ与sum_t=1^/y/、log条件概率p_Phi(y_t/x,y_<t)全部正确。|
|[lora-05](evidence\v2-r1\review\lora-05.png)|incorrect/correct|correct/correct|Adaptation objective Phi_0 + DeltaPhi(Theta), sums and conditioning；公式2 max_Theta、两层求和上下限与p_(Phi0+DeltaPhi(Theta))条件关系正确，不再把数据集限制误识别为独立t上下限。|
|[lora-06](evidence\v2-r1\review\lora-06.png)|correct/correct|correct/correct|h=W_0 x + DeltaW x = W_0 x + BA x, complete expression；h=W0x+DeltaW x=W0x+BAx完整，来源仅对应公式行。|
|[lora-07](evidence\v2-r1\review\lora-07.png)|correct/correct|correct/correct|Heading and body order；3 Our Method与方法概述、低秩约束正文的阅读顺序一致。此项不把正文中glyph[lessmuch]等残留认作公式正确。|
|[lora-08](evidence\v2-r1\review\lora-08.png)|correct/correct|correct/correct|WikiSQL/MultiNLI/SAMSum baseline and LoRA rows; headers and numeric cell association；Table1 WikiSQL/MNLI-m/SAMSum数据与BASE/LoRA及各参数规模行一致，分层表头与值关系保留。|
|[lora-09](evidence\v2-r1\review\lora-09.png)|correct/correct|partial/correct|GPT-2 M/L E2E: LoRA BLEU 70.4/70.4 with model-column associations；GPT2 M/L LoRA BLEU70.4/70.4及模型/指标列对应正确，但E2E被合入MET单列，未形成覆盖BLEU/NIST/MET/ROUGE-L/CIDEr的完整上级表头；按完整E2E列关联不能计正确。旧报告过宽判定在本轮纠正，原目标与分母不变。|
|[lora-10](evidence\v2-r1\review\lora-10.png)|incorrect/correct|correct/correct|Rank 1/2/4/8/64 rows and WikiSQL/MNLI values correctly associated；Table4 WikiSQL的Wq,Wv与Wq两子行分开，分别73.4/73.3/73.7/73.8/73.5及68.8/69.6/70.5/70.4/70.0；MultiNLI91.3/91.4/91.3/91.7/91.4对应rank1/2/4/8/64。WikiSQL行头跨两行，原始合并候选保留。|

复验命令：项目根目录`.venv/Scripts/python.exe -m pytest -q`；前端`tsc --noEmit`和`vite build`；两个Python环境`pip check`；前端`node --experimental-strip-types verify-geometry-r1.mjs`；`python -m evidence.v2-r1.verify_delivery`。测试日志[pytest-final.txt](evidence/v2-r1/pytest-final.txt)，几何结果[pdfjs-geometry.json](evidence/v2-r1/pdfjs-geometry.json)。测试/构建通过不替代内容与独立人员验收。
