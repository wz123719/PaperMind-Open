# V1-001 R1 返修交付

日期：2026-11-12（Asia/Shanghai）。范围仅限 `docs\development\V1-001-review.md` 的 R1。项目：`PaperMind`。开发方结论：**R1 已修复并通过本地验证，等待验收方复验**。未执行 V1-002，未改动 sources/、任务书或验收方报告，未向其他聊天发送消息。

## 修复结果

原先 SHA-256 重复分支在校验可靠元数据前直接返回。现在该分支在已有 `BEGIN IMMEDIATE` 写事务内读取原论文，先检查 arXiv/DOI 身份是否矛盾、标识是否已被其他论文占用、同一文件的 arXiv 版本是否矛盾；所有校验成功后才补全缺失字段。

- 补全原 `papers` 的缺失 arxiv_id、doi、title、authors、year；原 `paper_files.arxiv_version` 缺失时补全。
- 保留原 paper_id、file_id、内部 version、SHA-256、相对路径、创建时间和首次来源。不修改或重写已存储 PDF，不增加文件或版本。
- 保留已有非空标题、作者和年份，即使远程给出了不同值。后续普通上传缺少身份字段时，不擦除已补全的信息。
- 不能把 PDF 内的显式 DOI/arXiv 身份静默替换为矛盾的下载元数据。已有论文身份矛盾、同文件 vN 矛盾、标识归属其他论文或 DOI/arXiv 分属不同论文时，抛出 `IdentityConflict`，说明“身份冲突，需人工确认”。上传接口映射为 HTTP 409；异步 Worker 沿用现有有界重试逻辑，每次失败均将明确冲突信息持久化，达到额度后 failed。未新增自动合并 UI，也未更改队列重试规则。
- 新文件版本分支复用相同校验，防止相同 DOI 携带矛盾 arXiv ID 时静默串错论文。
- `source` 明确为首次来源，上传文件补全后仍是 `upload`。后续 arXiv 来源由持久化 jobs.type / payload.canonical / result.file_id 追溯，未新增数据库字段或改变 schema。
- 元数据检查和补全均在序列化写事务中执行，保留数据库标识唯一约束；并发冲突返回领域错误，而不是静默覆盖、移动文件或绕过归属检查。

## 验收对照与证据

所有 R1 回归数据都在测试独立临时库中；网络响应明确使用受控 `httpx.MockTransport`，调用实际 `arxiv.download` → `worker.execute` → `save_pdf` 链路，真实解析 Atom / PDF、持久化任务和文件。没有手动更新数据库来替代身份补全行为。合成 v8 不表示远端存在该版本。本轮未重新进行实网下载或浏览器 UI 操作，原有实网和浏览器证据保持历史属性。

| R1 要求 | 开发方结果 | 实测行为 |
|---|---|---|
| 跨入口补全 | 通过 | API 上传无身份 PDF A，再执行受控 Worker arXiv v7 导入同字节，返回 duplicate=true，原 paper_id/file_id 不变；论文 arXiv/DOI/year、文件 v7 得到补全，仍一篇一个文件。 |
| 后续新版本不拆分 | 通过 | 同一链路继续导入不同字节的合成 v8，仍归属原论文；内部版本为 1/2，arXiv 版本为 7/8。 |
| 重复导入幂等 | 通过 | 再次执行同字节 Worker 任务，结果 ID 相同，论文与文件记录完整快照不变；普通上传也不擦除已有字段。 |
| 非空信息与首次来源 | 通过 | 标题/作者保留上传值，已有年份不被后来不同年份覆盖；未知标题/作者/年份可正常补全。源文件除缺失 arxiv_version 外，其余字段快照不变，source 仍 upload。 |
| 身份冲突及原子性 | 通过 | 其他论文占用 arXiv 或 DOI、已有 arXiv/DOI/vN 矛盾、PDF 内显式身份矛盾均产生明确错误；冲突前后论文/文件快照相同，无部分补全。新文件上传矛盾身份返回 409。 |
| 并发补全 | 通过 | 四个并发 Worker 为同一文件补全一致身份，全部成功且仅一份记录；两个 Worker 给同一文件补不同身份，仅一个成功；两个不同原文件争同一身份，仅一个得到该身份，另一论文/文件完整保留。 |
| 全套验证 | 通过 | 原 29 项和新增 12 项共 **41 passed**，9.15 秒；前端类型检查及构建退出码为 0，pip check 无依赖冲突。 |

新增回归：`tests/test_identity_enrichment.py`（12 个用例，含参数化）。其中 `test_upload_then_worker_enrich_repeat_and_new_version` 对跨入口完整链路、身份/来源不变和后续新版本作行为断言；其他用例覆盖补全冲突和并发所有权争用。

## 实际执行的验证命令

工作目录 `PaperMind`：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_identity_enrichment.py -q -rA
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m pytest -q -rA --show-capture=no
.\.venv\Scripts\python.exe -m pip check
```

工作目录 `PaperMind\frontend`：

```powershell
node node_modules\typescript\bin\tsc --noEmit
node node_modules\vite\bin\vite.js build
```

- `evidence/r1-pytest.txt`：最终全量结果及逐用例结果，41 passed。
- `evidence/r1-typecheck.txt`：类型检查命令、退出码 0（编译器无诊断输出）。
- `evidence/r1-frontend-build.txt`：前端构建实际输出。

原 TestClient 弃用提醒、Vite 约 596 kB 主包提示仍存在，均为验收记录中的非阻塞项。没有新增依赖或 schema 迁移。

## 变更范围与复验方式

| 文件 | 变更 |
|---|---|
| `backend/files.py` | 重复文件身份补全、统一冲突检查、DOI 格式归一、保留已有信息与来源 |
| `backend/app.py` | 上传身份冲突映射 409，其他非法 PDF 仍 422 |
| `tests/test_identity_enrichment.py` | 跨入口 Worker、幂等、冲突原子性、并发补全等 12 项回归 |
| `README.md` / `ACCEPTANCE-V1-001.md` | 明确补全与来源语义，首轮记录链接到本次返修报告 |
| 本报告及 `evidence/r1-*` | 本次返修结果、命令与验证证据 |

在独立验收环境复跑上述命令即可复验，不需要真实 arXiv 网络或模型密钥。本项目运行中的 API / Worker 已在确认无 queued/running 任务后重启，以加载最新代码。测试未修改日常论文库；对历史已拆成两篇的记录不自动合并，若新导入发现身份已归属另一篇，会明确拒绝并要求人工确认。

等待 R1 复验；V1-002 尚未开始。
