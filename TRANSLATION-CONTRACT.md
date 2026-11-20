# V1-006 学术翻译契约

翻译为独立衍生内容。原文证据仍绑定 PDF SHA、文件 ID、解析 ID、解析器版本、原块 ID、原文及结构哈希、章节、顺序和全部区域。不同解析中的块不能互用。新译文和人工修改默认未审核，确定性校验不评价否定、因果和条件等语义忠实度。

## 数据与迁移

SQLite schema 5→6 通过现有 BEGIN IMMEDIATE 事务新增 task_model_settings、glossary_versions、translation_runs、translation_requests、translation_blocks、translation_revisions、translation_batches。重复启动安全，DDL 异常回滚。旧表不重建，旧行与 ID 保留。继续复用当前迁移链，本阶段不引入 Alembic；发布阶段 010 再评估迁移工具统一。

术语版本、运行快照、块修订和批次记录是主记录。原 PDF、解析、精读、聊天、笔记及 Vault 无翻译写入路径。块头仅指向当前运行内的修订。重译创建新运行，人工修改通过 expected_revision 新增修订。没有跨运行覆盖人工译文的操作。

## 来源范围

- 正文、段落、标题、章节标题、列表项、图注、脚注和算法文本行可翻译。native_only、reading_order_unverified、semantic_quality_unverified 保持来源警告，允许逐块处理。
- formula/equation、代码、参考文献、图片保留原来源。图注作为独立 caption 处理，图片内文字本阶段保留。
- table_model.cells 为表格主结构，按独立单元格 ID 发送，返回按 ID 回填副本。行列、跨行列、区域、原表头关联及原数据保留，整表手写禁用。
- 无结构的表格、未知类型、额外质量异常、未配对数学分隔符、疑似裸 LaTeX 和超过输入预算的块保留原文并标 needs_review。没有静默删除或截断。
- 译文定位使用该运行原块的全部 regions。没有区域时入口禁用并说明原因。坐标不由译文字符长度推算，术语建议 start/end 为 Python Unicode 码点偏移。

## 术语

版本为不可变快照，保存使用 expected_revision。候选由 glossary 专用任务从原文提取，source_block_id 与连续英文原串须匹配当前目标，返回实际 start/end 与来源区域。候选仍需用户确认。

用户锁定、论文确认、默认词表、建议依次优先。规范化采用 casefold 与空白折叠，同一英文同优先级的不同中文明确冲突。重叠范围优先按等级选取，再按最长匹配，保留词边界，允许大小写和连续空白变体，不进行隐含词形推导。锁定译法由程序恢复，模型无法改变该占位内容。默认词表当前含 neural network→神经网络，可逐步扩充。

## 模型与保护

translation/glossary 配置独立，reading/chat 配置继续沿用。只支持实际实现的非流式 Chat Completions JSON 协议。配置保存及查询不调用模型，API 不读取 Worker 密钥，Worker 从指定环境变量取值。数据库只保存环境变量名。端点须 HTTPS 或本机 HTTP，不接受凭据、查询和片段，拒绝重定向。无工具、文件或多模态调用。

prompts/translation.md 与 prompts/glossary.md 为独立 Prompt，运行保存全文、首行版本和内容哈希。protection-2 保护已识别的数学源码、配对代码、负数/指数/范围/常见单位、Unicode 数学符号、引用、图表编号、锁定和有效术语。原文中类似占位符的字面文本再次保护。每段使用随机 nonce，精确校验集合与次数，拒绝新增、缺失、重复和串批 token，再按映射恢复。复杂数学无法可靠识别时保留来源并提示。

请求显式 source_block_id。返回 ID 集合、数量和唯一性必须吻合目标集合，数组顺序不参与对齐。另检空译、明显短摘要/截断、整段原文回传、缺少中文及新增未保护数学/数值。规则通过仍标语义未审核，不能保证自然语言正确率。

## 执行、缓存与失败

一批为一原块，表格包含多个单元格目标。提供真实章节标题与相邻块各最多 400 原文字符的上下文，附原块 ID、解析身份和真实 start/end；上下文亦进行独立 token 保护，仅在总预算内加入，返回时不允许将其 ID/token 当作目标。上下文及其来源参与缓存 key。输入含 Prompt 最多 10000 字符，不拆断目标中的受保护公式；目标超限保留全块待复核。最多 3000 来源块/模型调用，每块最多 3 次尝试，提交请求先持久化调用预算。输出最多 40000 字符，HTTP 响应最多 400KB，3000 输出 token 请求上限，单次网络总硬时限 90 秒。异常响应不写日志正文。

复用 jobs、独立 Worker、心跳与租约。调用预留、请求/响应与耗时可追溯；块修订、块头、进度和事件在同一持租约事务提交。调用中断消耗一次预算，已保存块从检查点恢复。租约失效 Worker 无权提交。保护版本改变后旧运行停止继续生成，已有成果仍可读取，新任务使用新协议。

不同 Worker 可分别认领翻译和精读任务，各自有检查点与租约；单 Worker 按队列顺序执行。失败或 needs_review 不计成功完成率，任务不会因其存在而标成功。每轮队列最多 3 次尝试，后续尝试不重发已耗尽块。UI“重试问题块”创建新运行并保留旧记录。原 /jobs/{id}/retry 只增加队列预算，已耗尽块继续保留，应使用新翻译运行进行内容重试。

operation_key 重复提交返回同一运行，参数不同返回 409。同一活动来源/范围/配置快照的不同键共用执行，并保存键别名。结束后的新任务按块缓存。key 含完整来源、语言、提供商协议/端点/模型及设置版本、Prompt、术语快照、保护和翻译配置。缓存不含凭据，重用前校验源哈希、输出、映射和内部一致性。force 绕缓存。人工修订不进入生成缓存。

usage 使用服务实际返回值，缺失为 unknown。未配价格时 cost 为 unknown。

## API

前端沿用 /api 代理，服务端沿用 /v1。写请求保持 X-PaperMind-Client 与来源校验。

| 接口 | 行为 |
| --- | --- |
| GET/POST /v1/task-model-settings/{translation或glossary} | 查询/保存任务模型，POST 带 expected_revision |
| GET/POST /v1/papers/{paper_id}/glossary | 查询/新增术语版本，POST 带 entries 与 expected_revision |
| GET /v1/papers/{paper_id}/glossary-versions | 不可变版本历史 |
| POST /v1/parse-runs/{parse_id}/translation-runs | operation_key、scope=full/sections/blocks、ids、force、task=translation/glossary |
| GET /v1/parse-runs/{parse_id}/translation-runs | 运行清单及独立计数 |
| GET /v1/translation-runs/{run_id} | 来源快照、模型术语版本、块头、失败原因、批次/用量 |
| PATCH /v1/translation-runs/{run_id}/blocks/{block_id} | expected_revision、text，冲突 409 返回 local/remote/current_revision |
| GET /v1/translation-runs/{run_id}/blocks/{block_id}/revisions | 块修订历史 |
| GET /jobs/{job_id}/events | 复用持久化 SSE，支持 Last-Event-ID 回放 |

阅读页“学术翻译”提供范围、模型设置、术语 JSON 编辑/锁定、进度、历史、中英块对应、问题重试、局部重译、手写冲突恢复和原文定位。译文以 React 纯文本预览，保留数学源码。完整双语阅读与数学排版属于 007。
