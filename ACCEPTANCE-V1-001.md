# V1-001 开发交付与验收对照

> 本文件保留首轮开发记录。独立验收发现跨入口身份补全缺陷 R1，已返修；以 [R1 返修报告](ACCEPTANCE-V1-001-R1.md) 中的新验证结果为准，仍待验收方复验。

交付日期：2026-11-12（Asia/Shanghai）。本报告为开发方实测结果，供计划与验收窗口复验；不代表整个 V1 已完成。

项目绝对路径：`PaperMind`。仅新建该项目；`sources`、同步参考文件及任务书未修改。无其他聊天消息发送。

## 实现范围与设计

- React 19.1.1 / TypeScript 5.9.3 / Vite 7.1.12；PDF.js 5.4.296 渲染实际文件，支持版本选择、页码与缩放。
- FastAPI 0.140.13 / Pydantic 2.14.3 / SQLAlchemy 2.0.34 / SQLite；独立 Python Worker。没有 BackgroundTasks、Redis、Celery、LLM 或 Obsidian 写入。
- `papers` 和 `paper_files` 分离：稳定 UUID、SHA-256 唯一约束、论文内版本唯一约束，保留 arXiv vN、来源和相对路径。仅明确 arXiv/DOI 身份合并，不按标题推断。
- `jobs` / `job_events` 持久化；`BEGIN IMMEDIATE` 认领，心跳续租、过期恢复、有限自动重试和显式重试。文件提交与任务结束均检查租约，旧 Worker 无法继续提交。重试文件导入幂等，覆盖“文件保存后、任务完成前崩溃”。
- 上传校验大小、文件头和 PDF 实际可打开性；流式限制包含未提供 Content-Length 的请求。arXiv 仅访问官方 HTTPS 源，每次重定向先验证目标。
- loopback 监听、受限 Host/CORS、写入来源与自定义请求头校验；文件接口根据内部 ID 解析 storage 下路径。

## 文件清单

| 路径（相对于项目根目录） | 用途 |
|---|---|
| `backend/app.py` | API、上传、文件响应、SSE、本地来源保护 |
| `backend/db.py` | 四张数据表、数据库连接和写事务 |
| `backend/files.py` | PDF 校验、内容去重、身份与版本、存储路径边界 |
| `backend/arxiv.py` | ID/URL/version 规范化、受限下载、Atom 元数据 |
| `backend/queue.py` / `backend/worker.py` | 队列、租约、重试、持久化事件、独立 Worker |
| `backend/requirements*.txt` | 直接依赖与完整已验证依赖锁定 |
| `frontend/src/main.tsx` / `style.css` | 真实论文库、上传/任务交互、PDF 阅读 |
| `frontend/package.json` / `pnpm-lock.yaml` / `pnpm-workspace.yaml` | 固定依赖和可重复安装配置 |
| `tests/` / `pytest.ini` | 独立临时库测试与 Worker 进程验证 |
| `setup.ps1` / `start-*.ps1` / `README.md` | Windows 安装与分别启动说明 |
| `evidence/` | 实网 API/SSE 记录、测试构建输出、浏览器截图 |
| `.gitignore` / `storage/.gitkeep` | 排除运行数据、密钥、依赖和构建目录 |

## 实际执行的命令及结果

当前机器：Python 3.12.7、Node 24.22.1、pnpm 11.25.0。在此前不存在的项目目录创建 `.venv`，通过 pip 安装固定直接依赖，再生成完整 `backend/requirements.lock.txt`；前端从空目录安装依赖并生成 pnpm lockfile。干净机器仍须先安装上述 Python / Node / pnpm 前提环境；未声称做过整台 Windows 重装验证。

```powershell
python -m venv papermind\.venv
cd PaperMind
.\.venv\Scripts\python.exe -m pip install fastapi==0.140.13 uvicorn==0.52.0 sqlalchemy==2.0.34 pypdf==6.1.3 python-multipart==0.0.20 httpx==0.28.1 pytest==8.4.2
.\.venv\Scripts\python.exe -m pip freeze
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
.\.venv\Scripts\python.exe -m backend.worker
.\.venv\Scripts\python.exe -m pytest -q -rA
.\.venv\Scripts\python.exe evidence\verify_live.py
cd frontend
pnpm install
pnpm install --offline --config.confirmModulesPurge=false
pnpm run typecheck
pnpm run build
node node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173
```

本机实际 `pnpm` 命令使用 Codex 提供的完整可执行路径，见 README。初次安装需网络执行权限，已实际安装成功。pnpm 11 的全局虚拟存储设置在执行环境间存在差异，现已显式固定项目 `enableGlobalVirtualStore: false`，构建通过。8000 端口已占用，使用 8765，未停止其他服务。

最终结果：**29 passed**（约 8 秒）；`pip check` 无依赖冲突；前端 `typecheck`、`build` 退出码均为 0。输出分别见 `evidence/pytest.txt`、`pip-check.txt`、`frontend-build.txt`。交付的 `setup.ps1` 已在现有环境实际复跑成功，输出见 `evidence/setup-rerun.txt`。

## 逐项验收对照

| # | 原验收要求 | 开发方结果与证据 |
|---|---|---|
| 1 | 干净安装和启动步骤、实执命令 | **通过**。新建虚拟环境/前端依赖目录安装；README 和 PowerShell 脚本可复验。API、独立 Worker、前端实际启动；最终构建与依赖输出已保存。系统预置 Python/Node 是前提。 |
| 2 | 有效上传、列表、打开实际 PDF，无效/超限拒绝 | **通过**。浏览器从文件选择器上传三页测试 PDF，列表可见并打开渲染；实网论文 15 页实际打开。测试覆盖无效文件头、损坏结构、空文件、超限文件、带/不带 Content-Length 的请求。无效 422，超限 413。截图 `01`、`02`、`05`；API 证据 `live-api.json`。 |
| 3 | 相同文件一份、同论文新版本可查询 | **通过**。浏览器重复上传显示 duplicate；实网同一 arXiv v7 再导入 `duplicate=true`、原 file_id、仍一个版本。pytest 验证相同 DOI 不同 PDF 分配版本 1/2、同标题未知身份不强并、8 个并发保存只产生一份。 |
| 4 | arXiv 规范化及真实网络导入 | **通过（实网成功）**。现代/旧式 ID、abs/pdf URL、显式 vN 测试；恶意 URL/重定向拒绝。官方 API 和 PDF 均 HTTP 200，`1706.03762v7`，标题 Attention Is All You Need，8 位作者，年份 2017，15 页。`real-network.json`、`live-api.json`、截图 `05`。受控 transport 测试另外验证下载/限流/身份，不计入实网成功。 |
| 5 | Worker 终止/重启、租约恢复、幂等、双 Worker 竞争 | **通过（真实进程，受控远程响应）**。测试启动真实子进程，第二进程无有效认领；第一进程心跳跨初始租约仍有效；强杀、等待租约失效、重启另一进程，attempts=2 并成功保存。再导入仍一份。另测旧 Worker 禁写、最后一次租约过期转 failed、文件已提交但任务未完成时的恢复。`test_actual_worker_process_kill_restart_and_competition` 等见 pytest 输出。 |
| 6 | SSE 终态、Last-Event-ID 回放、未知任务 | **通过**。运行中 API 实际获取 queued/running/progress/succeeded，终态返回并结束；带 Last-Event-ID 仅回放后续事件；未知任务 404。`live-sse.txt`、`live-sse-replay.txt`、`live-api.json`；pytest 补测终态 ID 后为空及无效 ID 400。 |
| 7 | pytest 风险覆盖、前端构建/类型 | **通过**。29 项覆盖导入、并发去重/版本、URL/路径/来源、租约/心跳/旧 Worker 禁写、自动/手动重试、实际进程恢复、SSE。前端类型和构建通过。测试数据和日常库隔离。 |
| 8 | 实际浏览器上传、进度、列表和阅读 | **通过**。in-app 浏览器实际选择文件上传、重复上传、输入 arXiv 并提交、观察排队和字节进度/终态、打开真实文件、翻至第 2 页、放大到 140%、返回列表。截图 `01`–`07`。真实论文阅读页浏览器 warn/error 日志为空。 |

实网首轮受沙箱网络权限阻止，自动尝试三次后 failed；显式重试并在获准联网执行环境中成功，保留 attempts=4/max_attempts=6。随后通过 UI 新建任务，由独立 Worker 首次尝试成功、结果 duplicate=true。没有把网络失败或受控 fixture 当作实网成功。

## 运行证据索引

- `01-library-upload.jpg`：浏览器上传后，真实列表。
- `02-reader-page2-zoom140.jpg`：测试 PDF 第 2/3 页、140%。
- `03-import-queued.jpg`：UI 创建任务、排队。
- `04-import-progress.jpg`：实际下载字节进度。
- `05-real-arxiv-reader.jpg`：Attention Is All You Need 实际 PDF，第 1/15 页。
- `06-import-completed.jpg` / `07-final-library.jpg`：两个真实导入任务完成、论文仍一个文件版本。
- `real-network.json`：首次实网成功的完整任务结果。
- `live-api.json`：实际库/文件哈希/版本/去重/拒绝来源/非法 PDF/SSE 检查。
- `live-sse*.txt`：运行 API 的原始 SSE 与 Last-Event-ID 回放。
- `make_fixture.py`、`browser-upload-fixture.pdf`：明确标注的测试 PDF，非论文或假接口。
- `verify_live.py`：可对当前两篇验收数据运行的 API 复验脚本（会重复上传测试 PDF；不适合作为任意库的通用监控脚本）。

## 已知限制与复验关注

1. 本轮是阶段 1：没有章节树、坐标高亮、AI 精读、选文问答、Markdown 编辑或 Obsidian 发布。
2. 当前日常库保留一篇真实 arXiv 论文和一份明确标注的测试 PDF，均为验收产生。没有自动删除或垃圾回收接口；强杀可留下 `.part`，极端断电可留下无引用 blob，处理方式见 README。
3. 本轮明确拒绝加密 PDF；未知作者/DOI/年份保持 null，PDF 创建时间不推断论文年份。自定义 `/DOI`、`/arXivID` 字段之外，不做全文身份推断。
4. Vite 提示主包约 596 kB；本地 PDF.js 阅读可用，后续可按阅读路由拆包。Starlette TestClient 有迁移到 httpx2 的弃用提醒，29 项行为测试通过，当前依赖已锁定。
5. 只有 schema v1 的重复初始化；未来 schema 变更须迁移。当前无跨机器安装测试、20 篇最终验收、压力/恶意 PDF 隔离测试或生产部署承诺。
6. arXiv 依赖外部网络；当前 Worker 不读环境代理，在需要代理的网络中应先复验网络条件。API 仅 loopback，没有多用户认证；请按 README 本地运行。

开发已停在 V1-001，等待验收与下一条指令。
