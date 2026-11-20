# V1-004 问答与流式契约

2026-11-16。schema v4；chat-ndjson-1；chat-source-1；沿用source-fragments-2。会话固定绑定paper_id、paper_file_id、PDF SHA-256、parse_run_id，后续不改绑。chat_sessions/messages/turns/events只做新增表；原解析/精读保持可用。

## 使用与启动

仍在项目根目录分别启动`start-api.ps1`、`start-worker.ps1`、`start-frontend.ps1`；访问http://127.0.0.1:5173。API8765仅监听loopback，所有写请求沿用`X-PaperMind-Client: workspace`与Origin校验。升级前使用SQLite backup备份含WAL的库；本轮已备份并验证旧行不变。

模型配置继续在“AI分章节精读→模型服务配置”填写完整chat-completions URL、模型名及可选key_env。只在启动Worker的PowerShell中设置指定凭据环境变量，API不读取该变量。保存设置、打开/刷新会话和订阅事件均不发模型请求；点击发送才调用。正式库保持未配置，由用户稍后填写。密钥不要放URL、模型名、源码或聊天中。

阅读页切换“论文问答”，在PDF文字层拖选原文→“映射选文来源”→查看候选→“确认来源”→输入并发送。可持续携带当前选文追问；历史用户消息的“沿用这轮选文”是显式恢复服务端已确认来源，不冒充新的鼠标选文。可移除后询问当前论文。切页/文件/解析会清除临时选文；会话绑定不变，切到不同文件时发送禁用，可通过证据或“打开对话来源”回到正确身份。

## API

| 接口 | 行为 |
|---|---|
| POST /v1/chat-sessions | `{parse_run_id}`创建固定来源会话，201 |
| GET /v1/chat-sessions?paper_id=... | 该论文全部会话 |
| GET /v1/chat-sessions/{sid} | 会话身份/标题 |
| GET /v1/chat-sessions/{sid}/messages | 按sequence返回用户消息及助理草稿/完整/失败状态 |
| POST /v1/parse-runs/{rid}/selection-map | 选文描述→matched/ambiguous/unmatched、来源候选；不发模型请求 |
| POST /v1/chat-sessions/{sid}/messages | `{question,idempotency_key,selection?,reuse_selection_turn_id?}`返回turn/job/user/assistant ID及冻结快照，202 |
| GET /v1/chat-turns/{tid} | 状态/尝试预算/输入快照 |
| GET /v1/chat-turns/{tid}/events | 持久化SSE，Last-Event-ID或after参数回放，终态流关闭 |
| POST /v1/chat-turns/{tid}/retry | 仅失败任务，显式新增3次额度，仍受同会话串行约束 |

selection与reuse_selection_turn_id互斥。不存在404、状态/来源冲突409、输入约束422。幂等键按会话唯一；相同键同内容返回原轮次，相同键不同内容拒绝。同会话只允许一个queued/running生成，不同会话独立。

## 选文、偏移与检索

PdfPage回传实际文字层DOM Range：文件/解析/SHA、page_index、text、layer_text、layer_start/end、client_regions。只有Range两端均在当前PDF文字层内才捕获，不接受网页其他区域的选中文字。**start/end都是Python Unicode code point半开区间**，前端以Array.from转换UTF-16；emoji和组合字符不按UTF-16长度直接传。

服务器验证身份、层内范围，并用实际PDF所选页的原生文字独立确认；客户端文本/坐标不能授权新来源。再在该页的受控解析块中匹配。支持忽略空白、连字符及NFKC兼容字形，保留到原始字符位置的映射；原生页或解析材料无法可靠确认时unmatched。歧义最多20候选，用户明确确认；不按最近块猜测。最多跨3个相邻解析块，单页渲染不新增跨页拖选；已有多区域块仍保留所有区域。

模型实际source由服务端按已确认原始片段取出，保存parse/block/fragment ID、原始字符偏移、文字与质量标记。邻接上下文最多前后各350字符并单独建来源片段。历史沿用再次核验服务端保存来源及原生页，拒绝跨会话/运行沿用。

不带选文时使用论文内章节标题权重、关键词/中文二元词检索，最多8个候选块、每片至多1600字符。无命中明确记录no_hits；不声称已读全文，不引入向量库或跨论文RAG。source JSON总预算16000字符；当前选文无法纳入则拒绝，不截断。记录采用/省略的历史ID，只取最近已完成的最多6条消息（3对）、8000字符。失败/草稿不入历史；历史助理正文明确作为未核验对话，不能当作论文证据。

问题上限4000 Unicode字符，选文至少3个归一化字符、上限4000原始字符；文字层描述上限200000。前端保留超长问题并提示缩小，不使用UTF-16 maxLength静默剪贴。每轮保存问题、模型revision/端点/模型名、各契约版本、检索记录、实际source/hash、历史窗口；凭据值不进入快照。

## 模型流协议与边界

独立chat_provider发送`stream:true`、temperature0.2、max_tokens4000，读取真实`text/event-stream`。支持chat-completions的`choices[0].delta.content`与`data: [DONE]`，增量处理UTF-8和跨网络帧内容、CRLF、SSE注释心跳。非SSE/错误状态/损坏帧/截断/空流/缺[DONE]明确失败，不回退成伪流式。

模型content必须按提示输出逐行JSON，每条换行。不是把完整JSON报告显示给用户：服务端收到一条text记录即写草稿与delta，前端显示text字段。支持范围是满足以下输出协议的模型服务，尚未验证真实模型兼容性。

```json
{"type":"text","text":"一小段可读正文，生成后即输出。"}
{"type":"text","text":"下一段正文。"}
{"type":"claim","claim":{"text":"一个论断","kind":"fact","verification":"supported","evidence":[{"block_id":"本轮完整块ID","quote":"实际source中的连续短引"}]}}
{"type":"end"}
```

kind为fact/inference/advice，分别是论文事实/AI推断/工程建议。verification允许supported/inferred/unsupported/conflicted，但服务端不采信模型自报supported：原运行、实际片段、偏移、至少8字符连续引文和定位均有效，最多标unreviewed；推断为inferred、缺证为unsupported、矛盾为conflicted。所有正文均待语义核验；完整结构检查不证明结论正确。

每请求120秒总时限、10秒连接/20秒网络空闲、400KB响应、64K帧/记录缓冲、32000正文字符、600条记录、12条claims；每次尝试180秒检查，默认3次有限尝试。没有自动取消按钮；租约失效会取消HTTP流。远端可能已部分计费，重试/强杀不保证exactly-once模型调用或退款。

## 持久化与重放

user消息completed；assistant从draft到completed或failed，尝试号和错误单独保存。专用消息接口允许恢复未完成草稿，但不会伪装为最终回答。只有正文/claims完整、引用校验结束后，消息completed、references/completed事件和job成功在同一事务提交。

chat_events全局单调ID，带turn_id与attempt；类型start（reset）、delta、references、completed、failed、retrying。每个text记录批次事务写入，不按每token开事务。租约、Worker及尝试号在写入前校验；过期Worker不可写delta/保存/结束。重试的start替换旧草稿，不拼到旧尾部；旧尝试事件保留供审计。前端按event_id去重、按attempt重置，断线自动Last-Event-ID恢复；刷新从持久化事件重建。终态后再次订阅可回放，最后ID后返回空流。

引用保留原文件/解析身份和全部区域。若当前读另一版本，明确显示会话身份不符并禁止发送；点击证据切回正确文件/解析，然后用原坐标高亮。解析质量风险及逐条证据状态一直可见。模型输出仅数据，不提供文件、系统、网络工具权限。
