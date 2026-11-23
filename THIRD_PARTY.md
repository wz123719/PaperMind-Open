# 第三方组件与模型

PaperMind 的源码发布包不分发 Python/Node 依赖、模型权重、论文 PDF、用户数据库或模型凭据。安装时由用户从原始渠道下载所需依赖和模型。项目许可证不会替代这些组件各自的条款。

| 组件 | 用途与来源 |
| --- | --- |
| PyMuPDF / MuPDF | PDF 渲染、文字和定位相关解析。上游提供 AGPL 与商业许可，见 [PyMuPDF 许可说明](https://pymupdf.io/licensing)。 |
| Docling | 可选的文档结构解析和布局/表格模型，见 [Docling 项目](https://github.com/docling-project/docling)及[模型目录](https://docling-project.github.io/docling/usage/model_catalog/)。 |
| RapidLaTeXOCR | 可选的公式增强模型，见 [RapidLaTeXOCR](https://github.com/RapidAI/RapidLaTeXOCR)。 |
| MinerU | 可选的数学识别备选，见 [MinerU](https://github.com/opendatalab/MinerU)。 |
| PDF.js | 浏览器 PDF 阅读器，见 [PDF.js](https://github.com/mozilla/pdf.js)。 |

当前固定的依赖版本见 `backend/requirements.lock.txt`（默认安装，含 Docling 与 PyTorch）、`backend/requirements-core.lock.txt`（`-CoreOnly` 轻量安装）、`backend/math-runtime-requirements.lock.txt`、`backend/mineru-requirements.lock.txt` 和 `frontend/pnpm-lock.yaml`。如果另行制作用于分发的安装包，需针对实际打包进去的依赖和权重逐项核查许可证与随附声明。
