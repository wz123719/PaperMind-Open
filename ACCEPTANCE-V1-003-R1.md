# V1-003 R1 返修交付

2026-11-16。依据只读任务书`docs/development/V1-003-R1.md`，只修Worker凭据边界和阶段引文边界。**开发修复与工程验证通过，等待独立复验；最终一次浏览器补验未完成。** 不要求真实密钥，不进入V1-004。

| 要求 | 结果与证据 |
|---|---|
| R1-A：API/Worker凭据边界 | 通过。API不读取Worker变量；真正发请求的Worker检查。实际独立API/Worker子进程：API无值而Worker有合成值时202入队并鉴权成功；双方无值时也能入队，但Worker三次有限失败、报告409，没有请求发送。测试`test_reading_processes.py`两场景，不是同进程mock |
| R1-B：实际片段校验 | 通过。保存实际source和字符偏移、运行/块/片段身份；短引只匹配当前stage已发送片段，不能凭相同block_id匹配原全文。正例、未发送尾句、错引、跨块/运行、伪造片段、错偏移、无区域、跨片段边界及多区域均有测试 |
| 版本与缓存 | 通过。提示词`reading-v1-evidence-2`，契约`source-fragments-2`进入任务指纹。旧缓存/不同source重新识别；旧未完成任务要求重新生成，旧公开报告不静默改写，UI标旧版未按片段复核 |
| 有限重试/恢复/租约/预算 | 通过全量回归；新契约缓存可恢复复用，过期Worker不能保存/发布，失败不覆盖成功 |
| 全量后端 | **175 passed，52.93秒，6依赖弃用提醒**，原162加13新增实例，[日志](evidence/v3-r1/pytest-final.txt) |
| 前端/依赖 | 类型检查、Vite生产构建、pip check通过；JS616.96KB大小提示非阻塞，[构建](evidence/v3-r1/frontend-build.txt)、[依赖](evidence/v3-r1/pip-check.txt) |
| 真实本机HTTP | 最终代码重新完成独立Worker合成凭据请求、成功报告、三次503失败、失败API409与旧成功不变；检查私有source/hash/偏移，见[审计](evidence/v3-r1/delivery-verification.json) |
| 浏览器 | R1第一轮配置/生成/证据/失败/旧历史真实完成，有截图。最后私有缓存元数据补验遇工具自动审批两次超时，**未完成，不计通过**，详见[浏览器记录](evidence/v3-r1/browser-operations.md) |
| 历史保护 | R2/R3/R4分别274/232/278份选定文件及V1-003首版25份证据/报告/契约/工作记录哈希不变；旧版报告result+config哈希不变且API200；R4解析适配器SHA不变 |
| 正式库 | 旧各表行哈希与首版迁移前基线一致，schema仍3，正式精读配置/运行均0；替身仅隔离库，见[记录](evidence/v3-r1/library-protection.json) |
| 真实模型质量 | 待验证，未调用外部模型，用户仍可稍后填写配置；V1-002风险提示保留 |

最终HTTP成功运行`03fb3159-142a-46f7-94ba-34c71973180f`，失败`83241b4e-a762-40e6-95a4-6f2b942c2942`。第一轮浏览器成功`0271ab5d-fbf1-438a-bcff-0514ab1b3273`，失败`904fb523-dc94-49de-9700-4b406dc9da54`。它们属于隔离QA库，均为测试替身；旧版报告`e4d02e2c…`保持原内容与版本。

验证命令：`.venv/Scripts/python.exe -m pytest -q`；`pnpm --dir frontend run build`（含tsc）；`.venv/Scripts/python.exe -m pip check`；`python -m evidence.v3-r1.final_protocol_trial`；`python -m evidence.v3-r1.verify_delivery`。后两者依赖隔离协议服务，已保存实际成功证据，不要求在服务关闭后重跑并假称通过。

变更范围：`backend/reading.py`、`frontend/src/components/ReadingPanel.tsx`、对应测试及新增R1证据/契约/工作记录、README索引。无schema变更，无解析识别逻辑修改，无旧证据或验收方文件修改。API/Worker重启加载最终代码，正式模型设置保持为空。

使用与缓存策略见[增量契约](READING-CONTRACT-R1.md)。任务仍只承诺引用可追溯，不自动判定论断语义支持；不做第二轮跨章节分析、聊天或笔记。等待独立复验，不自行宣告V1-003正式验收通过。
