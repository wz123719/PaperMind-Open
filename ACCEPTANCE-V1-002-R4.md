# V1-002 R4 开发交付与复验报告

2026-11-15。依据只读任务书`docs/development/V1-002-R4.md`和R3验收报告。**本轮实现、工程检查及指定回归已交付；新留出仍未达95%，整体质量不放行，等待独立验收，不进入V1-003。** 以下为开发代理复核，不能改写为另一个自然人完成全量标注。

| 固定组 | 内容正确 | 真实语义定位正确 | 与R3关系 |
|---|---:|---:|---|
| 原五篇、原50项 | 50/50 | 50/50 | 49项目标主内容/区域不变；BERT概率公式区域微调已核对 |
| LayerNorm原10项 | 10/10 | 10/10 | 目标主内容/区域完全保持 |
| RMSNorm原10项 | 10/10 | 10/10 | 目标主内容/区域完全保持 |
| BatchNorm原10项，现开发回归 | 10/10 | 10/10 | 原七个失败目标具备当前主结构及区域证据 |
| 新ADADELTA v1留出10项 | **7/10** | **9/10** | **未达到预冻结95%门槛**，不合并入旧组 |

partial/incorrect/unknown不计正确。ADADELTA Table1的行头关系按严格标准计partial，保留复核争议说明；即使改判正确也只有8/10，仍不达标。没有改题、删失败项、调整分母或事后制定门槛。BatchNorm10/10只覆盖原10项，**不代表整篇正文或所有数学对象都正确**，周边正文残留问题在下文列出。

## 先根因、后实现

[修改前根因记录](evidence/v2-r4/root-cause.md)包含实际输入与失败链路：

- 原PDF部分分式线、根号横线和算法边框为1×1、单色、1-bit细条图像掩码，`get_drawings()`为0。旧实现只读取矢量规则，随后错误地将二维数学压成一维脚本归属。
- 旧路由以数学字体/LaTeX语法作为主要支持条件，未检查缺根号作用范围、未消费分式和多主基线；源目标函数又被静态命令白名单遗漏arg挡住。
- 算法结构仅处理Docling的code类型；误标formula或分散text/list_item没有父对象恢复入口。普通多行公式必须保留反例。
- 行内数学仅检测分式；三面板标题在图片内部，(a)没有描述文字；图号表的caption被当作类型不匹配；数值框吸入邻行字形导致指数未恢复。
- 首页作者/正文跨栏被合成一个多区域块，旧顺序规则只处理相邻公式引导语。

实现增加物理掩码/矢量规则、结构支持检查、完整行内数学run与源/PDF标识符冲突保留；恢复caption+Input/Output+步骤证据+闭合边界支持的算法父子结构，保留已有code路径；恢复图号表格和科学计数法；按连续标签、caption引用与真实墨迹空隙关联内部三面板；分离有证据的作者/正文混合块并按栏/全宽分区排序。还修复了原行分组共享列表导致的字符重复。没有论文名触发、固定目标答案替换、自由Agent、LLM密钥或新增大型组件安装。

数据字段、支持与拒绝边界见[增量契约](STRUCTURE-CONTRACT-R4.md)。所有新关系仍为unverified候选；语法检查/树存在不能充当语义正确判据。

## 冻结与真实运行

配置`structure-v8-r4`，适配器SHA256：

`95ab0b5ef14eaf1fe74259aab137d870603f488091b08f9c483c72a2bd68fdec`

[冻结记录](evidence/v2-r4/frozen-version.json)覆盖后端与前端源码，并登记新留出协议哈希。最终九篇均使用该实现、Docling2.58.0、公式增强开启、对应源文件优先；运行前后指纹一致。模型/隔离数学环境沿用R2固定清单，没有换组件掩盖问题，未关闭公式冒充完成。

| 论文 | 最终成功运行 | 全流程秒 |
|---|---|---:|
| LayerNorm | b87bac1d-1237-4ccd-9dd8-bcc17ea423cd | 170.640 |
| RMSNorm | 541d185c-d3af-435e-8d18-910946260688 | 104.735 |
| Transformer | c9d26f1c-d14c-46d3-8d11-3bd3f8982f64 | 80.141 |
| BERT | 65867c4f-7a2a-4356-aa78-8d7052e80578 | 72.485 |
| ResNet | 8abb30aa-1ba0-4737-8560-95e78bc5b78f | 83.109 |
| Adam，真实增强开启 | 3117b12b-18f5-42e1-b4a7-14e1c8362ee0 | 179.453 |
| LoRA | be33dab0-e8cd-4955-b2bd-586e282ea98f | 164.219 |
| BatchNorm，开发回归 | 2732f2dd-151a-447d-98c7-23215cb23a72 | 70.625 |
| ADADELTA，新留出 | 706ec95a-467b-426c-b94f-15ade09fb323 | 56.234 |

完整配置、输入/模型/源哈希与作业记录见[trials.json](evidence/v2-r4/trials.json)。这些是模型初始化、增强、映射及发布的本机全流程时间，不是纯推理基准；部分论文耗时比R3增加，不宣称普遍提速。全文1200秒与原局部图像预算保持。

## 回归与七项指定修复

原50逐项前后比较见[质量复核](evidence/v2-r4/quality-review.md)、[主数据/区域比较](evidence/v2-r4/review-comparisons.json)。BERT概率式主LaTeX保持，完整数学run的框稍收紧，原图确认分子指数、分母求和和j完整。Adam算法容器的线性reading_order先于子项，caption仍为第一子项再到步骤；没有将说明放到实际步骤之后。原Adam增强及regret bound不退化。

LayerNorm/RMSNorm原20项的主内容、单元格主值和区域与R3逐项一致：[LayerNorm](evidence/v2-r4/layernorm-regression-quality-review.md)、[RMSNorm](evidence/v2-r4/rmsnorm-regression-quality-review.md)。R2-S1和六个R3关闭项保持关闭。

| BatchNorm原失败目标 | 当前正式输出及来源核对 | 开发侧结论 |
|---|---|---|
| 目标函数 | arg min下标Theta、1/N、sum_i=1^N及损失函数范围；独立公式行 | 修复 |
| 归一化显示 | widehat(x)^(k)、完整分式和sqrt(Var[x^(k)])，不额外添加本显示不存在的epsilon | 修复 |
| gamma/x-hat/beta变换 | 正文父对象关联独立数学子块，装饰符/指数作用完整，区域精确到公式行 | 修复；只评该公式 |
| Algorithm1 | Input/Parameters/Output+四顺序操作；均值/方差求和、归一化根号及缩放/平移；行/公式子对象可定位 | 修复 |
| Algorithm2 | Input/Output、原编号1-12、循环缩进、训练/推理分组；step10均值/无偏方差、step11仿射推理完整 | 修复 |
| Figure1三面板 | 3真实面板、3标题/标签、caption共7区域；有实际空隙证据，支持整体/子项 | 修复 |
| Figure3命名的表 | 4个步骤值保存科学计数法、树及mantissa/base/exponent，空值不填；保留Figure标签与caption | 修复 |

逐项与前分数见[BatchNorm复核](evidence/v2-r4/batchnorm-regression-quality-review.md)；当前父块、步骤、树、字形与来源见[真实行为核验](evidence/v2-r4/real-behavior-verification.json)。另外使用真实Adam的caption在前/code步骤版面验证，17行及数学主文本保持，浏览器核验更新行；不是所有实际核查只来自BatchNorm。匿名测试还包含无边框caption、普通多行公式等负例。

BatchNorm首页已核查标题/共享作者信息位于正文前，左栏末公式再到右栏首段；拆分保留原文字与区域。该顺序规则的泛化局限由新留出揭示，见下文，不能宣称所有双栏首页均正确。

## 已关闭源表链路保持

原六篇47源表对象仍有34候选映射、13unknown（含3个不支持源结构）；只记覆盖，不当准确率。BERT Table2的`source:000078/squad_tab.tex:3`仍有60非空单元格绑定，Dev/Test各跨2列；LoRA Table2的`source:000132/expt.tex:131`仍有63绑定及2个差异，E2E跨5列和40指标值关系保持。源定义、候选、差异、PDF主单元格与真实区域全部保留。[两个真实案例](evidence/v2-r4/source-table-real-cases.json)、[全部候选/unknown](evidence/v2-r4/source-table-final.json)。

新ADADELTA另有2个源表候选映射；这不意味着两个表都通过内容/关系验收，尤其不能用候选覆盖替代其Table1行头缺口。

## 新留出结果与明确剩余问题

新论文为[官方ADADELTA v1](https://arxiv.org/abs/1212.5701v1)，6页，PDF SHA256：

`56effcce63f62b7ad38f9fe18e0f660a95155ffa6029f8299ad4a44186deed6e`

仅查看原始PDF后冻结[10项目标](evidence/v2-r4/holdout-targets.json)，协议SHA256`13b7505fe752f3e122e588a9a27c9fd7520a915bad5c1cd8de33cff31ea8c436`；内容和定位门槛均95%，在10项分母下需10/10。实现冻结后才登记/运行/查看应用输出。源归档SHA256`69e6be050694963427f63565d6d97c87bbd20592d69d9dea62b8327f846ae835`。没有据新输出修改实现，未宣称上游模型训练排除了该论文。

开发侧判定为**内容7/10、定位9/10**，详见[新留出逐项报告](evidence/v2-r4/adadelta-holdout-quality-review.md)及完整JSON/覆盖图。失败或partial：

1. Eq5根号中的求和输出为`sum_(tau^t=1)`，上限t被错误归入下限tau。结构支持检查没有拦截这处语义错误；语法/树可用不等于正确。公式区域本身完整。
2. 无框、Require开头且被Docling拆为text/list_item的Algorithm1没有恢复入口；epsilon仍有glyph占位，8步的指数/分式平铺，没有算法父/数学子项。不能把粗步骤框当完整语义定位。
3. Table1的率指数、15个数值与列头正确，但epsilon行标签未标为row_header、数值的row_headers为空。严格按完整行头关联计partial。若验收方认可通过row索引关联即可，可就此项复核；即使改为正确，上限仍8/10，不能放行。

还观察到清单外错误，保留而未悄悄增加/替换分母：居中但宽度低于全宽阈值的首页标题/作者被排到部分正文之后；Eq10还出现邻近数学混入。当前规则支持有证据的布局，不能外推到所有居中标题、无框算法或根号内复杂求和。

BatchNorm清单外周边正文也仍有风险：新行内公式父段的未替换部分有字形/空格/根号残留，少数不完整行内分式进入`inline_math_rejections`待复核；不能用本组10/10宣称全篇数学正确。这些局限均保留在本轮结果中，不能隐去后用于AI理解输入。

若后续据ADADELTA结果调优，应将其转开发集并重新登记另一篇未观察留出。**本轮不以继续追该论文答案的方式重新计算留出成绩。**

## 工程与发布边界

| 验证 | 实际结果 |
|---|---|
| 后端原121+新增17风险行为测试 | **138 passed**，36.92秒；6个依赖弃用警告，[日志](evidence/v2-r4/pytest-final.txt) |
| 类型与构建 | `tsc --noEmit && vite build`通过；610.65KB JS chunk大小提示仍为非阻塞，[日志](evidence/v2-r4/frontend-build.txt) |
| 依赖 | pip check：No broken requirements found，[日志](evidence/v2-r4/pip-check.txt) |
| 新旧成功产物 | **33运行/1295资源**，结构/JSON/Markdown/资源真实HTTP可读且与本地字节一致；父子/引用有效，[审计](evidence/v2-r4/api-verification.json) |
| 失败API边界 | 5个失败运行的structure/json/markdown/assets均409；含R4首次失败原型，[故障/缓存审计](evidence/v2-r4/failure-cache-guard-verification.json) |
| 缓存与身份 | 8篇R3→R4的input/adapter指纹变化；原缓存隔离、租约和输入身份测试通过，未复用旧配置假冒新输出 |
| Worker/超时/有限重试 | worker、queue、DB、parse_subprocess、process_guard、parse_api六文件与R3基线哈希一致；故障行为测试通过。R1真实1200秒/恢复证据沿用，本轮没有声称重等1200秒 |
| 清理 | 最终parse_child/rapid_child/mineru_math_child无残留，所检查Python进程无读取权限缺口 |
| 冻结/历史保护 | 冻结实现与留出协议哈希不变；R4启动前60文件副本、273份R2交付证据、232份R3证据/报告/产物哈希不变；sources及验收方文件只读 |

新增测试覆盖实际1-bit规则/普通图片、arg min/分式、字形不重复、嵌套脚本作用、缺根号范围拒绝、闭合编号算法、caption/普通多行公式负例、旧code缩进、指数/普通换行数字、三面板/独立图负例、双栏父子顺序、重复数学检测合并、源/PDF变量冲突、孤立伸展字形拒绝、命名算子及无字面空格的词间距。

首次集成原型`c3371f36…`因Rect.get_area兼容问题失败；修正后显式标为失败并保留[原型失败与旧head证据](evidence/v2-r4/prototype-failure.json)，没有发布半成品，也没有声称重试预算已耗尽。之后原型及最终运行日志保留，新成功发布才更新当前head。

## 前端与交付

真实浏览器核验了公式完整行、算法整体/单步/数学子项、训练推理分组、Figure表的单元格、7区域图与第三面板、90°/140%旋转缩放、非默认CropBox、BERT源表、Adam另一版面与R3历史读取；也保留新留出失败界面。[操作与16张截图记录](evidence/v2-r4/browser-operations.md)。几何验证与真实语义分数分开，截图存在不等于内容正确。

交付包括优化源码、17新增测试、原50+20+10前后对照、新留出10项、运行/版本/耗时/哈希、源图与结构证据、发布/失败/进程审计及浏览器截图。原始最终输出在`storage/qa-renders/r4/<name>/{parsed,full}.json`；正式API和历史产物仍按既有存储身份可读。[交付清单](evidence/v2-r4/delivery-manifest.json)生成后用于校验。

**等待独立验收。原50、20和BatchNorm目标通过不能抵消新留出关键错误；整体仍处于V1-002，不进入理解、聊天、精读或笔记功能。**
