# interview_bank 资料质量清单

更新时间：2026-05-11

## 范围

本文档只记录 `interview_bank` raw 资料的文件级质量问题和索引覆盖情况。

不涉及：

- 前端
- API
- WebSocket
- mock interview 主流程
- DeepSeek / HuggingFace embedding 配置

## 当前结论

`interview_bank` 主链路仍可用：

- raw 资料：58 份
- manifest 记录：58 份
- LlamaIndex docstore 节点：7789 个
- 已进入向量索引的源文件：38 份

当前剩余问题不是 embedding 或 RAG 主链路 blocker，而是资料文件本身的可解析性问题。

## 文件类型统计

按 `data/knowledge_bases/interview_bank/raw/` 统计：

| 类型 | 文件数 | 可抽取文本 | 空文本 | 解析错误 |
| --- | ---: | ---: | ---: | ---: |
| PDF | 47 | 33 | 11 | 3 |
| PPTX | 6 | 2 | 0 | 4 |
| DOC | 2 | 2 | 0 | 0 |
| DOCX | 1 | 1 | 0 | 0 |

说明：

- 旧 `.doc` 文件串行 LibreOffice 转换可用；并发转换时可能触发 LibreOffice 进程冲突。
- 4 个 `.pptx` 实际是 `CDFV2 Encrypted`，不是 zip-based PPTX。
- 3 个 PDF 需要密码。
- 11 个 PDF 可打开但文本层为空，`PyMuPDF` 和 `pdftotext` 均抽不到文字，基本属于扫描/图片型 PDF 或不可复制文本层。

## 加密 PPTX

以下 4 个 `.pptx` 的 `file` 类型均为 `CDFV2 Encrypted`：

| 文件 | 结论 |
| --- | --- |
| `【应急处置专项】广东选调面试小班带练课.pptx` | 加密 CDFV2，python-pptx 无法解析 |
| `【社会现象专项】广东选调面试小班带练课.pptx` | 加密 CDFV2，python-pptx 无法解析 |
| `【观点理解专项】广东选调面试小班带练课.pptx` | 加密 CDFV2，python-pptx 无法解析 |
| `【计划组织专项】广东选调面试小班带练课.pptx` | 加密 CDFV2，python-pptx 无法解析 |

处理建议：

- 优先人工另存为普通 `.pptx` 或 `.pdf` 后重新入库。
- 如果必须自动处理，需要密码或可解密版本。
- 当前不建议在主流程中为这类文件做复杂绕行。

## 可解析 PPTX

以下 2 个 `.pptx` 是正常 Office 2007+ 文件，已可解析：

| 文件 | 结论 |
| --- | --- |
| `【第2套】广东选调面试小班带练课.pptx [只读].pptx` | 可解析并进入索引 |
| `【第4套】广东选调面试小班带练课.pptx` | 可解析并进入索引 |

## 需要密码的 PDF

以下 3 个 PDF 在 `pdfinfo` / `pdftotext` 中均返回 `Incorrect password`，PyMuPDF 报 `document closed or encrypted`：

| 文件 | 结论 |
| --- | --- |
| `【人际关系专项】广东选调面试小班带练课.pdf` | 需要密码 |
| `【第3套】广东选调面试小班带练课.pdf` | 需要密码 |
| `自主练习题本及解析（仅支持打印，供及第街内部学员使用）.pdf` | 需要密码 |

处理建议：

- 提供密码或替换为无密码版本。
- 如果只有打印权限版本，建议人工导出无密码 PDF 后重新入库。

## 空文本 PDF

以下 11 个 PDF 可打开，但 PyMuPDF 和 `pdftotext` 抽取字符数均为 0：

| 文件 | 页数 | `pdfinfo` 加密状态 | 结论 |
| --- | ---: | --- | --- |
| `一、【2024版】结构化面试经典试题示范作答50例（及第街）_A1204.pdf` | 41 | no | 空文本层 / 疑似扫描件 |
| `三、【2024版】结构化面试热门考点汇编200页（及第街）_A1204.pdf` | 206 | no | 空文本层 / 疑似扫描件 |
| `二、【2024版】结构化经典论证素材100页（及第街）_A1204.pdf` | 101 | no | 空文本层 / 疑似扫描件 |
| `及第街2025版结构化面试论证素材（2025广东A177）.pdf` | 108 | yes, copy:no | 空文本层 / 受限制 |
| `及第街结构化面试示范作答100题（2025广东A177）.pdf` | 70 | yes, copy:no | 空文本层 / 受限制 |
| `及第街结构化高分前辈面试笔记篇（2025广东A177）.pdf` | 93 | yes, copy:no | 空文本层 / 受限制 |
| `四、【2024版】高分学员笔记及评论文章（及第街）_A1204.pdf` | 93 | no | 空文本层 / 疑似扫描件 |
| `广东事业面试典型真题解析（及第街整理）.pdf` | 13 | no | 空文本层 / 疑似扫描件 |
| `往年上岸前辈高分面试经验（及第街整理）.pdf` | 13 | no | 空文本层 / 疑似扫描件 |
| `老夏真题100题.pdf` | 387 | no | 空文本层 / 疑似扫描件 |
| `面试真题200例-下.pdf` | 255 | no | 空文本层 / 疑似扫描件 |

处理建议：

- 如果这些资料重要，下一步应接 OCR pipeline。
- 优先 OCR 页数较少或价值较高的文件，例如真题、示范作答、论证素材。
- 不建议在当前主链路里阻塞这些文件；现有 38 个源文件已可支撑 RAG。

## 低文本 PDF

以下 PDF 能抽出少量文本，但覆盖可能不足：

| 文件 | 页数 | 抽取字符数 | 结论 |
| --- | ---: | ---: | --- |
| `面试真题200例-上.pdf` | 247 | 348 | 极低文本层 |
| `03.老夏真题100题.pdf` | 386 | 368 | 极低文本层 |

处理建议：

- 与空文本 PDF 一起纳入 OCR 候选。
- 这类文件虽然已进入索引，但检索价值很低。

## 旧 DOC 复核

以下 2 个旧 `.doc` 文件是 WPS / CDFV2 旧格式，但串行 LibreOffice 转 TXT 可用：

| 文件 | 转换后字符数 | 结论 |
| --- | ---: | --- |
| `01、论证逻辑（必背）.doc` | 16804 | 可解析 |
| `02、论证素材总结（必背）.doc` | 40502 | 可解析 |

注意：

- 并发调用 LibreOffice 转换可能出现非零退出或进程冲突。
- 当前入库流程是逐个文件解析，实际索引中已包含这两个 `.doc`。

## 已进入向量索引的源文件

当前 `docstore.json` 中记录了 38 个源文件，说明这些资料已形成文本节点并参与索引：

```text
01.老夏30道母题.pdf
01、论证逻辑（必背）.doc
02.老夏逐字稿-50母题.pdf
02、论证素材总结（必背）.doc
03.老夏真题100题.pdf
04.老夏说公务员面试.pdf
【复盘记录】结构化0706.pdf
【复盘记录】结构化250418.pdf
【第1套】广东选调面试小班带练课_20240220214758.pdf
【第2套】广东选调面试小班带练课.pptx [只读].pptx
【第4套】广东选调面试小班带练课.pptx
一、2019-2023年广东事业单位面试试题（及第街整理）.pdf
一、2019-2023年广东事业单位面试试题（及第街整理）_1715780612422.pdf
二、五套广东事业单位面试试题示范答题（及第街整理）.pdf
五、三篇2023版面试论证素材参考（及第街整理）_1715784504670.pdf
亮点合集（2022年5月2日排版定稿）（微店版）.pdf
亮点合集（2023年2月5日排版定稿）（微店纯净版）.pdf
第10节：解决领导讲话类题目.pdf
第11节：解决社会现象类题目.pdf
第12节：解决名言警句类题目.pdf
第13节：解决态度观点类题目（单一观点）.pdf
第14节：解决态度观点类题目（ab观点）.pdf
第15节：解决演讲发言类题目.pdf
第16节：解决漫画类题目.pdf
第17节：解决特殊问法答法类题目.pdf
第1节：必背模块库.pdf
第2节：解决现实问题类题目.pdf
第3节：解决情景模拟类题目.pdf
第4节：解决人际关系类题目.pdf
第5节：解决应急应变类题目.pdf
第6节：解决组织管理类题目（要素顺序）.pdf
第7节：解决组织管理类题目（时间顺序）.pdf
第8节：解决调查研究类题目.pdf
第9节：解决启示做法类题目.pdf
老夏说公务员面试（公众号：上岸的资料）..pdf
赠送1：热点押题（含山东省情).pdf
面试真题200例-上.pdf
面试课程练习.docx
```

## 下一步建议

优先级从高到低：

1. 不再阻塞主链路，保留当前索引继续使用。
2. 人工替换或解密 4 个加密 PPTX 和 3 个需要密码的 PDF。
3. 为 11 个空文本 PDF 和 2 个低文本 PDF 增加 OCR 入库方案。
4. 如果做 OCR，先做小批量验证，不直接全量 OCR 1000+ 页资料。
5. 后续重建索引后，再比较 docstore 源文件数是否从 38 提升。

## 2026-05-11 OCR 小批量验证

### 环境检查

当前环境：

- `tesseract`：不可用
- `ocrmypdf`：不可用
- `pdftoppm`：可用
- `mineru` CLI：可用，版本 `2.6.5`

Python 包情况：

- `PIL` 可用
- `opencv-python` 可用
- `mineru` 可用
- `easyocr` / `paddleocr` / `rapidocr` 不可用

### MinerU 参数结论

直接使用 MinerU OCR 并开启默认公式 / 表格解析时失败：

```text
ImportError: cannot import name 'find_pruneable_heads_and_indices' from 'transformers.pytorch_utils'
```

原因：

- 当前 `mineru` 与已安装 `transformers` 版本存在兼容问题。
- 失败发生在 MFR / 公式识别模型初始化阶段。

可行绕过方式：

```bash
mineru -p <pdf> -o <output> -m ocr -b pipeline -l ch -s <start> -e <end> -d cpu -f false -t false
```

其中：

- `-m ocr`：强制 OCR。
- `-d cpu`：使用 CPU，避免 GPU 显存问题。
- `-f false`：关闭公式解析，绕过 MFR 依赖。
- `-t false`：关闭表格解析，减少模型复杂度。

### 样本一：普通空文本 PDF

文件：

```text
广东事业面试典型真题解析（及第街整理）.pdf
```

执行页：

```text
第 0-1 页
```

命令：

```bash
mineru -p data/knowledge_bases/interview_bank/raw/广东事业面试典型真题解析（及第街整理）.pdf \
  -o /tmp/deeptutor-ocr-smoke-noft \
  -m ocr -b pipeline -l ch -s 0 -e 1 -d cpu -f false -t false
```

结果：

- OCR 成功。
- 生成 Markdown：1711 字符。
- 能识别出真题标题、题干和示范作答。
- 有少量漏字 / 错字，例如“广东”偶尔识别为“东”，但整体可用于检索。

### 样本二：copy:no 空文本 PDF

文件：

```text
及第街结构化面试示范作答100题（2025广东A177）.pdf
```

执行页：

```text
第 0-1 页
第 2-3 页
```

命令：

```bash
mineru -p data/knowledge_bases/interview_bank/raw/及第街结构化面试示范作答100题（2025广东A177）.pdf \
  -o /tmp/deeptutor-ocr-smoke-copylock \
  -m ocr -b pipeline -l ch -s 0 -e 1 -d cpu -f false -t false

mineru -p data/knowledge_bases/interview_bank/raw/及第街结构化面试示范作答100题（2025广东A177）.pdf \
  -o /tmp/deeptutor-ocr-smoke-copylock-p2 \
  -m ocr -b pipeline -l ch -s 2 -e 3 -d cpu -f false -t false
```

结果：

- 第 0-1 页 OCR 成功，生成 Markdown：470 字符，主要是封面和版权说明。
- 第 2-3 页 OCR 成功，生成 Markdown：1057 字符，能识别目录结构和题型分类。
- `copy:no` 并不阻止 OCR，只影响直接文本抽取。

### OCR 验证结论

MinerU OCR 小批量验证通过。

可行方案：

1. 对空文本 PDF / 低文本 PDF 建立 OCR 辅助入库流程。
2. 默认使用：

```text
mineru -m ocr -b pipeline -l ch -d cpu -f false -t false
```

3. 先处理页数少、价值高的资料。
4. 输出 Markdown 后，将 Markdown 作为衍生文本加入 `interview_bank`，保留原 PDF 为 raw。
5. 重建索引后检查 docstore 源文件覆盖数是否提升。

暂不建议：

- 直接全量 OCR 所有空文本 PDF。
- 默认开启公式 / 表格解析。
- 在没有转换锁的情况下并发跑 OCR 或 LibreOffice。

## 2026-05-12 OCR 辅助入库脚本

### 已新增

新增脚本：

```text
scripts/ocr_interview_pdfs.py
```

用途：

- 调用 MinerU 对指定 PDF 的指定页段做 OCR。
- 使用已验证的稳定参数：

```text
-m ocr -b pipeline -l ch -d cpu -f false -t false
```

- 将 OCR 结果整理为稳定 Markdown。
- 输出到：

```text
data/knowledge_bases/<kb-name>/ocr_text/
```

- 生成：

```text
ocr_manifest.json
```

### 重要行为

默认行为：

- 保留稳定 Markdown。
- 保留 `ocr_manifest.json`。
- 自动清理 MinerU 中间产物 `_mineru_runs`，避免后续入库时误扫到中间 PDF / Markdown。

调试行为：

```bash
python scripts/ocr_interview_pdfs.py ... --keep-runs
```

使用 `--keep-runs` 时才保留 MinerU 中间产物。

### 小样本真实执行

命令：

```bash
python scripts/ocr_interview_pdfs.py \
  --pdf data/knowledge_bases/interview_bank/raw/广东事业面试典型真题解析（及第街整理）.pdf \
  --start 0 \
  --end 1 \
  --kb-name interview_bank
```

结果：

```text
OK: .../广东事业面试典型真题解析（及第街整理）.pdf
-> data/knowledge_bases/interview_bank/ocr_text/广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md
1711 chars
```

当前输出：

```text
data/knowledge_bases/interview_bank/ocr_text/广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md
data/knowledge_bases/interview_bank/ocr_text/ocr_manifest.json
```

复核结果：

- `scripts/ingest_interview_data.py` 的 `discover_files()` 只会扫描到稳定 Markdown。
- `_mineru_runs` 已清理，不会污染后续入库。

### 测试

执行：

```bash
python -m py_compile scripts/ocr_interview_pdfs.py tests/scripts/test_ocr_interview_pdfs.py
env PYTHONPATH=. pytest -q tests/scripts/test_ocr_interview_pdfs.py tests/scripts/test_ingest_interview_data.py
```

结果：

```text
5 passed
```

### 下一步

现在可以继续扩大到小批量 OCR，但仍不建议全量 OCR。

建议顺序：

1. 先处理页数少、价值高的 PDF。
2. 每次 OCR 后人工抽查 Markdown 质量。
3. 质量可接受后，用 `scripts/ingest_interview_data.py --input-dir data/knowledge_bases/interview_bank/ocr_text --kb-name interview_bank` 进行衍生文本入库或重建索引方案验证。
4. 验证 docstore 源文件覆盖数是否提升。

## 2026-05-12 小批量 OCR 入库链路验证

### 脚本修复

发现并修复：

- 多次运行 `scripts/ocr_interview_pdfs.py` 时，`ocr_manifest.json` 原先只保留最后一次记录。
- 已改为按 `source_pdf + start + end` 合并记录。
- 同一个 PDF 页段重复 OCR 时会替换旧记录。
- 不同 PDF / 不同页段会累计保留。

新增测试覆盖：

- manifest 累计写入。
- 同页段替换旧记录。
- 默认清理 `_mineru_runs`。
- `--keep-runs` 调试保留中间产物。

### 当前 OCR 衍生文本

当前 `ocr_text` 中有 4 个稳定 Markdown：

| 文件 | 页段 | 字符数 | 结论 |
| --- | --- | ---: | --- |
| `广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md` | 0-1 | 1711 | 真题与示范作答可检索 |
| `及第街结构化面试示范作答100题（2025广东A177）__ocr_p2-3.md` | 2-3 | 1057 | 目录和题型结构可检索 |
| `面试真题200例-上__ocr_p0-1.md` | 0-1 | 219 | 封面 / 目录，检索价值较低 |
| `面试真题200例-上__ocr_p10-11.md` | 10-11 | 1355 | 正文真题解析可检索 |

`discover_files()` 复核：

```text
data/knowledge_bases/interview_bank/ocr_text/...
```

只会扫描到 4 个稳定 Markdown，不会扫到 MinerU 中间 PDF / Markdown。

### 独立 OCR smoke KB 入库

为避免覆盖主索引，本次使用独立知识库：

```text
interview_bank_ocr_smoke
```

执行：

```bash
python scripts/ingest_interview_data.py \
  --input-dir data/knowledge_bases/interview_bank/ocr_text \
  --kb-name interview_bank_ocr_smoke
```

结果：

```text
Total files: 4
RAG index: initialized
Embedding chunks: 13
```

### 检索验证

查询一：

```text
职业教育改革 家长不认可
```

结果：

- 命中 `面试真题200例-上__ocr_p10-11.md`
- 内容包含职业教育改革、家长认知、原因分析和优化职业教育举措。

查询二：

```text
长江国家文化公园 建设 认识
```

结果：

- 命中 `广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md`
- 内容包含长江国家文化公园建设、组织领导、文化特色、生态保护等示范作答。

### 测试

执行：

```bash
env PYTHONPATH=. pytest -q \
  tests/scripts/test_ocr_interview_pdfs.py \
  tests/scripts/test_ingest_interview_data.py \
  tests/services/embedding/test_huggingface_local_adapter.py \
  tests/services/embedding/test_health.py \
  tests/services/embedding/test_client_runtime.py \
  tests/services/config/test_provider_runtime.py \
  tests/services/test_rag_manifest_fallback.py
```

结果：

```text
22 passed, 1 skipped, 1 warning
```

### 当前结论

OCR 衍生文本链路已经打通：

```text
空文本 / 低文本 PDF -> MinerU OCR -> Markdown -> 独立 KB 入库 -> embedding -> RAG 检索
```

下一步可以选择：

1. 继续扩大小批量 OCR，优先处理页数少、价值高的空文本 PDF。
2. 将 `ocr_text` 的衍生文本合并进正式 `interview_bank` 索引。
3. 做一个增量索引方案，避免每次重建完整 58 份资料。

## 2026-05-12 OCR 衍生文本正式合并

### 合并策略

使用已有正式增量入口：

```text
deeptutor/knowledge/add_documents.py
```

原因：

- 该入口会把文件 stage 到正式 KB 的 `raw/`。
- 会调用 `LlamaIndexPipeline.add_documents()` 增量插入现有索引。
- 会在 `metadata.json` 中记录文件 hash，避免重复索引同一内容。

本次显式只传 4 个稳定 OCR Markdown，不传 `ocr_manifest.json`，避免 manifest 被作为正文资料入库。

### 执行命令

```bash
env PYTHONPATH=. python deeptutor/knowledge/add_documents.py interview_bank --docs \
  data/knowledge_bases/interview_bank/ocr_text/及第街结构化面试示范作答100题（2025广东A177）__ocr_p2-3.md \
  data/knowledge_bases/interview_bank/ocr_text/广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md \
  data/knowledge_bases/interview_bank/ocr_text/面试真题200例-上__ocr_p0-1.md \
  data/knowledge_bases/interview_bank/ocr_text/面试真题200例-上__ocr_p10-11.md
```

结果：

- 命令成功退出。
- 4 个 OCR Markdown 已 stage 到 `data/knowledge_bases/interview_bank/raw/`。
- `metadata.json` 已记录 4 个 OCR 文件 hash。
- `metadata.json` 增加 `incremental_add` 记录，`count=4`。

### 主索引变化

合并前：

```text
docstore nodes: 7789
source files: 38
OCR source files: 0
```

合并后：

```text
docstore nodes: 7802
source files: 42
OCR source files: 4
```

OCR source files：

```text
及第街结构化面试示范作答100题（2025广东A177）__ocr_p2-3.md
广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md
面试真题200例-上__ocr_p0-1.md
面试真题200例-上__ocr_p10-11.md
```

说明：

- `manifest.json` 仍记录原始 58 份资料。
- OCR Markdown 是增量补充资料，当前由 `metadata.json` 和 docstore 记录。
- 后续如果需要展示完整资料清单，应把 OCR 派生项单独列入 manifest 扩展字段，而不是混入原始 raw 资料数。

### 正式 interview_bank 检索验证

查询：

```text
职业教育改革 家长不认可
```

结果：

- 正式 `interview_bank` 命中 `面试真题200例-上__ocr_p10-11.md`。
- 该 OCR 文件在 top results 中排在前列。
- 返回内容包含职业教育改革、家长认知、原因分析和优化职业教育举措。

查询：

```text
长江国家文化公园 建设 认识
```

结果：

- 正式 `interview_bank` 命中 `广东事业面试典型真题解析（及第街整理）__ocr_p0-1.md`。
- 该 OCR 文件在 top results 中排在前列。
- 返回内容包含长江国家文化公园建设、组织领导、文化特色、生态保护等示范作答。

### 回归测试

执行：

```bash
env PYTHONPATH=. pytest -q \
  tests/scripts/test_ocr_interview_pdfs.py \
  tests/scripts/test_ingest_interview_data.py \
  tests/services/embedding/test_huggingface_local_adapter.py \
  tests/services/embedding/test_health.py \
  tests/services/embedding/test_client_runtime.py \
  tests/services/config/test_provider_runtime.py \
  tests/services/test_rag_manifest_fallback.py \
  tests/services/rag/test_office_parsing.py \
  tests/services/rag/test_rag_pipelines.py
```

结果：

```text
32 passed, 2 skipped, 2 warnings
```

### 当前结论

OCR 衍生文本已经正式合并进 `interview_bank` 主索引。

当前链路状态：

```text
空文本 / 低文本 PDF -> MinerU OCR -> Markdown -> 增量合并 -> 正式 interview_bank RAG 可检索
```

下一步建议：

1. 继续小批量 OCR 更多高价值页段。
2. 为 OCR 派生资料设计 manifest 扩展字段，清楚区分 original raw 和 derived OCR。
3. 后续可让 mock interview 抽题验证是否自然命中 OCR 补充内容。
