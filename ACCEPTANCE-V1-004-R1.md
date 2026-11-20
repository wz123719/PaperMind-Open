# V1-004 R1 开发交付与验收记录

日期：2026-11-16。范围：V4-R1-A，保留选文语义符号。开发自验通过，等待独立验收；不进入 V1-005。

修复了删除 ASCII 连字符导致正负数错误等价的问题，同时收紧空白与字形兼容范围。来源契约升级到 `chat-source-2-symbols`；原生 PDF、解析映射、确认、提交和 Worker 执行前校验采用一致规则。旧报告、旧成功数据与正式模型设置保持不变。

| 验收项 | 开发自验结果 | 证据 |
|---|---|---|
| 正负数、减法、指数、范围与标点 | 实际 PDF 保存→原生解析→API 映射/提交；12 组双向或风险场景通过，伪造提交不建消息或任务 | tests/test_chat_signs.py；evidence/v4-r1/pytest-signs.txt |
| 安全兼容与原文偏移 | 空白、保留连字符的换行、软连字符、受限连字、全角 ASCII、中文及组合字符实 PDF 正例通过；emoji/多块/歧义与字符偏移回归通过 | 同上；tests/test_chat.py；tests/test_chat_js.py |
| 无法确认的转换拒绝 | 删除连字符/软连字符、上标折叠、数学断行误合并及截取有符号数字均拒绝 | 新增 6 个风险反例 |
| 版本与旧请求 | 旧候选、旧沿用、旧幂等键拒绝；旧 pending 及篡改的新快照执行前拒绝，provider 调用为 0，三次有限失败 | 新增版本/待执行测试；CHAT-CONTRACT-R1.md |
| 完整工程回归 | 234 passed，0 skipped，6 个现有依赖弃用警告，81.61 秒；包含原 207 项与新增 27 项 | evidence/v4-r1/pytest-full.txt |
| 前端与依赖 | tsc 与 Vite 构建成功；pip check 无损坏依赖 | frontend-build.txt；pip-check.txt |
| 真实进程协议 | 独立 API/Worker、Worker 独有凭据、实际 TCP 流式、无凭据失败、kill/租约恢复、事件回放回归通过 | 完整测试中的 tests/test_chat_processes.py |
| 最终代码浏览器 | 实际 PDF 原生拖选正数→映射→确认→发送→完成，新版来源标签可见；测试探针调用真实 API，正负互换均 unmatched；旧沿用显示重新确认错误 | evidence/v4-r1/browser-operations.md 及截图 |
| 实际 HTTP 补充 | 正负各一例正确映射；伪造及旧候选均 409；负数正确提交完成且保留原文负号；共 2 次授权替身调用，伪造/旧沿用调用为 0 | http-sign-verification.json；protocol-turns.json；wire-observations.json |
| 历史与正式库 | 33 个成功运行、1295 个 PNG、1361 个文件字节与 API 仍正确；5 个失败运行继续 409；旧 QA 的 2 会话、14 消息、7 轮、52 事件不变；正式库旧表未变，模型设置及聊天行均 0 | history-verification.json；delivery-verification.json |

完整命令：项目根目录执行 `.venv/Scripts/python.exe -m pytest -q`、`.venv/Scripts/python.exe -m pip check`；前端执行 `pnpm --dir frontend run build`（脚本包含 tsc）。新增集成核验脚本为 `evidence/v4-r1/verify_delivery.py`，仅在新隔离服务运行时使用；旧 evidence/v4 的脚本未执行写入。

最终实现冻结清单包含 84 个文件，见 `evidence/v4-r1/frozen-implementation.json`。浏览器与 HTTP 验证后逐文件复核一致。历史证据保护数量为 R2 274、R3 232、R4 278、V3 25、V3-R1 28、V4 41，均匹配原交付摘要。

构建存在 629.36 kB JS chunk 提醒，无类型或构建错误。Windows 字体实际 PDF 覆盖中文、组合字符、连字和上标；不把系统 emoji 字体在 PDF 提取器中的表现宣称为实 PDF emoji 通过，emoji 偏移由既有解析夹具与 JS 行为测试覆盖。保守规则可能拒绝真实但无法证明的断词，不会自动去连字符。模型协议替身仅验证链路；真实服务、回答准确率、延迟与费用尚未评估。V1-002 质量欠项继续保留。

当前结论仅为开发自验通过，独立验收仍待执行。
