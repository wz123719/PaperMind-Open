# V1-002 R3 开发交付与质量复验报告

2026-11-14。依据任务书 `docs/development/V1-002-R3.md` 与只读 `V1-002-R2-review.md`。本报告属于开发侧复验，独立验收待办。**R3工程及指定缺陷修复已交付；新留出质量未达到预设95%，不能宣布V1-002整体质量验收通过，不进入V1-003。**

| 核验组 | R2内容 | R3内容 | R2真实语义定位 | R3真实语义定位 | 结论 |
|---|---:|---:|---:|---:|---|
| 原五篇、原50项 | 50/50 | 50/50 | 50/50 | 50/50 | 开发侧保持通过，分母和目标未变 |
| LayerNorm原10项，开发回归 | 8/10 | 10/10 | 10/10 | 10/10 | 两处已知内容缺陷修复 |
| RMSNorm原10项，开发回归 | 6/10 | 10/10 | 8/10 | 10/10 | 四处已知内容缺陷及对应定位修复 |
| 新BatchNorm v3留出10项 | — | **3/10** | — | **6/10** | **未达标**；不得合并到原50项 |

partial/incorrect不算正确，工程成功、语法检查和数学树存在均不直接算内容正确。原50中47项的目标文字/表格主值/区域完全保持，3项变化已单独核对：Adam说明公式的帽形epsilon绑定、Adam regret bound与LoRA求和公式的完整范围微调。逐项保留前后内容、运行、块ID与源图覆盖：[原50复验](evidence/v2-r3/quality-review.md)、[完整比较](evidence/v2-r3/review-comparisons.json)、[LayerNorm](evidence/v2-r3/layernorm-regression-quality-review.md)、[RMSNorm](evidence/v2-r3/rmsnorm-regression-quality-review.md)。未删除旧失败和历史证据。

## 实现与版本

配置 `structure-v7-r3`，适配器SHA256 `1b47675e9c407f8697028388087e1f3ed0ccd424e636caaf3dde92cd531079cb`，数学结构 `math-tree-2`。实现冻结记录：[frozen-version.json](evidence/v2-r3/frozen-version.json)。八次运行均使用此实现、Docling 2.58.0、公式增强开启和source_preferred开启。LN/RMS预运行与最终冻结适配器一致，最终批次复用这两个成功运行，其余六篇真实新执行，未伪称重复执行。

新增源表双向唯一内容关联；补齐算符上下限的局部裁剪、装饰符作用对象与转置结构；使用实际基线拆分类别数据行；按嵌入字体Encoding解码勾叉，保留原始值；以标签、相邻标题/图注与真实墨迹空隙建立复合图。前端增加源定义、整表/单元格定位与布尔属性展示。实现中没有论文名称、固定目标答案或专用样本替换规则。数据字段和保守拒绝条件见[增量契约](STRUCTURE-CONTRACT-R3.md)。

沿用R2的Docling布局/表格、受限TeX候选、PDF数学字形布局及受限MinerU/Rapid图像候选路线；没有新一轮组件安装或整体替换。使用R2固定模型与清单，不宣称MinerU整页表格/Paddle已整体接入。全文档1200秒、局部数学候选预算和父Worker租约控制沿用；未关闭公式以替代增强成功。

## R2-S1：真实源表映射

**支持场景开发验证通过，覆盖率并非47/47。** 原六篇有源表的47个对象，44个支持源结构解析，**34个形成候选PDF映射**；13个保持unknown（3个源结构不支持、10个缺少足够内容支持）。这只是候选覆盖数，不是内容正确率，也不是人工验收数。原始定义、展开定义、文件行号、源表与PDF候选、列数/图注/内容证据、差异和未核验状态保留。

| 论文 | 源表对象 | 源结构支持 | 候选映射 |
|---|---:|---:|---:|
| Transformer | 4 | 4 | 3 |
| BERT | 8 | 8 | 7 |
| ResNet | 11 | 10 | 7 |
| LoRA | 14 | 14 | 13 |
| LayerNorm | 3 | 1 | 1 |
| RMSNorm | 7 | 7 | 3 |

Adam和BatchNorm本次源对象中没有kind=table对象；BatchNorm中图号命名的两个表仍由PDF表格路线处理，不代表源表路线覆盖所有tabular写法。所有源表的最终候选/未知原因见[source-table-final.json](evidence/v2-r3/source-table-final.json)。

两个强制真实验证案例：

| 案例 | 源对象 → PDF | 单元格链路与原文对照 |
|---|---|---|
| BERT Table2 / SQuAD | `squad_tab.tex:3`，`source:000078` → `7071daf4…:b000080`，第7页 | 60个非空源单元格候选绑定；Dev/Test各跨2列，EM/F1分组和各行数值保留。源文件/行号、原定义、PDF主单元格、完整表头和实际区域可追溯；未将同页其他表混入 |
| LoRA Table2 / E2E | `expt.tex:131`，`source:000132` → `f3a93055…:b000073`，第7页 | 63个绑定，E2E五列子表头和40个指标值关联。Fine-Tune/BLEU=68.2等实际定位正确。源定义的居中E2E单格与PDF五列跨度、Method跨度差异明确保存；另2个未绑定源单元格保留差异，不覆盖PDF主值 |

两例实际结构、源定义、表头路径、单元格区域和反向链接保存在[source-table-real-cases.json](evidence/v2-r3/source-table-real-cases.json)，浏览器截图见[操作记录](evidence/v2-r3/browser-operations.md)。匿名测试涵盖双向重复/歧义拒绝、相同caption编号但内容不同、冲突数值不覆盖，以及3.5≠35、负号/指数差异；没有按编号/顺序强制配对。

## 六个已观察缺陷

| 目标 | R3实际结果 | 开发侧判定 |
|---|---|---|
| LayerNorm Eq1 | `a_i^l=(w_i^l)^top h^l`，转置作用于已带索引的完整w操作数；树保留transpose | 修复，公式行区域完整 |
| LayerNorm Table1 | 4行×7列，表头+Batch/Weight/Layer三方法独立；18个类别值和对应列头逐项核对 | 修复；不是只改Markdown |
| RMSNorm Eq1 | 实际PDF局部范围补齐sum下限j=1、上限m，并保留w_ij、x_j和激活项 | 内容与定位修复 |
| RMSNorm Eq2 | 两个bar均绑定a，随后保存i下标；分式sigma、gain与激活范围正确 | 修复 |
| RMSNorm Table1 | 五方法×六属性共30个✓/✗，布尔主数据与原文一致；图注同步按字体证据解码 | 修复，raw_text 3/7及字形证据保留；普通数字测试不变 |
| RMSNorm Figure1 | 图组b174包含2面板+2标题+caption共5区域；整体、面板和标题有独立层级 | 内容关联与定位修复，未包含下方正文 |

所有图表/数学候选在产品中仍标为待核验，不把开发侧检查写回为默认可信结果。原已正确的14个补充目标主内容/区域与R2完全一致；六个变化目标均保留实际原文覆盖图与候选记录。

## 新留出：Batch Normalization v3

来源：[官方arXiv版本](https://arxiv.org/abs/1502.03167v3)，PDF 11页，SHA256 `bdc69e0b568f41d8d3181cc9077a461f58fcdd1c70c9f49efe60a05ee6109655`。首次查看应用输出前已冻结来源、10目标、内容/定位规则及95%门槛（10项需10/10）；实现随后冻结，才运行并查看输出。留出目标SHA256 `fca8896f8f7a428b9ba6180cc44c0a7ba8635b7372a86483d2e4a875b9a78e41`保持。未据其结果修改实现或重新挑题，不声称上游模型训练数据排除过该论文。

结果**内容3/10、定位6/10**，逐项见[留出复核](evidence/v2-r3/batchnorm-holdout-quality-review.md)与JSON；没有事后调整门槛。摘要、Section2引导内容与Figure4命名的六列表格通过。主要失败：

- 目标函数argmin/1/N结构、归一化分式与帽形作用范围错误；不能以LaTeX/树可生成判正确。
- y/gamma/x/beta只在正文保留平面字符，缺少独立数学及公式行区域。
- Algorithm1缺少输入输出与完整四步骤，Algorithm2步骤错序、部分合成乱码，推理变换范围错误。
- Figure1三面板缺少独立子面板/标题关联。
- Figure3命名的表中前三个10^6指数仍平面化，不能按数值关联存在就算完整正确。

此外首页全局双栏阅读顺序仍有问题，摘要目标通过仅代表摘要内部完整。**这些是剩余质量缺陷，不是环境阻塞或任务成功的免责项。** 本轮遵守留出协议保留失败等待验收；若下一轮据此调优，应将其转为开发样本并重新冻结另一篇留出，不得继续称未观察样本。

## 工程、发布边界与浏览器

| 验证 | 结果与证据 |
|---|---|
| 原106测试+新增15行为测试 | **121 passed**，36.33秒；6个依赖弃用警告，[pytest-pretrial.txt](evidence/v2-r3/pytest-pretrial.txt) |
| 类型检查与生产构建 | `tsc --noEmit && vite build`通过；JS610.16KB的chunk大小提示仍存在，非失败，[frontend-build.txt](evidence/v2-r3/frontend-build.txt) |
| 依赖 | 主运行环境`pip check`：No broken requirements found；隔离数学组件沿用R2清单 |
| 原始成功输出与引用 | **21个新旧运行、705份资源**，结构/JSON/Markdown/资源真实HTTP可读并与本地字节一致，引用/父子关系有效；历史产物哈希与R2核验一致，[api-verification.json](evidence/v2-r3/api-verification.json) |
| 失败/半成品API | 4个历史失败运行的structure/json/markdown/assets均409；旧成功结果仍可读，[failure-cache-guard-verification.json](evidence/v2-r3/failure-cache-guard-verification.json) |
| 缓存失效 | 七篇旧/新配置的input_hash与adapter hash均变化；原缓存隔离/租约/运行中版本变化测试继续通过；未复用旧版本答案冒充R3 |
| 超时/租约/有限重试/原子发布 | Worker、queue、DB、parse_subprocess、process_guard及API发布边界六文件与R2哈希一致；原故障行为测试通过。R1真实1200秒/恢复证据保留，本轮没有声称重新等待1200秒 |
| 进程清理 | 八篇结束后psutil检查parse_child/rapid_child/mineru_math_child：无残留；Python进程无读取权限缺口。PowerShell CIM读取被环境拒绝，已用psutil完成检查 |
| 冻结/历史证据 | 冻结的后端/前端源码哈希一致，R2基线50文件副本及273份R2交付证据/报告哈希不变；未编辑验收方报告或sources/ |
| 浏览器 | 源表/单元格、六处修复、整体/子项定位、120%旋转、CropBox140%旋转、历史版本与留出失败均有真实操作截图；[操作记录](evidence/v2-r3/browser-operations.md) |

几何测试与真实语义定位分开统计，不用旧几何fixture成绩填充语义定位分母。前端保留未核验提示。新旧运行、原始Docling与数学候选、源定义和差异均可读取。

## 运行记录

| 论文 | 成功运行ID | 全流程秒 |
|---|---|---:|
| LayerNorm | 26002538-213b-421f-b970-81a7cfa4df94 | 138.016 |
| RMSNorm | 02ad198e-a984-44a2-9415-51a9064676d3 | 83.859 |
| Transformer | acb2d91a-60f0-45c2-9e7b-1e620781d178 | 76.343 |
| BERT | 7071daf4-dd18-4a13-b178-814108a964f3 | 68.875 |
| ResNet | 45b7a70b-9adb-431b-977d-502d9c39e3a8 | 81.093 |
| Adam，真实增强开启 | 221e7c27-2aee-459f-bf5b-8c44f713c960 | 42.297 |
| LoRA | f3a93055-da94-4c57-8737-3dfb06355047 | 151.375 |
| BatchNorm，新留出 | 9ec3cb2c-edb1-45e4-af77-48961fdcfc2a | 54.000 |

以上不是纯推理速度基准；包含本地队列、模型初始化、增强与发布，受候选缓存、源文件和硬件影响。完整配置、文件/源归档哈希、耗时和作业预算见[trials.json](evidence/v2-r3/trials.json)。冻结时间与留出登记见对应JSON。原始产物位于`storage/qa-renders/r3/<name>/{parsed,full}.json`，来源PDF/源归档按既有存储身份保留。

## 验收状态与待办

R2-S1、六个已观察目标、工程回归和原50固定清单具备开发侧通过证据。新留出**失败**，故R3不能自行放行；独立人员须复核原50、两个真实源表链路、六个修复目标与新留出失败判定。仍以至少48/50内容与定位、Adam真实增强、发布/超时边界等原标准验收，不能因工程测试全绿而降低标准。

下一步由验收方决定下一轮通用修复范围；有源文件时仍需完善无法唯一映射的数学/算法与图号表格，不以固定答案修补。若继续使用BatchNorm调优，必须更换留出。**不进入V1-003，不启用AI精读/理解功能。**
