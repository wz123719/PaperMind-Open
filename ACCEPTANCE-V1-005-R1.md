# V1-005 R1 开发返修交付

日期：2026-11-17。依据V1-005-review.md与V1-005-R1.md。**两项修复已实现，已完成的核验通过；剩余浏览器补验未执行，等待独立复验，尚不声明签收。**

V5-R1-A采用先保存策略，并在请求在途时锁定编辑、章节及笔记身份；V5-R1-B按YAML、数学、代码和普通正文分区导出。旧交付、验收方报告/证据均保留原样。schema仍为5，不扩展阶段或模型质量范围。

| 返修/回归项 | 结果 | 证据 |
|---|---|---|
| 先看建议、只选s02、再编辑s05 | 实际浏览器复现，最终应用禁用且显示先保存；实际点击尝试被阻止，服务端应用请求0、版本仍1，文字保留 | ui-dirty-apply-blocked.png；browser-dirty-proof.json；blocked-no-request.json |
| 取消后保留文字与建议 | 取消勾选再重选，文字相等，建议集仍显示，无写请求 | browser-dirty-proof.json；browser-operations.md |
| 保存后应用其他章节 | 保存手写后仅应用s02；SQLite比较父子版本，仅s02变化，s05内容及manual/origins不变，后续版本仍可恢复 | browser-record-verification.json；http-files-verification.json |
| 在途编辑/切换 | 真正暂停保存、应用、审核、恢复和打开另一笔记请求；编辑器及章节/笔记选择禁用，实际fill/select尝试受阻；请求结束后原内容和身份正确 | browser-save-lock.json；browser-operation-locks.json；browser-requests.json |
| 行内/块比较公式 | 真实API保存→审核→预览→发布；多条`$a < b$`、多行及单行`$$...$$`保持源码字节 | tests/test_notes_r1.py；http-files-verification.json；exported-r1.md |
| YAML元数据 | `<Graph>`、已存在实体、中文引号/冒号/换行，导出YAML解析后所有snapshot metadata字段相等 | 同上 |
| 代码与图片示例 | 围栏/行内代码尖括号与图片示例保持，不复制/下载代码示例；实际图片仍走绑定解析白名单 | 新增API发布测试；实际文件清单 |
| 安全继续有效 | 正文HTML被转义，javascript/data/vbscript/file及实体/控制符变体阻止；React安全预览原测试继续通过 | tests/test_notes_r1.py、test_notes_preview.py |
| 图片/PDF离线追溯 | 实际PNG/PDF存在且哈希匹配，保留相对链接与#page=1；实际用图一张，不复制代码里的图片 | http-files-verification.json |
| 审核/外部修改/中断/旧来源 | 新编辑未审核，过期预览409；外部修改409且另存保留原文件；实际子进程退出73后preparing，显式HTTP重试成功；旧source1提示/原消息均不升级 | http-files-verification.json；原264项回归 |
| 旧待发布计划 | 旧渲染计划拒绝提交和同键静默升级，要求新键预览；旧成功记录保持可读 | 新增版本兼容用例 |
| 完整测试 | 279 passed，0 skipped，6个既有弃用警告，90.97秒；原264项及15个新增风险用例 | pytest-final.txt |
| 类型/构建/依赖 | tsc/Vite与pip check通过；仍有大JS chunk提醒，无类型/构建错误 | frontend-build.txt；pip-check.txt |
| 历史与验收材料保护 | 正式旧行/ID、原QA与旧V5笔记历史、原11份测试Vault文件、41份验收方材料摘要不变；八组旧证据哈希一致 | history-protection.json |
| 历史API环境复核 | F盘临时目录隔离API全33成功运行及5失败限制通过；普通日常API最终空间恢复后也完整通过，1361产物含1295 PNG保持 | history-verification.json；daily-history-verification.json |
| 后续浏览器冲突恢复/最终发布 | **未执行**。自动审批初始化因C盘满失败，动作未执行；用户选择交付已完成结果并标注边界。本轮没有绕过审批重试浏览器或以HTTP冒充浏览器 | 本报告、browser-operations.md |

实现冻结为 `evidence/v5-r1/frozen-implementation.json` 的97份文件。已执行浏览器步骤的前端代码与最终冻结一致；随后新增的后端旧计划版本保护经过最终279项与实际HTTP核验，未追加浏览器操作。最终冻结后不再修改源代码。完整交付摘要、独立测试Vault文件清单及隔离库备份在新evidence/v5-r1，未覆盖旧记录。

环境过程与当前状态：开始时C盘free=0，日常API8765的638476f9结构接口500，health仍200。仅为开发/验收子进程设置F盘TEMP/TMP/SQLITE_TMPDIR，验证API8774已完成33/5核对；没有改全局环境或正式配置，也没有删除用户文件。最后检查C盘可用约3.11GB（约2.9GiB），日常API在原C盘临时目录环境重启加载R1后，该接口与完整33/5复核均通过；空间恢复原因未调查，不归因于本轮修复或清理。用户已选择停止剩余浏览器补验，因此没有因空间恢复而擅自重做浏览器流程。

正式库notes、revisions、操作、审核、发布、Vault及模型设置仍为0，旧表和原产物保持。旧八组受保护文件计数为274/232/278/25/28/41/33/43；原V5复制的4笔记、13版本、13操作、6审核、7发布记录逐行保留。普通API已加载R1，临时验收服务关闭。实际外部修改仅在新R1测试Vault中模拟；未触碰正式Vault或真实密钥，未调用外部模型。

仍保留LaTeX源码预览、Markdown子集、未实际打开Obsidian、真实模型质量未验证、跨进程目录替换竞态及非整体原子包等既有边界。普通正文中未配对的公式不被猜测为受保护数学区；支持范围见NOTES-CONTRACT-R1.md。当前交付等待复验，不自行进入下一阶段。
