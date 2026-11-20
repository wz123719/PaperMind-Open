# V1-002 开发交付与待验收报告

**结论：工程实现与行为验证已提交；质量门槛未通过，不能宣布 V1-002 验收通过，不进入 V1-003。**

任务依据：docs/development/V1-002.md。核验日期2026-11-12。仅实施结构解析与原文定位；未开发AI精读、聊天、笔记或Obsidian写入。sources/与同步参考文件保持只读，未向其他聊天发送消息。

## 七项证据与判定

|任务书验收项|本轮结果|可复核证据|
|---|---|---|
|1 非破坏迁移与导入回归|已验证。原2篇/2文件/2任务/65事件的ID、行摘要与PDF哈希不变；迁移两次安全；DDL故障回滚/重试通过|evidence/v2/migration-before.json、migration-after.json；tests/test_migrations.py及原41项回归|
|2 五篇真实论文|五篇实际Docling检查；四篇公式增强完成，Adam增强运行2014.87秒后人工中止，使用显式公式关闭的实际运行检查其余内容，公式不计完成。此项不能宣称五篇完整增强通过|samples.json、review-samples.json、docling-samples.json、docling-base-samples.json、adam-long-attempt.json|
|3 每篇10个关键元素、内容≥95%|未达到。开发代理逐项比较50点；独立真人验收仍待进行。partial/incorrect不计正确|evidence/v2/quality_targets.json、quality-protocol.md、quality-review.md/.json|
|4 ≥40标注区域、定位≥95%|合成几何40参考矩形/640变换全部通过；真实语义定位另计，见下表，不合并分母|geometry-annotations.json、pdfjs-geometry.json、几何源图及浏览器截图|
|5 中断、重复、故障、扫描、历史与版本|真实生产Worker在Docling处理中强杀后重启，attempt2成功；旧产物完全相同且重复提交复用。受控故障三次自动重试后失败，显式重试成功；过期Worker不能发布。真实Docling空白/扫描零块有OCR警告|real-parse-restart.json及前后日志、docling-no-text.json、tests/test_parsing.py|
|6 浏览器完整阅读链路|实际启动→进度→完成→章节/块→高亮→缩放→搜索→选文→版本切换；公式增强和历史可读。浏览器重试按钮未手工复验，后端故障/重试有集成验证|evidence/v2/browser-operations.md与对应ui-*.jpg|
|7 测试、类型、构建及局限|60项后端测试通过；类型/构建通过；pip check通过。仍有内容/定位和公式长任务超时缺口|evidence/v2/final-verification.json、STRUCTURE-CONTRACT.md、本报告修复路径|

## 内容与真实语义定位（固定分母50）

这些是开发代理逐项对照源PDF渲染与实际输出的结果，不冒充独立真人复核。每篇10个事先选定检查点，可能有检查点涉及同一复合对象的不同内容，不代表整篇所有块的随机准确率。详细记录均绑定具体parse_run_id、block_id与来源页序号。

|论文|内容正确/10|内容partial|内容incorrect|内容missing|语义定位正确/10|定位partial/incorrect/missing|
|---|---:|---:|---:|---:|---:|---|
|transformer|9|1|0|0|9|1/0/0|
|bert|9|0|1|0|9|1/0/0|
|resnet|8|0|2|0|10|0/0/0|
|adam|5|0|4|1|8|2/0/0|
|lora|8|0|2|0|10|0/0/0|

内容正确 **39/50 = 78%**；真实语义定位正确 **46/50 = 92%**。目标分别为≥95%，每项需至少48/50正确。没有以有bbox算公式/表格正确，也没有把未检查项移出分母。

## 真实运行清单

Docling2.58.0，PyMuPDF1.26.5；CPU4线程，OCR关闭、准确表格模式；映射配置structure-v2。每次运行保存完整模型清单及哈希；未自动降级。模型清单SHA-256：44603f91d8af6ab0b48e01fb3f112a33ef6838ecdd5367170eb44d96b0749aed。Adam的公式关闭运行是独立明确提交，不是将失败增强任务改成成功，也不是native替代。

|论文/官方来源|PDF SHA-256|页数|实际核验运行|公式增强|运行耗时秒|章节/块|
|---|---|---:|---|---|---:|---|
|[transformer](https://arxiv.org/abs/1706.03762v7)|bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697|15|c73b916e-5743-4eed-b1af-63d5341e8c49|开启|133.69|27/167|
|[bert](https://arxiv.org/abs/1810.04805v2)|5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e|16|e12b4426-c23d-44b9-903a-a1a026ceb770|开启|67.72|33/259|
|[resnet](https://arxiv.org/abs/1512.03385v1)|1e0651b6810ecba34a3dbc5b5b0209226f889004607c1f203540a48d64e5a93a|12|7c578058-5137-4828-8684-404a625cc875|开启|64.48|22/219|
|[adam](https://arxiv.org/abs/1412.6980v9)|eab9c73ae2ceda884b94830bda99312254bac4806f6c9f045cbab90721ecda31|15|cbd71e80-3214-4431-91ee-e5a2263a1d0d|关闭（不计公式完成）|48.88|22/195|
|[lora](https://arxiv.org/abs/2106.09685v1)|38a259c1926b724363fcfbd8e5f80fcadf0dd8d9ab6944fea8c00e74fd7590b0|20|bb6ccd85-b61d-4e35-9fe3-81a97db79469|开启|203.62|34/229|

耗时取表中成功尝试记录（含转换、映射及资源生成）；Transformer恢复后的成功尝试133.687秒，不含首次被杀运行及租约等待。Adam公式增强尝试1187cc05在2014.87秒后由开发QA人工中止，非自动超时，非自然解析异常；其artifact_root为空，旧成功结构未变，见adam-long-attempt.json。没有把它记为公式成功。完整配置、警告、文件及输入哈希见review-samples.json；实际输出在storage/parses相应不可变尝试目录，可通过版本化API读取。五篇原PDF与源裁图仅在本地QA保存，未公开发布全文。

公式关闭运行另存在docling-base-samples.json（Adam更新为structure-v2的新运行），均明确标注关闭公式；空公式按missing，不计正确。其他四篇增强结果在docling-samples.json；此前基础运行和历史资源仍在库中。初次官方模型下载的网络/TLS/完整性失败证据保留；最终官方LFS/Git哈希校验通过，没有跳过TLS或内容校验。

## 几何与浏览器证据

40个显式参考矩形位于8页合成PDF：5区域×4原始旋转×2CropBox。PDF.js以4缩放×4额外旋转检查640次，全部通过；PyMuPDF文字框落入参考区域检查通过，四张源图接触表已逐项查看。多页组经队列/API保存并在浏览器切到第2区域。该组明确标记synthetic_geometry_only，不算Docling论文识别。

真实论文浏览器抽查包括Transformer章节、第3页系统架构图、第4页Attention公式；140%缩放高亮对齐。搜索用当前文件原生文字，扫描页不声称可搜索。文字层使用实际PDF.js TextLayer。详情见[browser-operations.md](evidence/v2/browser-operations.md)。

![真实公式定位](evidence/v2/ui-docling-formula-full.jpg)

## 实现与复验入口

- schema迁移：backend/db.py；运行身份与历史：backend/parsing.py；实际解析映射与资源：backend/parse_pipeline.py。
- 原队列/独立Worker按type分派，尝试目录隔离，租约栅栏与完整发布在事务中完成；失败不能替换当前成功结果。
- /v1结构API、坐标契约、资源边界与兼容旧导入接口见[STRUCTURE-CONTRACT.md](STRUCTURE-CONTRACT.md)。
- 前端拆为Reader/PdfPage/StructurePanel与服务层；支持章节、块、多区域、文字层、搜索、文件版本和运行历史。
- 启动与锁定依赖见[README.md](README.md)。真实服务端口8765，前端5173。没有Git仓库，未伪称已提交commit或PR。

复验命令（项目根目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
pnpm --dir frontend run build
.\.venv\Scripts\python.exe -m evidence.v2.verify_migration
cd frontend
node verify-geometry.mjs
```

需要复跑真实论文时从项目根目录执行python -m evidence.v2.run_samples，默认复用相同成功输入；--force才新建历史，--only指定单篇。Adam公式增强可能再次长时间占用CPU，建议先修复全流程硬超时再复验。不要和其他Worker竞争领取此验证批次。prepare_review只产生候选，publish_review仅包装明确写入的逐项判断，不自动判PASS。

## 未达到标准的失败样本及修复路径

1. 复杂表格：ResNet Table1把括号/重复次数拆成额外列；LoRA Table4合并了WikiSQL的两组权重子行并错置MNLI数值。需增加跨行/跨列结构一致性校验，保留原始cells，并对不一致表格显式标记低质量；用同一50点重验，不能仅修Markdown显示。
2. 数学内容：BERT行内分式未被识别成公式；ResNet式(1)出现多余字符；Adam算法符号和正文/公式顺序存在问题。需补行内数学区域检测、公式/代码结构化提取与来源字符对照；不以手写论文专用替换规则凑准确率。
3. 语义区域：复合图面板/标题关联及算法内公式的细粒度区域不足。需保留真实子区域、区分段落和行内公式，在真实源图重新标注并复验。几何转换已通过不能免除语义错误。
4. 运行稳定性：Docling document_timeout=1200只覆盖库内页面构建检查，不覆盖后续公式增强；Adam实跑暴露长时间CPU占用。需把转换隔离到可终止子进程，加覆盖模型初始化/公式增强的全流程硬时限及进度；超时后保留旧成功结构、有限重试。当前不把该配置宣传为硬超时。
5. 其他已见局限：图中标题被误识别为章节；部分caption关系类型冲突已显式unknown；附近引用只是candidate。原始Docling、原生文字和来源资源均保留，不宣称全部结构或引用已准确。OCR未启用，扫描全文缺失属于明确能力缺口。Vite主包604.26KB有体积警告，未来可按需拆包。

验收建议：按本报告的失败ID与逐项清单独立复验，维持原≥95%门槛。工程测试通过不等于质量通过；修复后仍停留V1-002重验，未经质量验收不启动V1-003。
