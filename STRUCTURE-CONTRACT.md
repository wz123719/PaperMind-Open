# V1-002 结构与定位契约

## 运行、身份和迁移

schema v2 新增 `schema_migrations`、`parse_runs`、`document_sections`、`document_blocks`、`file_parse_heads`，不重写四张 v1 表。数据库初始化使用 `BEGIN IMMEDIATE` 包含 DDL 与版本记录；失败回滚，重复运行安全，拒绝高于支持版本的数据库。升级前真实备份保存在 storage/backups，测试验证 DDL 注入故障的回滚和重试。

每次运行记录稳定 UUID、paper_file_id、file_sha256、input_hash、parser、parser_version、config_version、完整 config、job_id、状态/警告/耗时。input_hash 包含文件 SHA、解析器/配置版本和规范化 config；Docling 还包含模型清单哈希。执行前再次核验文件哈希、解析器版本和模型清单。不兼容的旧任务应重新提交，不伪装成相同配置。

同一文件和输入指纹的 queued/running/succeeded 运行可复用；force=true 创建新历史。一个文件的提交时间在事务内单调递增，避免 Windows 时钟刻度相同或回拨导致旧运行覆盖新运行。成功历史不可覆盖。head 只指向完整成功运行，较旧运行后完成也不能覆盖已发布的更新运行。

## 坐标：normalized-unrotated-crop-topleft-v1

- page_index 从 0 开始；page_label 来自 PDF page label，独立存储；前端导航页序号是 page_index+1，不使用印刷标签索引数组。
- bbox=[x0,y0,x1,y1]，单位是未旋转可见 CropBox 的宽/高比例，原点在左上，x 向右、y 向下；有效范围 [0,1]。四个数不能与 points 混用。
- page.width_points/height_points 表示未旋转裁切页面在 PyMuPDF 中的尺寸；pdf_view 为对应的 PDF user-space 可见框 [left,bottom,right,top]；rotation 记录原始 /Rotate。
- MediaBox 不是绘制范围；可见 CropBox 的偏移保存在 pdf_view 中。PyMuPDF 的原生文字框在未旋转裁切空间，归一化后保存。Docling 来源框先从其显示方向变换回未旋转 CropBox；尺寸不匹配、缺失或无效来源标记可见，不猜测页面或伪造 bbox。
- Docling page_no 是 1-based，入库时转换为 page_index。多 provenance 项逐项保存为 regions，不压扁为跨页单个框。

前端显式转换（实现为 `frontend/src/services/coordinates.ts`）：

```text
width = pdfPage.view[2] - pdfPage.view[0]
height = pdfPage.view[3] - pdfPage.view[1]
pdfRect = [view.left + x0*width, view.top - y1*height,
           view.left + x1*width, view.top - y0*height]
viewport.convertToViewportRectangle(pdfRect)
```

PDF.js viewport 一次性处理原始旋转、用户额外旋转、缩放和 UserUnit。overlay 使用 CSS px；canvas 的 devicePixelRatio 仅影响像素分辨率，不能再次乘入 overlay。文字层使用同一 viewport。一个块的多个 regions 按当前页过滤显示，界面提供各区域的跳页按钮。

## 结构和资源

section 保存 parent_id、level、title、reading_order、regions。block_id 在运行内唯一且带 parse_run UUID 前缀；块保存 section_id、type、text、reading_order、regions、source、quality_flags、data。引用应保存 parse_run_id + block_id，重解析后旧 ID 与旧资源仍可读取。

Docling负责初始结构、阅读顺序、表格与图像候选；PyMuPDF提供原生文字、搜索和位置证据。structure-v5公式增强明确采用PDF数学字形/线段结构与独立RapidLaTeXOCR候选，记录formula_backend、版本、数学模型及隔离运行依赖完整清单和哈希。原CodeFormulaV2的实际失败另存，不冒充该模型增强成功。公式保留原始文本、各次原始与规范化候选、选择依据、检查状态、来源字形/线段与区域；语法检查不代表内容正确，verification默认unverified。

表格主数据为data.table_model的cells：row/column、row_span/column_span、raw_text、text、regions、column_headers及row_headers。原始Docling table、raw_markdown、候选和差异保留；展示Markdown由当前主数据生成。独立表格线网格和数值基线子行候选按来源证据选择，异常显式待复核，不能只改显示数据。图像、公式、算法步骤等来源区域另存PNG，完整PDF仍绑定paper_file_id。

data.children/parent_block_id描述对象层级；figure_group保存复合图的独立面板、标题及图注区域，algorithm_step保存step_number、缩进、分行文本/数学片段与独立区域，inline_formula保留父段落关系。前端提供定位整体、递归定位子项和区域切页入口。无法确认的关联保持candidate/unknown，缺失来源和未核验标志不自动转为正确。

caption 来自 Docling 提供的 caption 关联；无法识别时为 null/unknown。附近文本引用通过可见 Figure/Table 编号匹配，仅标为 candidate，不能当作已核验关系。结构 JSON 同时保留原始 Docling 字典与独立原生文字列表。

native 模式不识别章节、表格或 LaTeX，块带 native_only / reading_order_unverified，扫描或无原生文字文件明确警告 OCR 未启用。不会把原生块包装成 Docling 成果。

## API

旧上传/导入与 job/SSE 接口保留兼容。新结构接口版本前缀为 `/v1`；本地前端通过 Vite `/api` 代理，实际访问 `/api/v1/...`。写请求沿用来源白名单和 `X-PaperMind-Client: workspace`。

| 接口 | 响应与边界 |
|---|---|
| POST /v1/files/{file_id}/parse-runs | JSON mode=docling/native、force=false、formulas=true；202 返回 run/job ID 和 reused；未知文件 404 |
| GET /v1/files/{file_id}/parse-runs | 运行历史及 current_run_id；未知文件 404 |
| GET /v1/parse-runs/{id} | 运行状态、输入绑定、配置、警告、耗时；不暴露内部绝对路径 |
| GET /v1/parse-runs/{id}/structure | 成功的 sections、blocks、pages；未成功 409，未知 404 |
| GET /v1/parse-runs/{id}/json | 完整结构、原始 Docling 与原生提取 JSON |
| GET /v1/parse-runs/{id}/markdown | 实际 Markdown 产物；未成功 409 |
| GET /v1/parse-runs/{id}/assets/{asset_id} | 仅允许该运行块记录中的内部资源 ID，未知或越界 404 |
| GET /v1/files/{file_id}/search?q=... | 当前 PDF 原生文字搜索，最多 200 匹配框，返回 truncated 标记；不跨文件或调用模型 |

Markdown 中的区域资源名对应 assets API 的 asset_id；客户端导出离线笔记时应同时保存资源并重写链接。本轮只提供读取接口，没有 Obsidian 发布。

## 队列、失败和发布

`parse_pdf` 与 `arxiv_import` 由同一独立 Worker 按 type 分派。未知类型报错。沿用数据库认领、心跳、有限重试、SSE 事件和显式重试。parse run 与对应 job 的失败/排队状态在队列事务内同步。

每个尝试写独立的 storage/parses/{run_id}/{attempt_id}，完整产物落盘后检查租约。在一个事务中插入所有章节和块、设置成功状态与 artifact_root、更新 head、提交任务终态和 succeeded 事件。失败、旧 Worker 或写事务回滚不能发布半成品。普通失败清理本次未发布目录；强杀可留下未引用目录，不会被 API 读取。历史成功资源不删除。

Worker管理租约、进度、重试和原子发布，Docling转换及增强隔离到独立子进程，不占用FastAPI BackgroundTasks。PAPERMIND_PARSE_TIMEOUT_SECONDS默认1200秒，从启动前计时，覆盖模型初始化、版面/表格、公式、映射和资源。独立图像推理启动/单次调用另限60秒。Windows使用挂起启动并纳入Worker与任务的Job Object，KILL_ON_JOB_CLOSE覆盖后代；POSIX使用独立进程组及父管道守护。超时、租约失效或Worker强杀会终止进程树。子进程只写私有工作目录，父进程必须校验完整产物、输入与租约后才原子发布。没有complete帧的退出码0也失败。原队列三次预算不变，用户手动重试才显式新增三次预算。

checkpoint只上报可取得的实际阶段、已完成页/公式数量、累计和阶段耗时；缺少细粒度计数时仅显示阶段内处理中，不伪造百分比。持续心跳只证明存活。失败不覆盖当前成功结构、引用和资源；未成功的structure/json/markdown/assets均不可读取。强杀遗留的私有目录也不属于可发布结果。原生模式仍为独立能力有限模式，不把公式关闭当作增强成功。

## 验证边界

40 个合成参考区域和 640 次自动 PDF.js 变换检查属于几何验证，不能充当真实论文内容准确率。五篇真实样本的章节/正文顺序、公式实际符号、表格实际单元格和图片/caption 必须逐项对照源 PDF，另报缺失与错误。未完成核验时不宣称 ≥95%，也不进入 AI 精读阶段。

## R2 增量契约（structure-v6-r2）

`GET /v1/files/{id}/source` 返回对应PDF哈希/arXiv版本的源文件状态；`POST`排入原Worker的`arxiv_source`任务（三次预算），不在API内启动下载或识别。`POST /v1/files/{id}/parse-runs`新增可选`source_preferred`布尔值。获取来源仅允许官方arXiv准确版本端点；未知版本、失败、包装PDF无TeX对象各有明确状态。源档、来源时间、SHA256和解析器身份参与新运行输入指纹，不改写旧运行。

TeX只做有界静态提取，不执行作者脚本或编译命令。主文件/子文件、有限宏、章节、数学片段、表格定义及引用保存在完整JSON的`source_document`；每个对象保留文件、行号、字符偏移、原始/展开文本、检查状态与PDF映射候选。未知关联保留空区域，不能把整页假充对象来源。静态公式编号未经独立核验禁止用于强制对齐；同一版本源档也可能包含与分发PDF不同的条件内容。

数学对象保留原PDF字形、规则线段、候选识别和选择理由。`math_structure`提供分式、根号、上下标、求和上下限等有界关系树；它不验证数学含义。映射可靠字形优先；未映射的CMEX可打印片段也判为不支持，不当成普通字母。受限MinerU备选只针对不支持的数学裁剪：本地固定4.2.1模型，120秒；必要时再一次Rapid调用60秒，全部仍受父任务1200秒上限与原队列三次预算约束。`object_routing`保留真实路由/缓存事件。

私有对象缓存键包含PDF/源档/图像区域及完整配置和模型清单哈希，内容校验后原子写入。失败前成功对象可在完全相同指纹下复用；模型、源码适配器、源文件或区域变动即失效。缓存及失败尝试不属于公共API产物。模型或隔离依赖不匹配时拒绝调用该组件，记录失败后仍可在预算内尝试其他组件；执行期间适配器哈希变化则拒绝整篇发布。缺少完整子进程完成帧的退出码0仍为失败。

表格以`table_model.cells`为主数据；单元格保存行列/跨度/来源/原始文本和从上至下的`column_headers`路径。版面恢复的上下标保存`layout_latex`和数学关系树；有真实列分隔与垂直对齐证据才拆分多行表头。Markdown从选定结构生成。原始Docling和先前候选保留。前端可展开单元格头路径、查看未核验数学候选并定位单元格。候选组件的无单元格坐标必须为空，不生成假精细区域。
