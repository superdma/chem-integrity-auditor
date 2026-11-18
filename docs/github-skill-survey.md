# GitHub 同类论文诚信审计工具调研（2026-11-18）

调研范围：GitHub 上的 research-integrity / paper-forensics / scientific-image
forensics 项目，重点看它们如何做图像定位、源数据统计核查、证据呈现和
Agent skill 工作流。方法为 GitHub Search API + 直接阅读 README / SKILL.md /
关键脚本；没有下载或运行第三方项目，也没有复制其代码。

## 1. 生态概览

| 项目 | Stars | 许可证 | 重点 | 对本项目最有价值的部分 |
|---|---:|---|---|---|
| [ai4s-research/ai4s-skills](https://github.com/ai4s-research/ai4s-skills) | 272 | MIT | AI4S Agent skills，含 `integrity-auditor` | 三轨证据模型、`_clean` vs `_inapplicable`、质量门 G1–G9、源数据统计检查清单、图像 panel/phash/ORB 工具链 |
| [zixixr/paperconan](https://github.com/zixixr/paperconan) | 85 | MIT | 源数据数值取证 + 报告 | 卡片式报告、发现索引、证据表单元格高亮、覆盖计数、“signal not verdict”边界 |
| [AliManjotho/open-reviewer](https://github.com/AliManjotho/open-reviewer) | 30 | MIT | 多 Agent 论文评审 | 方法/实验/引用/跨章节一致性分工；适合作为多 Agent 编排参考 |
| [taehyeonglim/paper-verifier](https://github.com/taehyeonglim/paper-verifier) | 1 | MIT | 统计声明与引用一致性 | 舍入感知的数值比对、ground-truth gate、orphan/dangling citation |
| [Fengmo997/paper-data-integrity-audit](https://github.com/Fengmo997/paper-data-integrity-audit) | 0 | 未声明 | 源数据/图像完整性 skill | 重复行、固定差/比、算术序列、末位数字 Mode A/B、精度混合、小数尾、可视化审计报告 |
| [Sandyyy123/image-integrity-screen](https://github.com/Sandyyy123/image-integrity-screen) | 0 | 专有（NOASSERTION） | 图像复制/拼接筛查 | ORB + ratio test + RANSAC 的单图 copy-move、ELA、严重度分级；仅借鉴概念 |
| [guru-bharadwaj20/ScholarGuard](https://github.com/guru-bharadwaj20/ScholarGuard) | 0 | MIT | 图像重复/拼接/AI 生成 | 内容门控 SIFT + g2NN + RANSAC + ZNCC 区域生长 + 噪声残差 clone test；三套 held-out 评估与“图数量基线”控制 |
| [Phoenix275/bioproof](https://github.com/Phoenix275/bioproof) | 0 | 未声明 | Western blot / gel | FFT 周期性、模板匹配、EXIF 设备核验、风险分档 |
| [ZJUZhiyuCai/biomed-research-integrity-auditor](https://github.com/ZJUZhiyuCai/biomed-research-integrity-auditor) | 1 | MIT | 生物医学投稿前自查 | 材料 intake、provenance graph、detector→calibrator→reporter 分层、R0–R4、覆盖与 action queue |
| [IACBI/academic-paper-forensic-auditor](https://github.com/IACBI/academic-paper-forensic-auditor) | 0 | MIT | 跨学科取证协议 | 证据变更检查、报告 diff、checkpoint 续跑、人工复核记录、覆盖状态 completed/partial/not_assessed |

## 2. 值得吸收的设计

### 2.1 单图内部 copy-move（已实现）

`image-integrity-screen` 和 `ScholarGuard` 都把“同一面板内复制一块区域”作为
独立检测项，而不是只比较两个面板。共同做法是：

1. 在**同一张图**内做特征自匹配（排除自身）；
2. 用 RANSAC 只保留几何一致的匹配簇；
3. 用像素级验证（NCC / ZNCC / 噪声残差）排除“相似但不相同”的坐标轴、
   文字和相邻面板。

我们原有 `image_dup_orb.py` 只做**跨图**比较，`spectral_segment_dup.py` 只做
一维曲线片段。新增的 `image_copy_move.py` 补上了二维单图 copy-move，并加了
透视/仿射回写 + NCC/MAD 验证。在真实电化学论文的 6 张证据图上测试，未出现
误报；合成“粘贴一块纹理”的正对照能稳定检出 1 个区域。

**没有照搬的部分**：ScholarGuard 的 g2NN、ZNCC 区域生长、噪声残差 clone test、
稠密 block-DCT 层。这些能提升平滑印迹的召回，但实现和调参成本高；当前先用
ORB + RANSAC + NCC 作为第一层，后续可用标注集评估是否值得升级。

### 2.2 源数据工作表筛查（已实现）

`ai4s-skills` 的 `decimal_match.py` / `magnitude_consistency.py` /
`xlsx_aggregate_consistency.py` 和 `paper-data-integrity-audit` 的
`source_data_workbook_audit.py` 说明：只读渲染后的 Markdown 表格会漏掉
单元格级模式。高价值、低误报的检查包括：

- 重复数值行 / 列；
- 两列固定差、固定比、近完美相关；
- 单列算术序列；
- 混合显示精度；
- 末位数字 Mode A（去尾零后的非零末位）和 Mode B（按该列最大显示精度补零）；
- 跨值重复的小数尾。

新增 `source_data_audit.py` 覆盖以上检查，输出 file/sheet/row/column 和
support count。每条 lead 都带“先排除共享校准、派生列、单位换算、技术重复”
的良性解释提示。**没有照搬**其阈值和代码；Mode B 特别限制为“该列存在更粗
精度值”或“最大精度下 0 占比过高”，避免把统一 1 位小数列误判。

### 2.3 运行级复现清单与覆盖面板（已实现）

`ai4s-skills` 的质量门要求每个 track 都有产物，且明确区分
`_clean.md`（查过、没发现）与 `_inapplicable.md`（不适用）；
`biomed-research-integrity-auditor` 输出 `coverage.json`、
`file_hash_manifest.json`、`audit_snapshot.json`；`paperconan` 报告有覆盖计数。

新增 `audit_run_manifest.py`：

- 记录 PDF/full.md/tables/figures/源数据的 SHA-256 与大小；
- 记录 Python/Pillow/numpy/OpenCV/pdfplumber/pypdfium2/openpyxl 版本；
- 统计页数、表格、图件、证据图、findings 文件；
- 输出每轨 coverage 和 `gaps`；
- `report_cards.py` 在报告旁发现该 JSON 时，自动渲染“审计材料与覆盖”面板，
  缺失项显示“缺”，并注明“缺失不等于检查为阴性”。

这比只在正文写一句“已检查”更可复核，也方便重跑时确认读的是同一份 PDF/SI。

### 2.4 证据分级与质量门（已有，补强）

`ai4s-skills` 的 G1–G9 与 `IACBI` 的 completed/partial/not_assessed 都强调：
**报告必须能回答“哪些范围没查”**。本项目已有 `report_gate.py`，这次把
覆盖清单接入报告卡片，并在 `references/06-grading-report.md` 增加“gap 写入
局限性”的要求。

`paper-verifier` 的“ground-truth gate”（有统计声明但没有基准表时硬失败）
值得记住，但它面向作者自查的统计流水线；化学论文审计没有稳定的
`results.json` 基准，暂不引入。

## 3. 暂不引入的能力

| 能力 | 代表项目 | 暂缓原因 |
|---|---|---|
| SIFT/g2NN + 区域生长 + 噪声残差 | ScholarGuard | 实现复杂、需要标注集调参；先用 ORB+NCC 覆盖高置信场景 |
| ELA / JPEG ghost / 噪声图拼接检测 | image-integrity-screen、biomed-auditor | 对 PDF 重压缩图误报高；应作为“候选提示”而非 finding |
| FFT 周期性 / PRNU / AI 生成图检测 | bioproof、ScholarGuard | 主要面向生物医学/生成图；化学谱图的周期性有合法来源（晶格、校准脉冲） |
| EXIF 设备核验 | bioproof | 期刊 PDF 图像通常已剥离 EXIF，适用面窄 |
| 引用真实性与 orphan/dangling | paper-verifier | 本轮方向未包含；且已有 `citecheck` 类工具可单独用 |
| 多 Agent 评审编排 | open-reviewer | 当前单 Agent + 确定性脚本已够用；多 Agent 成本高，需先有评测集 |
| 盲评测 harness | ZJU、ScholarGuard | 需要标注“撤稿/干净”论文集和统一指标；这是下一步最值得补的基础设施 |

## 4. 本轮落地清单

新增：

- `scripts/image_copy_move.py` — 单图 ORB 自匹配 + RANSAC + 透视回写 +
  NCC/MAD 验证 + 标注图。
- `scripts/source_data_audit.py` — XLSX/CSV/TSV 源数据统计筛查。
- `scripts/audit_run_manifest.py` — 运行级复现清单。
- `docs/github-skill-survey.md` — 本文。

修改：

- `scripts/report_cards.py` — 可选“审计材料与覆盖”面板。
- `SKILL.md`、`references/03-numeric-track.md`、`references/04-image-track.md`、
  `references/06-grading-report.md` — 工作流与解释规则。
- `README.md`、`CHANGELOG.md`、`ACKNOWLEDGEMENTS.md` — 能力、基线与出处。
- `tests/smoketest.sh` — 新增 3 组正负对照，基线 94 通过 / 0 失败。

## 5. 已知边界

- 新检测器是**初筛**，阈值未用标注集校准；真实论文上的阴性结果只代表
  “当前方法未检出”，不代表独立测量。
- `source_data_audit.py` 不判断列语义；固定差/比可能是单位换算、归一化或
  派生列，必须结合表头与上下文人工排除。
- `image_copy_move.py` 对平滑、低纹理区域（DAPI、暗胶）召回有限；对规则
  网格/对称物体可能误报，NCC 只能降低不能消除。
- 覆盖率面板里的“缺”只表示运行目录没有对应产物；如果材料在别处，应用
  `--workdir` 指向实际解析目录，或在局限性中说明。
- 未做跨论文基准评测。ScholarGuard 的结果提醒：图数量本身就能预测撤稿，
  任何新指标都应与“图数量基线”比较后再宣称有效。

## 6. 建议的下一步

1. 建一个 20–30 篇“已撤稿 + 干净对照”的小型标注集，记录每篇的图数、
   撤稿通知指控类型、可用 SI；用它测 copy-move / ORB / 源数据检查的
   召回与误报，而不是继续凭单篇调阈值。
2. 为 `image_copy_move.py` 增加 `--calibrate` 输出（不同 NCC/MAD 阈值下的
   ROC），与现有 `calibrate_image_thresholds.py` 的标注 manifest 对接。
3. 若要提升平滑图像召回，再评估 ScholarGuard 式区域生长/噪声残差，而不是
   直接堆更多特征。
4. 把 `audit_run_manifest.json` 纳入 `report_gate.py` 的硬检查（例如
   Level ≥2 报告必须至少有 PDF + full.md + 一条证据图），但先允许 `--strict`
   之外的老报告通过，避免破坏既有输出。
