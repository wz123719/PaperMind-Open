# V1-006 开发记录

2026-11-18，按 docs/development/V1-006.md 交付 M3 翻译、术语、校验和最小阅读页入口。复用现有工程、API 代理、持久化队列、SSE、Worker 租约、坐标和 SQLite 事务迁移。

新增 translation.py、translation_protection.py、translation_provider.py、translation_api.py、两个独立 Prompt 和 TranslationPanel。数据库只新增七张表，schema 6。旧精读/问答提供商及 V1-005 R1 保存和导出逻辑沿用。原两项迁移测试随 schema 版本升级更新预期，新增翻译风险测试与实际双进程凭据测试。

保护协议为 protection-2，翻译配置 translation-2-context，Prompt academic-translation-2-context 与 glossary-extraction-1。术语处理使用带优先级的重叠跨度选择，再按真实位置替换为一次性 token，覆盖大小写、空白和 Unicode 大小写变体。上下文和目标明确区分，输入预算不截断目标。

中间测试发现 Counter 对字典取值计数导致正确 token 被拒绝，已改为对键计数；缓存完整性校验需要保留 cached=false 的原生成状态，已修正。真实全量检查超过验证脚本最初 180 秒上限，脚本改为 600 秒，执行期间有块级检查点。逐块检查和调用预算查询改为轻量索引/ID 查询，避免反复读取全部译文和响应。

验证目录 evidence/v6 与既有证据隔离，测试库 storage/evaluation/v6-browser，迁移副本 v6-migration.sqlite3。本机 8773 是显著标注 TEST ONLY 的协议替身，使用合成凭据；其中文输出是协议样例。真实 ADADELTA PDF 与既有成功解析复制到隔离库，原身份和文件哈希保留。没有调用外部模型。

最终自动化命令为 `.venv/Scripts/python.exe -m pytest -q`、前端 `tsc --noEmit`、`vite build`、`pip check`。实际 HTTP/进程检查脚本、浏览器交互和逐项结果由 ACCEPTANCE-V1-006.md 与 evidence/v6 保存。

当前范围到 006。V1-005 R1 等待独立复验，V1-002 质量暂缓、真实模型待配置的限制继续记录。007 双语三模式、008 中文问答/跨章综合、009 译文导出及 010 质量评估按后续任务分别推进。
