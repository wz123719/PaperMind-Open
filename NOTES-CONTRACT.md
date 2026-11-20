# 笔记与手动发布契约 V1

2026-11-16；V1-005；`structured-notes-1`。延续 `chat-source-2-symbols` 与 `source-fragments-2`，不改变旧模型结果或原始证据状态。

## 数据、版本和保存

当前实际 schema 从4升级到5。新增 `notes`、`note_revisions`、`note_operations`、`note_reviews`、`vault_settings`、`note_exports` 六表。迁移使用 BEGIN IMMEDIATE，DDL和版本记录在同一事务；错误全部回滚，重复初始化安全，高于当前支持版本的库会拒绝打开。旧表不改列、不重编ID、不重写历史行。正式迁移前留有真实库副本并验证故障回滚。

`notes`固定论文、文件ID、内部文件版本、PDF SHA及可空解析ID。切换阅读文件不能重绑已有笔记。只有成功精读可用于初始草稿或导入建议；无精读可用空模板。十二章节ID固定为s01至s12，依次为基本信息、贡献、背景问题、相关工作、框架流程、模块公式、实验、优势局限、实现复现、知识联系、个人疑问、证据参考。当前分章导览只装配到框架流程，贡献明确待跨章综合，其他不足章节留空，不填造。

每个revision保存完整JSON快照、父revision、操作类型、时间和快照SHA摘要。正文、章节来源、完整回答/轮次快照与精读报告都在数据库中；数据库是保存内容的权威，Markdown为可重现派生结果，不依赖旁路文件成功写入。单笔记最多500000字符。API不提供删除或原地更新revision的操作。恢复历史、新编辑、追加、替换和应用建议均新增revision，旧历史不删除。

保存必须提供 `expected_revision` 和8至100字符 `operation_key`；事务内重新比较head。冲突409提供提交内容、当前快照以及章节编辑的两份文字与diff。前端保留未保存文字，可明确载入新基线再人工合并。操作键绑定完整请求摘要；相同操作重放不重复插入，不同内容用同键报错。主动再次插入使用新键。创建键在创建操作命名空间内去重；创建重放返回该笔记的实际当前版本。

审核记录绑定精确revision和快照hash，只能审核当前head；任何新revision均未审核，恢复旧内容也不能沿用旧审核。保存完整回答必须是completed助理消息，且论文、文件、哈希、解析身份与笔记一致。默认追加，替换须显式mode=replace；保存完整正文、原消息和turn、来源与claims，不触发模型，不改变原消息或事件。旧契约回答可保存，显著保留旧版未复核提示，不升级到新契约。编辑导入内容后manual=true，原来源仅作历史追溯，不声称继续支持新文字。

## Markdown与安全预览

YAML由SafeDumper序列化，包含ID、type、title、authors、year、source、arxiv_id、doi、status、tags、创建/更新时间、文件/解析/精读标识、revision、parent与hash。未知信息为null，标签初始空列表。换行字符串强制双引号转义，避免标题内 `---` 被frontmatter分隔器误读；不拼接不可信键值。

编辑单位是章节Markdown，不支持整篇复杂AST反解析。预览是React元素白名单，不使用innerHTML：支持段落、标题、简单管道表格、三反引号代码围栏、引用、普通链接和部分行内格式。LaTeX行内/块公式以明确标识的源码保留显示，本轮没有接入数学排版引擎；wikilink原样显示为文本，不推断链接目标。导出保留公式、表格、围栏与wikilink，Obsidian自身可按安装的渲染能力处理。并不宣称完整CommonMark/GFM实现。

预览所有HTML按文本转义；普通链接只允许http/https/mailto及页内锚点，不执行危险URL。远程图片不加载；图片必须写为 `![说明](asset:受控ID)`，受控ID来自笔记固定成功解析运行的资产白名单。导出时图片ID换成实际相对PNG路径；任意路径、远程图片和未知ID明确拒绝，代码围栏内示例不作为图片资源复制。非代码HTML在导出中转义，已知危险URL替换为阻止标记。用户资源不下载，不从任意客户端源路径读文件。

来源页码、人读引文、状态、契约、文件SHA和解析身份随Markdown保留。导出复制绑定原PDF原字节，生成 `_resources/<note-id>/<sha>.pdf#page=N` 相对链接，UTF-8路径按URI规则编码。只复制实际引用图片与一份绑定PDF；不用localhost URL作为离线证据，不声明Obsidian支持坐标高亮。工作台内仍可打开绑定文件/解析版本及证据区域。

## Vault边界和发布状态

默认无Vault配置。用户输入已存在的本地根目录及相对输出子目录；保存设置只验证路径，不写Vault。只有点击验证才在所选根目录创建并清理一个系统命名探测文件，前端明确说明。正式配置和测试配置使用不同SQLite库，开发只使用 `storage/evaluation/v5-隔离 测试Vault`。

输出子目录拒绝绝对路径、UNC、盘符、父目录、反斜线混用、ADS冒号、控制字符、设备名（含COM/LPT上标数字形式）和尾点/空格等。现存祖先逐层lstat，拒绝符号链接、junction和其他reparse point；写入前后再次检查。源资产同样要求登记、正确成功解析、真实文件、受控根内、无reparse并核对哈希。输出文件名仅由服务端UUID生成，不使用标题或客户端文件名。仅支持本地允许硬链接的文件系统，当前在Windows本地NTFS测试；UNC、网络盘、FAT/exFAT等未验证，不承诺支持。

发布分为preview→preparing→succeeded/failed。预览必须是当前已审核精确revision/hash，冻结完整Markdown、源资源路径与哈希、Vault配置revision、上次成功文件基线及目标名；预览只写SQLite。设置或笔记后来变化，提交拒绝。实际发布同步执行，上限100MiB/500张图片；不是Worker长任务，不新增队列或隐式重试。

每个revision使用独立UUID文件名，新版本不会原地覆盖旧Markdown。更新仍检查同一输出位置的上次成功文件：外部修改、删除或变成目录均报冲突，提供外部与本地内容/diff；可以保留外部文件另存新的UUID文件，或手工合并形成新revision、重新审核后另存。首次同名未受管文件即使字节相同也不能认领。资源内容寻址且不可变，冲突不覆盖资源。

应用内通过BEGIN IMMEDIATE串行化提交，跨本应用进程也适用；先提交preparing日志，再在持有写事务时校验head、配置和基线，准备资源，最后发布Markdown，完成后核对字节并提交成功。临时文件和目标同卷，写完flush/fsync，使用无覆盖hard-link使完整单文件原子可见，然后清理本次明确归属的临时名。不是多文件包整体原子事务；没有用普通替换覆盖用户文件。

外部编辑器不遵循本应用事务，路径检查与写入之间仍有目录被替换的TOCTOU竞态；哈希检查不提供跨进程绝对无损保证。不要同时移动输出目录或修改受管资源。不可变版本文件和无覆盖发布降低风险，但不宣称在恶意并发目录替换下无条件安全。

## 失败与恢复

复制/权限/创建/数据库提交错误标failed，不删旧成功Markdown或用户文件。服务被强杀可留下preparing、已准备资源，或已写Markdown但未提交成功。重启不会自动发布；在发布历史选择该记录、查看状态并显式重试。原冻结版本仍当前且已审核、配置/基线不变，才允许恢复；已存在的资源和尝试文件必须哈希完全相符，恢复后再标成功。版本已变则重新预览；残留文件保留供人工检查。

进程异常结束可能留下本次未完成的 `.papermind-tmp-*` 文件或未被Markdown引用的受管资源；本轮没有自动垃圾清理。finally只删除本次保存的确切临时路径。不得按前缀批量清理整个Vault；人工处理前关闭应用、核对发布记录和归属，旧文件、外部文件与历史版本不自动删除。SQLite与Vault多文件没有单一原子提交，不将残留当成功。

## API

下列路径均以 `/v1` 开头，保留loopback、Origin和 `X-PaperMind-Client: workspace` 保护；PATCH纳入允许方法。GET不触发模型或发布。

| 接口 | 行为 |
|---|---|
| GET /notes?paper_id= | 列表，可省略paper_id看全部 |
| POST /notes | paper_file_id、parse_run_id可空、reading_run_id可空、title可空、operation_key |
| GET /notes/{id}?revision_id= | 当前或指定完整版本、Markdown和审核状态 |
| PATCH /notes/{id}/sections | expected_revision、operation_key、section_id、markdown |
| GET /notes/{id}/reading-suggestions?reading_run_id= | 建议和diff，不覆盖 |
| POST /notes/{id}/apply-reading | 基线/操作键、reading_run_id、所选section_ids |
| GET /notes/{id}/answer-preview?message_id= | 完整回答预览与旧契约提示 |
| POST /notes/{id}/answers | 基线/操作键、section_id、message_id、mode=append或replace |
| GET /notes/{id}/revisions | 不可变版本列表 |
| GET /notes/{id}/diff?a=&b= | 指定版本统一diff |
| POST /notes/{id}/restore | 基线/操作键、revision_id，恢复为新版本 |
| POST /notes/{id}/review | revision_id、content_hash，审核精确当前版本 |
| GET /notes/{id}/assets、/evidence | 当前绑定资源与指定revision证据 |
| GET/POST /vault-settings | 配置读取/保存；写入需root、subdir、expected_revision |
| POST /vault-settings/validate | 显式临时写入探测，不保存配置 |
| POST /notes/{id}/export-preview | revision_id、content_hash、operation_key、fork可选；冻结预览 |
| GET /notes/{id}/exports | 最近100条发布记录 |
| POST /note-exports/{id}/commit | 显式提交或恢复同一发布记录 |
| GET /note-exports/{id} | 查询冻结计划、资源清单、状态与错误 |

正式使用与恢复步骤见 NOTES-WINDOWS.md；本轮工程自验见 ACCEPTANCE-V1-005.md。原V1-002质量欠项和V1-003跨章综合缺口保留，真实模型质量和实际Obsidian程序内打开尚未验证。
