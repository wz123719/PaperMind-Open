# V1-005 开发交付与逐项自验

日期：2026-11-16。范围：结构化知识笔记、完整回答保存、版本保护、人工审核和本地Vault手动发布。**开发自验通过，等待独立验收**；不自行进入下一阶段。

已形成从指定成功精读装配草稿、编辑/预览、保存完整问答、冲突处理、版本恢复、审核精确版本到手动发布Markdown/图片/离线PDF的闭环。正式库只执行schema4→5非破坏升级，没有写入测试笔记、模型或Vault配置。V1-002质量欠项及V1-003跨章综合缺口继续保留。

| 任务书项目 | 开发自验 | 证据 |
|---|---|---|
| 数据迁移 | 六张新表；实际库副本故障DDL完全回滚、重复迁移安全；正式库旧表行数、内容摘要与ID不变 | library-before.json、migration-verification.json、history-protection.json |
| 固定来源与不可变版本 | 固定论文/文件/SHA/解析；完整快照、父版本、时间、操作及hash；恢复不删历史 | backend/notes.py；tests/test_notes.py |
| 乐观并发/幂等 | 两请求只能一方保存；409保留两份与diff；同键重放不插入，新键允许主动再次插入 | 并发测试；ui-two-tabs-conflict.png |
| 十二章节与YAML | s01至s12稳定ID；不足留空，分章摘要不冒充综合；特殊标题/换行/冒号安全序列化，未知值null | YAML测试；NOTES-CONTRACT.md |
| Markdown与预览安全 | 表格、代码、链接、wikilink保留；LaTeX以源码显示；HTML转义、危险链接阻止，远程图片无img节点 | React实际静态渲染测试；ui-editor-math-table.png；ui-preview-unsafe-content-blocked.png |
| 手写保护与导入 | 建议只读，明确选择章节才应用；浏览器仅应用贡献后框架手写不变；编辑后来源只作追溯 | 建议/差异测试及browser-operations.md |
| 完整回答保存 | 正文两段完整保存至实验章节；保留原消息/turn/来源/claims；失败/生成中拒绝；旧source1保存仍提示旧版，不改变历史 | ui-refresh-answer-restored.png；http-files-verification.json；回答测试 |
| 版本/审核 | 浏览器看diff、恢复为新revision、重新审核；新编辑不继承审核；过期审核/预览/提交拒绝 | 版本与故障测试；browser-operations.md |
| 发布预览与显式提交 | 审核精确revision/hash，预览冻结目标与资源；实际检查Vault为空，点击确认后才输出 | preview-no-vault-writes.json；ui-publish-succeeded.png |
| Vault路径边界 | 已存在本地根目录、显式临时探测；拒绝遍历/盘符/UNC/ADS/设备名/尾点空格；实际Windows junction拒绝 | 参数化边界测试与实际junction测试 |
| 受控资源 | 只从固定成功解析白名单读取，缺失、未知路径、远程图片、哈希变化均失败；仅复制实际用图 | 资源缺失/篡改测试；http-files-verification.json |
| 离线可追溯 | 中文空格Vault路径；相对图片/PDF链接均存在；PDF哈希与绑定原文件一致，含#page=1、引文/身份/状态；不依赖localhost | http-files-verification.json；测试Vault实际文件 |
| 外部修改与同名保护 | 外部修改/删除/替成目录、预览后变化和同名未受管文件均拒绝；真实HTTP外部改动后保留两份另存 | 外部冲突测试；http-files-verification.json |
| 原子性/中断 | 不可变资源先写，Markdown最后无覆盖原子可见；多文件非整体事务；真实子进程写Markdown后退出73，状态preparing，HTTP重试后才成功 | 进程故障测试；http-files-verification.json |
| 真实文件权限失败 | Windows独占打开测试库源PDF造成实际PermissionError errno13，状态failed；解锁重试成功，原10个Vault文件哈希不变；未改ACL | windows-sharing-failure.json |
| 复制/文件提交/DB提交故障 | 注入三个阶段错误，状态不伪成功，恢复不破坏旧结果；并发发布及重放通过 | tests/test_notes.py |
| 发布历史与服务重启 | API重启后笔记/历史状态可读；界面可重新选择发布记录、刷新或显式恢复；不自动发布 | browser-operations.md；ui-final-publish-panel.txt |
| 原解析/模型链路回归 | 33成功解析、1295 PNG、1361文件字节和API读取保持；5失败运行仍409；原234项包含网络/凭据/kill恢复回归 | history-verification.json；pytest-final.txt |
| 历史证据与配置 | 旧七组证据摘要匹配；原QA作业/消息/轮次/事件逐行保留；正式笔记/发布/Vault/模型设置均0 | history-protection.json |

完整测试 **264 passed，0 skipped，6个既有依赖弃用警告，100.05秒**：原234项继续执行，新增30项。旧迁移测试只将目标schema断言更新到当前5，未删除测试或放宽来源检查。前端 `tsc --noEmit && vite build` 和 `pip check` 均通过，构建仍有单JS chunk超过500kB提醒，无类型/构建失败。命令与日志见 `evidence/v5/pytest-final.txt`、`frontend-build.txt`、`pip-check.txt`。首次开发用例暴露的换行YAML分隔器和另存文件名长度问题已修复，失败记录保留；HTTP补验脚本对Windows CRLF按原始字节解码比较，不把换行转换当产品错误。

冻结清单为 `evidence/v5/frozen-implementation.json` 的 **95个实现/测试/配置文件**。冻结后再次用浏览器另存并发布同一审核版本，见 `ui-final-frozen-publication.png`。最终摘要在交付清单中逐文件复核。临时服务5174/8771/8772关闭；日常API8765与Worker加载新实现，正式配置未写测试端点或Vault。单独离线测试Vault保留供验收。

旧证据保护数：V2-R2 274、R3 232、R4 278、V3 25、V3-R1 28、V4 41、V4-R1 33；解析适配器摘要保持R4版本。正式库schema_migrations仅新增版本5，既有版本行未改。原QA复制后的13作业、70作业事件、5会话、9轮、18消息、62对话事件均保持。

明确未验证/支持边界：

- 未调用真实外部模型、未读取真实密钥，不宣称模型语义质量或原解析质量通过。
- 标准程序路径和卸载/协议注册信息未发现可用Obsidian安装，**未在Obsidian程序中打开**；Web预览和离线文件核对不冒充该验证。
- 公式在工作台以LaTeX源码保留显示，没有数学排版引擎；只支持契约列出的Markdown子集。wikilink原样保留，目标由Vault自身解析，不自动创建不存在的知识笔记。
- 只在本地Windows文件系统验证无覆盖硬链接发布；UNC/网络盘/不支持硬链接的文件系统不承诺支持。目录检查存在外部并发替换竞态，普通hash检查不提供跨进程绝对无损保证。
- 同步包上限100MiB/500张图片；没有后台导出队列或自动同步。多文件不整体原子，异常可能留下preparing、孤立受管资源或本次临时文件；不自动清理用户Vault，恢复方法见NOTES-CONTRACT.md和NOTES-WINDOWS.md。

开发交付不替代独立验收，当前保持V1-005等待验收。
