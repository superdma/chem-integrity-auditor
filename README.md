# chem-integrity-auditor

化学 / 材料 / 电化学 / 分析化学论文的**研究诚信审计 skill**。它不是“判定造假”的黑箱，而是一套可复核的证据流水线：先做确定性数值与像素检查，再由 agent 阅读证据、做良性解释压力测试，最后产出中文分级报告。

> **把仓库链接发给 Agent 就能安装。** 支持 Claude Code、Cherry Studio、以及任何会读 `SKILL.md`、能执行 shell 的通用 Agent 客户端。

---

## 一、把仓库交给 Agent 安装

### 方式 A：直接发链接（推荐）

把下面这段原样发给你的 Agent 客户端：

```text
请从 https://github.com/superdma/chem-integrity-auditor 安装 chem-integrity-auditor skill：
1) 将仓库克隆到你使用的客户端的 skills 目录（Claude Code 用 ~/.claude/skills/，
   Cherry Studio 用其 Data/Skills/，其它客户端用其文档指定的 skill 目录）；
2) 安装依赖：python3 -m pip install -r requirements.txt；
3) 安装 poppler（提供 pdftoppm/pdfimages/pdftotext）；
4) 运行 python3 scripts/check_env.py 和 bash tests/smoketest.sh；
5) 把安装路径、check_env 结果和 smoke 结果发给我。
不要修改仓库外的文件，不要把任何 token 写入仓库。
```

Agent 会自己完成克隆、依赖安装和自检。装好后，直接把论文 PDF 路径或 DOI 发给它即可。

### 方式 B：Claude Code

```bash
# 个人级（所有项目可用）
git clone https://github.com/superdma/chem-integrity-auditor.git \
  ~/.claude/skills/chem-integrity-auditor

# 或项目级（只在该项目可用）
git clone https://github.com/superdma/chem-integrity-auditor.git \
  .claude/skills/chem-integrity-auditor

python3 -m pip install -r ~/.claude/skills/chem-integrity-auditor/requirements.txt
python3 ~/.claude/skills/chem-integrity-auditor/scripts/check_env.py
```

### 方式 C：Cherry Studio

把仓库放到 Cherry Studio 的 Skills 目录，或在「设置 → Skills / 技能」中导入该目录：

```bash
# Linux
git clone https://github.com/superdma/chem-integrity-auditor.git \
  ~/.config/CherryStudio/Data/Skills/chem-integrity-auditor

# macOS（以客户端设置中显示的 Data/Skills 路径为准）
git clone https://github.com/superdma/chem-integrity-auditor.git \
  "$HOME/Library/Application Support/CherryStudio/Data/Skills/chem-integrity-auditor"

# Windows PowerShell（以客户端设置中显示的 Data/Skills 路径为准）
git clone https://github.com/superdma/chem-integrity-auditor.git `
  "$env:APPDATA\CherryStudio\Data\Skills\chem-integrity-auditor"
```

目录名可以随意，但必须保证 `chem-integrity-auditor/SKILL.md` 在目录根。重启或刷新 Skills 列表后，在对话里说“用 chem-integrity-auditor 审计这篇论文”。

### 方式 D：手动下载 ZIP

1. 打开 <https://github.com/superdma/chem-integrity-auditor> → **Code → Download ZIP**。
2. 解压到客户端的 skills 目录，确保 `SKILL.md` 位于解压目录根（不要多套一层文件夹）。
3. 安装依赖并自检（见下）。

### 依赖

```bash
python3 -m pip install -r requirements.txt

# poppler：pdftoppm / pdfimages / pdftotext
sudo apt-get install poppler-utils     # Debian / Ubuntu
brew install poppler                   # macOS
# Windows 建议在 WSL 中运行，或把 poppler 的 bin 加入 PATH

python3 scripts/check_env.py           # 必须输出 Overall: OK
bash tests/smoketest.sh                # 必须 0 failures
```

- Python 3.8+；Pillow、NumPy、OpenCV、SciPy。
- RDKit 可选（结构与分子式交叉校验）。
- **MinerU 可选**：只在 PDF/DOI 路线的正文与 SI 解析时需要；PMC 路线用 `pmc_fetch.py`，不需要 MinerU。本地 4.x / 2.x–3.x 与官方云 v4 都支持，见 `references/09-mineru-setup.md`。
- Token 只从环境变量读取（`MINERU_API_TOKEN` / `MINERU_API_KEY`），不会写进仓库、报告或 manifest。

### 安装后怎么用

直接在对话里说：

```text
用 chem-integrity-auditor 审计 /path/to/paper.pdf
用 chem-integrity-auditor 审计 DOI 10.1039/d5ra01695a
用 chem-integrity-auditor 批量审计 papers/*.pdf，每篇一个 run 目录
```

Agent 会按 `SKILL.md` 的 8 步流水线执行，输出：

```text
output/chem-integrity-auditor/<slug>/<timestamp>/
├── audit_report.md          # 中文分级报告
├── input_manifest.md        # 采集与阻断记录
├── findings/{numerical,image,logical}/
├── workdir/                 # 各脚本 JSON 证据
├── panels/                  # 面板 PNG
└── supplementary/           # SI / 撤稿通知
```

### 更新与卸载

```bash
cd <skills>/chem-integrity-auditor && git pull
# 卸载：删除该目录，或在客户端 Skills 设置中移除
```

---

## 二、能查什么

- **数值轨**：收率取整、转化率×选择性、CHN 元素分析与分子式、HRMS 精确质量/加合物、Scherrer 晶粒尺寸、重复值、面积归一、不可实现单位/量程、表格重复行。
- **结构身份轨**：化合物 name/SMILES/CAS/InChIKey/分子式 → PubChem，比较分子式、MW、单同位素质量、CHN Calcd/Found、CAS、新颖性；支持盐/水合物与离线缓存。
- **图像轨**：面板切分（白沟 + 框架线 + 内容带）、dHash/aHash、ORB（旋转/镜像/裁剪 + RANSAC inlier/bbox）、谱图曲线与背景噪声指纹、stacked trace 切分与颜色隔离、**单条曲线内部片段复用**（patch NCC）。
- **参考谱轨**：把论文谱图峰位（两点轴校准）或峰表与 SDBS/NMRShiftDB 导出的峰表比对；不抓取数据库，只做半自动匹配。
- **逻辑轨**：合成→纯度→结构→性能的 claim chain、缺失对照、表征与结论不匹配、领域合理性。

## 三、关键脚本

| 脚本 | 作用 |
|---|---|
| `mineru_convert.py` | PDF → `full.md`；local v1 / local legacy / cloud v4 |
| `pmc_fetch.py` | PMC 全文 XML + 原始 figure 文件 → `full.md` |
| `build_evidence_ledger.py` | 文本/HTML 表/图/caption 的 cell 级 provenance 索引 |
| `chem_numeric.py` | 化学数值异常线索 |
| `nmr_hrms_numeric.py` | NMR 积分/13C 峰数/HRMS 同位素与 RDBE 线索 |
| `structure_check.py` | PubChem 结构身份核验（离线缓存） |
| `panel_split.py` | 多线索面板切分（白沟 / 框架线 / 内容带） |
| `stack_split.py` | 按全宽分隔线切 stacked traces |
| `image_dup.py` / `image_dup_orb.py` | 感知哈希 / ORB 变换复用（RANSAC inlier、inlier ratio、bbox、JSON） |
| `spectral_noise_fingerprint.py` | 曲线 + 背景噪声指纹 |
| `spectral_segment_dup.py` | 单条/两条曲线内部片段复用（patch NCC） |
| `reference_spectrum_match.py` | 峰表/谱图 vs SDBS/NMRShiftDB 峰表 |
| `calibrate_image_thresholds.py` | 标注对 → ROC/AUC/Youden 阈值标定 |
| `check_env.py` | 环境自检 |

## 四、测试

```bash
python3 tests/make_fixtures.py
bash tests/smoketest.sh
```

当前基线：**全部通过，0 失败**（fresh clone 首次运行会多一项 fixture 生成检查）。覆盖所有脚本编译/`--help`、数值正负对照、PubChem 离线缓存、参考谱匹配、图像复用、谱图指纹、面板/stack 切分、片段复用、阈值标定、MinerU 三后端 mock 与 auto fallback。

## 五、非协商项

- 发现是证据，不是判决：不写“造假/fraud”，写 Level 1–4 异常与“需原始数据裁定”。
- 每条发现必须有可解析的定位（markdown 行/页、表 id+行列+原值、图 id+panel、图像路径、技术）。
- 确定性脚本先跑，agent 只负责解释、做良性解释压力测试与分级。
- dHash/ORB/数据库命中本身不是造假；必须结合论文自身 claim 与第二条独立证据。
- 不抓取 SDBS；参考峰表由人工导出。
- 不修改被审计论文或其它 skill 的输出。
- Token/API secret 只从环境变量读取。

## 六、第三方依赖、参考项目与致谢

本项目建立在大量开源软件与公开科学数据之上。完整清单、许可证与引用见 **[ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)**。核心包括：

| 项目 / 数据 | 用途 | 许可证 / 条款 |
|---|---|---|
| [Pillow](https://python-pillow.org/) | 图像读写与绘制 | HPND |
| [NumPy](https://numpy.org/) | 数值计算 | BSD-3-Clause |
| [OpenCV](https://opencv.org/) | ORB、模板匹配、RANSAC | Apache-2.0 |
| [SciPy](https://scipy.org/) | 可选统计/信号辅助 | BSD-3-Clause |
| [RDKit](https://www.rdkit.org/) | 可选结构/分子式校验 | BSD-3-Clause |
| [Poppler](https://poppler.freedesktop.org/) | `pdftoppm` / `pdfimages` / `pdftotext` | GPL-2.0（独立可执行程序） |
| [MinerU](https://github.com/opendatalab/MinerU) | 可选 PDF → Markdown | AGPL-3.0（以仓库为准） |
| [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/) | 化合物身份核验 | NCBI 数据使用条款 |
| [SDBS](https://sdbs.db.aist.go.jp/) / [NMRShiftDB](https://nmrshiftdb.nmr.uni-koeln.de/) | 参考谱峰表 | 各自数据库条款；仅人工导出，不抓取 |
| [Europe PMC](https://europepmc.org/) / PMC | 全文与 figure 获取 | NLM 条款 |

算法与思想参考：dHash/aHash 感知哈希（`imagehash` 社区的公开方法）、ORB（Rublee et al., 2011）、Lowe ratio test（Lowe, 2004）、RANSAC（Fischler & Bolles, 1981）、Benjamini–Hochberg FDR（1995）、Fisher z、Scherrer 方程。感谢这些作者与维护者。

## 七、License

本项目采用 **MIT License**，见 [LICENSE](LICENSE)。第三方依赖、数据库与可选服务仍受各自许可证/条款约束；使用 MinerU、Poppler、SDBS、NMRShiftDB、PubChem 前请阅读其上游条款。

---

## 仓库结构

```text
SKILL.md                 # skill 合同与 8 步流水线
references/00-09         # 增量执行、采集、技术目录、数值/图像/逻辑/分级、结构、参考谱、MinerU
scripts/                 # 确定性脚本（无 LLM SDK）
templates/               # 中文 audit_report 模板
tests/                   # 生成式 fixtures + smoke + MinerU mock + gold set
.github/workflows/       # CI smoke
ACKNOWLEDGEMENTS.md      # 第三方依赖、数据源、算法引用与许可证
```

## 状态

已完成：多线索面板切分、PMC HTML 表进台账、单条曲线片段复用、阈值标定 harness、环境自检与 CI；NMR/13C/HRMS 同位素检查；真实 MinerU cloud v4 验证；5 篇真实撤稿论文 gold set（13 条撤稿指控，逐条给出 reproduced / partial / not reproduced / untestable 与分级）。当前缺口：跨论文图库（用于“首次发表于 ref. 1”类指控）、无分隔线的 offset-stacked 谱图切分、可执行报告质量门。
