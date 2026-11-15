# 10 — 跨论文图库与可执行报告质量门

本文件覆盖两个“最后一公里”组件：如何把“首次发表于 ref. 1”变成可复核的
本地比对，以及如何在交付前用脚本而不是记忆检查报告。

## A. 跨论文参考图库

### 什么时候需要

撤稿通知出现以下表述时：

- “first published in ref. 1 as another material”
- “partially identical to data published in ref. 1”
- “the same data were used in our previous paper”

这类指控的对象是**另一篇论文**。dHash/ORB 只能在同一运行目录内比较，必须
先有一个本地参考图库。

### 伦理与版权

- **只手工导出**：从出版社页面、机构订阅、作者提供的 PDF/SI 中导出图片。
  本项目不抓取出版社页面，也不批量下载数据库。
- 参考图仍是出版社版权，**只放在本地 corpus 目录**，不要提交到仓库、
  报告或 manifest。报告只写 DOI、图号、文件名和匹配指标。
- 在 `meta.json` 的 `license` / `note` 字段记录来源与使用限制。

### 目录结构

```text
corpus/
├── 10.1016-j.matchemphys.2023.127793/
│   ├── meta.json
│   └── figures/
│       ├── ref1-fig1.png
│       └── ref1-fig2.png
└── 10.1039-d0ra09390d/
    └── ...
```

`meta.json` 由 `corpus_add.py` 生成，含 DOI、标题、来源 URL、许可证、每张图
的 sha256。不要手改 sha256；换图时用 `--force` 重新登记。

### 登记

```bash
python3 scripts/corpus_add.py --corpus corpus \
  --key 10.1016/j.matchemphys.2023.127793 \
  --doi 10.1016/j.matchemphys.2023.127793 \
  --title "FeSe2/TiO2 heterostructure ..." \
  --figure ref1-fig1.png --figure ref1-fig2.png \
  --source-url https://doi.org/10.1016/j.matchemphys.2023.127793 \
  --license "publisher copyright; local audit use only"
```

`--key` 会做文件名安全化；建议直接用 DOI。`--dry-run` 可先看计划。

### 匹配

```bash
python3 scripts/corpus_match.py \
  --query output/.../panels \
  --corpus corpus \
  --json corpus_matches.json --md corpus_matches.md
```

- 查询对象优先用 `panels/`（面板级），不要只用整图：复用往往只涉及一个
  panel。
- 每个候选给出：dHash 距离、ORB matches、RANSAC inliers、inlier ratio、
  方向（same/mirror）、目标 bbox、参考 DOI。
- 阈值：`inliers >= 12` 且 `matches >= 30`，或 dHash `< 12`，为强候选；
  `matches >= 12` 或 dHash `< 28` 为弱候选。阈值是默认值，有标注对时用
  `calibrate_image_thresholds.py` 复核。

### 如何解释

强候选只说明“相同像素/特征几何再次出现”。必须做良性解释压力测试：

| 良性解释 | 检验 |
|---|---|
| 同一晶相/同一标准卡片 | 比较峰位与相对强度；相同相本来就会重叠 |
| 同一批次、同一仪器的再绘图 | 检查是否有独立噪声；共享噪声才是强线索 |
| 同一示意图被合法引用 | 看 caption 是否引用 ref. 1，是否标注 adapted |
| 同一作者前作的同一实验 | 看实验描述、样品编号、时间线；若通知已指控，仍需原始数据 |

报告写法：

```text
Fig. 3a（`panels/...png`）与 ref. 1 Fig. 2b（corpus key 10.1016/...，
本地文件 ref1-fig2.png）在 ORB 下 63 matches / 51 inliers（ratio 0.81，
same orientation，bbox x67–371, y91–165），dHash 距离 4。相同峰位可由同一
晶相解释；但两者共享背景噪声（noise_corr 0.60），该解释不足以覆盖全部
重叠区域。需作者提供两图的原始导出文件与采集日期。
```

## B. 无分隔线 offset 堆叠谱

`stack_split.py` 依赖全宽黑色分隔线。XRD/FTIR 常见“无分隔线、仅垂直偏移”
的堆叠。`offset_stack_split.py` 是**半自动**的：

```bash
# 1) 看候选切线
python3 scripts/offset_stack_split.py fig.png --propose

# 2) 确认后精确切分
python3 scripts/offset_stack_split.py fig.png bands/ --cuts 159,293,387,497

# 或让工具按 trace 数提议并切分
python3 scripts/offset_stack_split.py fig.png bands/ --traces 5
```

- 候选切线来自“垂直膨胀后的行墨迹剖面”，并对左/中/右三个竖条取最小值，
  以压制单侧图例/标签。
- 自动提议在 5 条 offset XRD 上可给出正确切线；但淡曲线、宽峰、落在空隙
  里的标签都可能让切线偏移几像素。**切错会静默改变比较结果**，所以必须
  目视确认，并在 finding 里记录使用的 cuts。
- 切出的 band 只用于形状/噪声比较；不要对同一父图的 band 互相比噪声
  （它们共享父图的 JPEG 纹理），除非 band 来自不同原图。

## C. 可执行报告质量门

```bash
python3 scripts/report_gate.py "$RUN/audit_report.md" \
  --run-dir "$RUN" --json "$RUN/report_gate.json" --strict
```

退出码：`0` 通过；`1` 有 error（`--strict` 时 warning 也算）；`2` 文件
不可读。交付时连同 `report_gate.json` 一起给出。

检查项：

1. 章节 1–7 齐全（论文信息、范围与方法、发现、各线小结、原始数据、
   局限性、质量门自检）。
2. 每个 `####` finding 含 `位置 / 技术 / 观察 / 良性解释 / 压力测试`。
3. Level ≥ 2 的 finding：至少一个证据路径能在报告目录或 `--run-dir` 下
   解析；没有路径时，必须有 `Fig + panel` 或 `Table + row/col` 结构化定位。
4. 无残留占位符（`<title>`、`<N>`、`<path>`…）。
5. 不出现“造假/伪造/篡改/fraud/fabricat”，除非同一行是通知原文引用或
   明确的“不下此结论”说明。
6. 数值线/图像线/逻辑线三行都有 `clean / 有发现 / 部分不适用 / 不适用`。
7. 第 7 节没有未勾选 `- [ ]`；勾选少于 5 项给 warning。

常见失败与修法：

- **missing field '压力测试'**：补上“最强良性解释是什么、如何检验、结果
  成立/不成立”，不要只写“已排除”。
- **no evidence path resolves**：报告里的 `panels/...png` 是相对运行目录
  写的；确认 `--run-dir` 指向包含 `panels/` 的那一层，或改写成真实路径。
- **verdict word**：把“数据造假”改成“与通知原文一致/高度疑似失实”或
  “需原始数据裁定”；若确为引用，放在引号内并在同一行写“通知原文”。
- **unchecked checklist**：第 7 节是交付前自检，确实是逐项跑过才勾。

质量门不是学术判断的替代品：它只能证明“格式与定位可复核”，不能证明
Level 分级正确。分级仍由 agent 的良性解释压力测试决定。
