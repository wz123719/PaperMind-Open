# V1-003 精读契约

本地API继续要求`X-PaperMind-Client: workspace`写入头及既有来源校验。schema v3只增加reading_settings、reading_runs、reading_stages；不改写旧行，不替换解析head。精读引用始终绑定具体parse_run_id和原块ID。

| 接口 | 行为 |
|---|---|
| GET /v1/reading-settings | 非敏感配置与configured；不返回凭据值 |
| POST /v1/reading-settings | endpoint完整URL、model、key_env可选；保存新revision，不自动调用模型 |
| POST /v1/parse-runs/{id}/reading-runs | `{force:false}`；完整成功解析才可提交；重复活动任务总复用，成功结果默认复用，force重建历史 |
| GET /v1/parse-runs/{id}/reading-runs | 该解析版本的精读历史 |
| GET /v1/reading-runs/{id} | 状态、配置快照、进度、有限重试次数；不返回阶段产物 |
| GET /v1/reading-runs/{id}/report | 仅完整成功返回报告，否则409；不存在404 |
| POST /jobs/{id}/retry | 复用原有显式重试机制，失败任务新增3次额度 |

模型端点为用户配置的完整chat-completions生成URL，HTTPS或loopback HTTP，无URL凭据、query、fragment。不自动探测厂商，不允许重定向，不继承系统代理。请求JSON包括model、messages、temperature=0.2、max_tokens=3000、stream=false；无tools。响应应为`choices[0].message.content`中的纯JSON字符串，结构见backend/reading.py的SYSTEM。供应商接口若不兼容，需要独立适配，不宣称支持所有服务。

凭据仅从Worker的key_env指定环境变量读取，按Bearer头发送到用户明确配置的模型端点；配置API只保存变量名，不保存密钥。更改变量值后重启Worker，改模型/端点或需要隔离缓存时重新保存配置。不要在模型名、URL或变量名中填写密钥。

每次请求90秒总时限、10秒连接/20秒网络等待、400KB响应字节上限、100000字符结构化内容上限；每块源材料JSON计数不超过12000字符，长块连续拆分保留尾部与原ID，最多100块，超出明确失败；提示词、标题和封装额外占少量输入。每次Worker尝试1200秒总预算，3次有限重试；阶段缓存按run隔离，暂停/强杀后租约恢复可复用已完成阶段。HTTP通过异步取消中止；租约与总预算在请求中轮询、保存与最终发布前再次检查。外部服务可能已计费，不能保证取消撤回远端计算。

输入哈希包括PDF SHA、parse_run_id、配置revision/endpoint/model/key_env、提示词版本及分块预算；凭据值不参与公开哈希。章节阶段保存于私有DB，完整结果和任务succeeded在同一事务提交；失败运行不修改旧成功报告。全文章节导览由各已完成章节摘要确定性组装，当前没有第二轮跨章节综合推理。

每条claim包括text、kind=fact/inference、model_verification和本地verification。来源引用包含block_id、quote、matched、regions、quality_flags。有效匹配需块属于当前输入/解析版本、原文连续短引至少8字符且存在定位。任何引用失败则该claim为unsupported；模型自称supported也最多变成unreviewed。inferred/conflicted仍需人工核验；没有自动语义支持判定。summary是未核验主题导览，不能当作已验证事实。当前发送解析文字与质量标记，不发送PDF原文件或图片；公式和复杂表格的完整语义仍受解析文本质量限制。

阅读页入口“AI分章节精读”→填写模型服务配置→点击生成。使用需密钥的服务时，在启动Worker的PowerShell中设置凭据环境变量，例如`$env:PAPERMIND_LLM_API_KEY='你的密钥'`，界面key_env填写`PAPERMIND_LLM_API_KEY`。不应把密钥贴到聊天、报告或源码。生成按钮说明会向配置服务发送当前解析文本并可能计费，用户未点击前只进行本地读取。
