# chem-integrity-auditor

化学 / 材料 / 电化学 / 分析化学论文的**研究诚信审计 skill**。它不是“判定造假”的黑箱，而是一套可复核的证据流水线：先做确定性数值与像素检查，再由 agent 阅读证据、做良性解释压力测试，最后产出中文分级报告。

## 能查什么

- **数值轨**：收率取整、转化率×选择性、CHN 元素分析与分子式、HRMS 精确质量/加合物、Scherrer 晶粒尺寸、重复值、面积归一、不可实现单位/量程、表格重复行。
- **结构身份轨**：化合物 name/SMILES/CAS/InChIKey/分子式 → PubChem，比较分子式、MW、单同位素质量、CHN Calcd/Found、CAS、新颖性；支持盐/水合物与离线缓存。
- **图像轨**：面板切分（白沟 + 框架线 + 内容带）、dHash/aHash、ORB（旋转/镜像/裁剪）、谱图曲线与背景噪声指纹、stacked trace 切分与颜色隔离、**单条曲线内部片段复用**（patch NCC）。
- **参考谱轨**：把论文谱图峰位（两点轴校准）或峰表与 SDBS/NMRShiftDB 导出的峰表比对；不抓取数据库，只做半自动匹配。
- **逻辑轨**：合成→纯度→结构→性能的 claim chain、缺失对照、表征与结论不匹配、领域合理性。

## 安装

```bash
pip install -r requirements.txt
# poppler 提供 pdftoppm / pdfimages / pdftotext
sudo apt-get install poppler-utils     # Debian/Ubuntu
python3 scripts/check_env.py           # 检查 Python / 包 / poppler / MinerU 环境变量
```

MinerU 只在 PDF/DOI 路线的正文与 SI 解析时需要；PMC 路线用 `pmc_fetch.py`，不需要 MinerU。本地 4.x / 2.x-3.x 与官方云 v4 三种后端都支持，配置见 `references/09-mineru-setup.md`。Token 只从环境变量读取，绝不写进仓库或报告。

## 快速开始

```bash
# 1. 环境与自测
python3 scripts/check_env.py
bash tests/smoketest.sh

# 2. 建立 run 目录（见 SKILL.md Step 1）
# 3. PDF → full.md
python3 scripts/mineru_convert.py paper.pdf --output run/workdir --tier flash
# 4. 面板（poppler，不依赖 MinerU）
pdftoppm -r 300 paper.pdf run/panels/page -png
# 5. 证据台账
python3 scripts/build_evidence_ledger.py run/workdir --output run/workdir/evidence_ledger.json
# 6. 数值 / 结构 / 图像 / 片段复用
python3 scripts/chem_numeric.py run/workdir --output run/workdir/chem_numeric.json
python3 scripts/structure_check.py --batch run/workdir/compounds.json --output run/workdir/structure_check.json
python3 scripts/image_dup_orb.py run/panels/*.png
python3 scripts/spectral_segment_dup.py --image run/panels/fig2a.png --out run/workdir/segment.json
```

完整流程、门禁与报告模板见 `SKILL.md`、`references/00-setup-incremental.md` 与 `templates/audit_report.md`。

## 关键脚本

| 脚本 | 作用 |
|---|---|
| `mineru_convert.py` | PDF → full.md；local v1 / local legacy / cloud v4 |
| `pmc_fetch.py` | PMC 全文 XML + 原始 figure 文件 → full.md |
| `build_evidence_ledger.py` | 文本/HTML 表/图/caption 的 cell 级 provenance 索引 |
| `chem_numeric.py` | 化学数值异常线索 |
| `structure_check.py` | PubChem 结构身份核验（离线缓存） |
| `panel_split.py` | 多线索面板切分（白沟 / 框架线 / 内容带） |
| `stack_split.py` | 按全宽分隔线切 stacked traces |
| `image_dup.py` / `image_dup_orb.py` | 感知哈希 / ORB 变换复用（RANSAC inlier、inlier ratio、bbox、JSON） |
| `spectral_noise_fingerprint.py` | 曲线 + 背景噪声指纹 |
| `spectral_segment_dup.py` | 单条/两条曲线内部片段复用（patch NCC） |
| `reference_spectrum_match.py` | 峰表/谱图 vs SDBS/NMRShiftDB 峰表 |
| `calibrate_image_thresholds.py` | 标注对 → ROC/AUC/Youden 阈值标定 |
| `check_env.py` | 环境自检 |

## 测试

```bash
python3 tests/make_fixtures.py
bash tests/smoketest.sh
```

当前基线：**全部通过，0 失败**（fresh clone 首次运行会多一项 fixture 生成检查）。覆盖所有脚本编译/`--help`、数值正负对照、PubChem 离线缓存、参考谱匹配、图像复用、谱图指纹、面板/stack 切分、片段复用、阈值标定、MinerU 三后端 mock 与 auto fallback。

## 非协商项

- 发现是证据，不是判决：不写“造假/fraud”，写 Level 1–4 异常与“需原始数据裁定”。
- 每条发现必须有可解析的定位（markdown 行/页、表 id+行列+原值、图 id+panel、图像路径、技术）。
- 确定性脚本先跑，agent 只负责解释、做良性解释压力测试与分级。
- dHash/ORB/数据库命中本身不是造假；必须结合论文自身 claim 与第二条独立证据。
- 不抓取 SDBS；参考峰表由人工导出。
- 不修改被审计论文或其它 skill 的输出。
- Token/API secret 只从环境变量读取。

## 仓库结构

```
SKILL.md                 # skill 合同与 8 步流水线
references/00-09         # 增量执行、采集、技术目录、数值/图像/逻辑/分级、结构、参考谱、MinerU
scripts/                 # 13+ 个确定性脚本（无 LLM SDK）
templates/               # 中文 audit_report 模板
tests/                   # 生成式 fixtures + smoke + MinerU mock
.github/workflows/       # CI smoke
```

## 状态

已完成第一轮优化：多线索面板切分、PMC HTML 表进台账、单条曲线片段复用、阈值标定 harness、环境自检与 CI。下一轮优先级：真实撤稿论文 gold set（5–10 篇）、化学数值检查扩展（NMR 积分/13C 峰数、HRMS 同位素、XPS、CV/EIS）、ORB homography/inlier 证据、报告质量门可执行化。

## License

未指定；使用前请与仓库维护者确认。
