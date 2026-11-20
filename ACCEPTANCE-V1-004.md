# V1-004 开发交付与待验收报告

2026-11-16。已按任务书实现真实PDF选文来源确认、同选文/论文内多轮问答、独立Worker真实流式、持久化事件及会话历史。**开发工程验证完成，等待独立验收；未验证真实模型质量。** 用户暂缓V1-002质量、模型稍后配置的决定保留，本轮不进入V1-005。

## 九项要求对照

| 项 | 结果与证据 |
|---|---|
| 1 数据与迁移 | 通过。schema3→4事务新增4张chat表；正式库备份后旧表全部行/hash不变，旧迁移记录不变，12份PDF哈希验证；故障回滚/重复初始化测试通过。[迁移记录](evidence/v4/library-migration.json) |
| 2 选文来源 | 通过。真实PdfPage DOM Range→多块候选→确认→提交已在浏览器完成。服务端身份、原生PDF页、解析块、原始CP范围核验；错误页/版本/文本、歧义、组合字符/emoji、多区域、跨页块错用页码均有风险测试。不可靠映射明确拒绝 |
| 3 真实流式 | 通过。独立SSE适配器接收网络增量，NDJSON text记录即时发布可读正文；3字节网络拆分/UTF-8、[DONE]、空流、坏帧、非SSE、截断、超时、上限测试通过。浏览器在模型未结束时已有草稿，[证据](evidence/v4/live-stream-proof.json) |
| 4 多轮/检索 | 通过。至少三轮选文解释→同来源追问→移除选文后论文内检索，历史/source快照已审计；另完成后续引用回归。最多3对已完成历史，未命中明确，失败/草稿不作历史原文 |
| 5 恢复/幂等/租约 | 通过。真实流中刷新、断流自动重试、人工新增预算、相同键复用/异内容拒绝、同会话串行/不同会话隔离、真实Worker强杀+API重启、旧Worker禁写、终态订阅/回放测试。start按尝试替换旧草稿；最终回答不含旧草稿 |
| 6 证据/版本跳转 | 通过。引用仅限本轮实际片段，不采信模型supported；错引和跨运行引用为unsupported。新回答无需刷新可定位，换文件时发送禁用，点击引用切回正确版本/解析；140%/90°及CropBox浏览器高亮通过 |
| 7 凭据/调用边界 | 通过。真实不同API/Worker环境：API无值、Worker合成值时成功；双方无值有限失败。设置/会话创建无调用，读取与重订阅测得新增模型调用0；凭据值未进DB/事件/日志 |
| 8 工程回归 | **207 passed，77.88秒，6个依赖弃用提醒**（原175+新增32）。类型检查/Vite构建/pip check通过；JS628.93KB大小提示非阻塞。[全量](evidence/v4/pytest-final.txt)、[进程](evidence/v4/pytest-processes-final.txt)、[构建](evidence/v4/frontend-build.txt)、[依赖](evidence/v4/pip-check.txt) |
| 9 文档/分离 | 通过。Windows启动、schema/API、NDJSON/SSE、偏移与能力边界见[CHAT-CONTRACT.md](CHAT-CONTRACT.md)。测试库独立，正式模型设置仍空，旧证据只读，未写验收方文件或向其他聊天发消息 |

当前隔离QA为2会话、7轮次：6成功、1次永久失败；其中一轮曾因替身静默超时耗尽3尝试，补心跳后用户显式重试，attempt4/max6完成；另一次实际断流在attempt3/max3完成。审计保留旧尝试事件，未删失败或把失败草稿拼成答案。[详细快照/事件](evidence/v4/protocol-turns.json)、[审计](evidence/v4/delivery-verification.json)、[浏览器记录](evidence/v4/browser-operations.md)。

## 实现与范围

新增chat_sources（原生页与块映射/轻量检索）、chat_provider（真实网络SSE与NDJSON）、chat服务/API和4张表；复用已有队列、Worker心跳/租约、模型配置及source-fragments-2校验。选文、检索来源、问题、配置revision、采用历史与哈希在提交时冻结。完整回答、引用和job终态原子提交；失败不更新旧成功。

PdfPage仅接受当前文字层的真实Range；服务端不信任其文本或坐标。支持单页最多3个相邻解析块、兼容字形/空白/连字符归一化，最终偏移回到原始Unicode字符。多区域保留；原生页与解析材料无法共同确认时拒绝，不按最近块猜测。历史选文需显式沿用且限制同会话/解析。

前端自动精读与问答共用一个可切换侧栏，提供确认卡片、问题预算、流式草稿/失败/完成状态、会话列表及逐条证据。刷新恢复论文/工作区/会话；文件/页/解析改变清除临时选文。引用按原身份切回文件和解析。原精读非流接口保持回归。

## 测试命令与冻结

工作目录PaperMind：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests/test_chat_processes.py -v
pnpm --dir frontend run build
.\.venv\Scripts\python.exe -m pip check
```

隔离协议服务：`python -m evidence.v4.protocol_server`；QA前端5174代理8771；模型替身8772；验证`python -m evidence.v4.verify_delivery`依赖这些服务。实际执行输出已保存，收尾会关闭QA服务，不在服务关闭后假称重跑HTTP通过。

实现冻结为schema4/chat-ndjson-1/chat-source-1/source-fragments-2，[冻结文件哈希](evidence/v4/frozen-implementation.json)。最终审计确认R4解析适配器不变，R2/R3/R4/V1-003/R1分别274/232/278/25/28份选定历史文件hash不变。另逐字节复核33个历史成功运行、1295资源及JSON/Markdown共1361文件，原hash一致，正式API仍可读，5个失败运行产物仍409，见[evidence/v4/history-verification.json](evidence/v4/history-verification.json)。正式库旧ID、行与历史产物保留，源资料及旧验收报告未修改。

## 局限与待验收

- 真实模型服务、语义准确率、费用和实际延迟待用户配置后评估。当前只验证满足所述SSE+NDJSON协议的兼容链路，不承诺所有供应商/模型可直接使用。
- 引文匹配只证明本轮材料可追溯；事实、推断、建议均需人工语义核验。V1-002已知公式/表格/定位风险未被本轮自动修复。
- 选文依赖原生文字层与解析块共同可匹配；扫描/OCR差异、超3块、复杂文字顺序或未能归一化的内容可能明确无匹配。没有新增跨页连续拖选，也没有字形级区域细分。
- 检索是论文内有限关键词/章节路由，不是全文理解或跨论文RAG。记录未命中与历史窗口取舍，不保证穷尽相关证据。
- 无取消按钮、笔记保存/编辑、Obsidian、跨章节综合及V1-005功能。网络取消或Worker中断不保证远端只计费一次。

等待独立验收。本报告是开发交付，不替代验收方结论。
