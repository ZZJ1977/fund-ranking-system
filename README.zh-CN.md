# 公募基金风险收益评价与量化筛选系统

[English README](README.md)

本项目是一个基于 Python 的公募基金历史表现分析与决策辅助系统。项目目标不是简单按历史收益率排序，而是搭建一套可复现的基金风险收益评价流程，回答一个更贴近数据分析的问题：

> 如果基金筛选不能只看收益率，如何从收益、风险、风险调整收益和稳定性多个维度评价基金？

## 合规声明

本项目是基金历史表现分析与决策辅助系统，不构成个性化投资建议、收益承诺或买卖指令。系统输出的排名、风险等级和观察标签仅用于研究比较。实际投资需要结合投资者风险承受能力、投资期限、流动性需求、费用、基金合同和市场环境等因素。

## 功能概览

| 功能 | 说明 |
|---|---|
| 真实数据接入 | 通过 AkShare 抓取开放式基金单位净值和基金名称 |
| 多因子评分 | 计算收益、风险、风险调整收益和稳定性指标 |
| 投资者画像 | 支持 aggressive、balanced、conservative 三类权重 |
| 敏感性分析 | 比较不同风险偏好下的基金排名变化 |
| 决策辅助标签 | 输出风险等级、观察标签和原因说明 |
| 基金类型分类 | 根据基金名称推断股票型、混合型、债券型、指数型等大类 |
| 数据质量提示 | 标记样本期较短、滚动窗口不足、波动率异常等问题 |
| 结果解释 | 为每只基金生成自然语言解释，说明收益、风险和数据质量特点 |
| Web 分析台 | 输入代码即可分析，支持搜索、基金池、下载 |
| SQLite 缓存 | 保存净值、基金名称、基金池和分析历史 |
| 独立结果页 | 每次分析保留独立报告，不被新结果覆盖 |
| 研究报告 | 生成轻量文本因子和可解释模型说明 |

## 页面预览

![Web UI](docs/assets/web-ui.png)

![Ranking Results](docs/assets/web-results.png)

## 系统架构

```text
基金代码 / 基金池
      ↓
AkShare 数据抓取
      ↓
SQLite 本地缓存
      ↓
净值清洗与指标计算
      ↓
多因子评分和画像排名
      ↓
风险等级、敏感性分析、研究报告
      ↓
Web 页面、CSV、Markdown 报告、图表
```

## 文档索引

- [本地部署说明](docs/local_deployment.md)
- [Web 演示说明](docs/demo_guide.md)
- [正式项目报告](docs/project_report.md)

## 分析流程

系统会执行完整的数据分析闭环：

```text
基金净值数据
  -> 数据清洗
  -> 收益率计算
  -> 风险收益指标计算
  -> 基金排名
  -> 可视化图表
```

多因子评分模型：

```text
Fund Score =
w1 * Annual Return
+ w2 * Sharpe Ratio
+ w3 * Maximum Drawdown
+ w4 * Calmar Ratio
+ w5 * Volatility
+ w6 * Rolling Positive Ratio
```

三类投资者画像：

| 画像 | 设计思路 |
|---|---|
| aggressive | 更看重收益和收益持续性，接受更高波动 |
| balanced | 平衡收益、回撤、风险调整收益和稳定性 |
| conservative | 更看重最大回撤、波动控制和持有体验 |

## 项目结构

```text
Fund-Ranking-System
├── data
│   ├── raw
│   └── processed
├── docs
│   ├── demo_guide.md
│   ├── local_deployment.md
│   └── project_report.md
├── reports
├── src
│   └── fund_ranking_system
│       ├── cli.py
│       ├── akshare_data.py
│       ├── advisory.py
│       ├── data.py
│       ├── metrics.py
│       ├── pipeline.py
│       ├── report.py
│       ├── research.py
│       ├── scoring.py
│       ├── sensitivity.py
│       ├── storage.py
│       ├── web.py
│       └── visualization.py
├── tests
├── scripts
│   ├── run_web.sh
│   ├── fetch_akshare_funds.py
│   └── update_fund_data.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 快速运行

### GitHub 本地部署

克隆项目后，可以直接运行：

```bash
git clone <your-repo-url>
cd fund-ranking-system
bash scripts/run_web.sh
```

然后打开：

```text
http://127.0.0.1:8000
```

详细说明见：[本地部署说明](docs/local_deployment.md)。

### Docker 启动

如果本机已经安装 Docker，也可以直接运行：

```bash
git clone https://github.com/ZZJ1977/fund-ranking-system.git
cd fund-ranking-system
docker compose up --build
```

然后打开：

```text
http://127.0.0.1:8000
```

### 命令行 demo

```bash
cd ~/fund-ranking-system
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest
fund-ranking --demo --profile balanced
```

如果已经安装过依赖，可以直接运行：

```bash
.venv/bin/fund-ranking --demo --profile balanced
```

## 启动 Web 分析页面

本项目提供本地 Web 版，适合实际演示和日常查询。启动后可以在页面输入基金代码、起始日期和投资者画像，系统会自动抓取真实净值数据并生成排名、图表和报告。

```bash
cd ~/fund-ranking-system
.venv/bin/fund-ranking-web --host 127.0.0.1 --port 8000
```

打开：

```bash
open http://127.0.0.1:8000
```

页面仍然只提供历史表现分析和研究辅助，不构成个性化投资建议。

Web 页面支持：

- 分析时显示加载状态
- 页面内错误提示，不会直接白屏
- 按基金名称或代码搜索基金
- 使用默认基金池进行快速分析
- 下载 Markdown 报告、CSV 排名和指标明细
- 使用 SQLite 缓存历史净值，重复分析同一基金时优先读取本地数据
- 记录最近分析历史，方便回看分析过的基金组合
- 点击历史记录可打开独立结果页，也可以复用历史参数重新分析
- 支持自定义基金池保存和删除
- 显示本地缓存的最早日期、最新日期和数据条数
- 每次分析生成独立报告目录，历史报告不会被新结果覆盖
- 自动生成研究报告，包含轻量文本因子和可解释模型说明

## 本地数据库与自动更新

Web 版会自动维护一个本地 SQLite 数据库：

```text
data/fund_ranking.db
```

数据库保存：

- 基金代码和名称
- 历史单位净值
- 最近分析记录

如果某只基金已经缓存过，页面会显示类似：

```text
缓存命中 3 只，远程补抓 0 只。
```

也可以手动更新数据库中已有基金：

```bash
cd ~/fund-ranking-system
.venv/bin/python scripts/update_fund_data.py --start-date 2021-01-01
```

指定基金更新：

```bash
.venv/bin/python scripts/update_fund_data.py --codes 000001 000011 000083 --start-date 2021-01-01
```

## 输出结果

运行后会生成：

- `data/raw/demo_fund_nav.csv`：模拟基金净值数据
- `data/raw/fund_metadata.csv`：基金代码、基金简称映射表
- `data/processed/fund_metrics.csv`：收益率、波动率、回撤、Sharpe、Calmar 等指标
- `data/processed/ranking_all_profiles.csv`：三类投资者画像的评分和排名
- `reports/ranking_aggressive.csv`：激进型投资者排名
- `reports/ranking_balanced.csv`：平衡型投资者排名
- `reports/ranking_conservative.csv`：稳健型投资者排名
- `reports/weight_sensitivity.csv`：权重敏感性分析结果
- `reports/weight_sensitivity.md`：权重敏感性分析摘要
- `reports/fund_analysis_report.md`：中文项目分析报告
- `reports/*.png`：风险收益散点图、净值走势、回撤曲线和 Top 排名图

排名表中还会输出：

- `risk_level`：较低风险、中等风险、中高风险、高风险
- `fund_type`：推断出的基金类型
- `type_rank`：同类基金内排名
- `data_quality`：数据质量提示
- `decision_label`：重点观察、可观察、高回撤预警、暂不优先
- `decision_reason`：系统给出该标签的历史指标原因
- `result_explanation`：自然语言解释

## 使用自己的数据

准备一个 CSV，第一列为日期，后面每一列是一只基金的单位净值或复权净值：

```csv
Date,Fund_A,Fund_B,Fund_C
2023-01-03,1.0000,1.0000,1.0000
2023-01-04,1.0021,0.9987,1.0032
2023-01-05,1.0045,1.0018,1.0011
```

运行：

```bash
.venv/bin/fund-ranking --input data/raw/your_fund_nav.csv --profile balanced
```

## 接入真实基金数据

项目提供了 AkShare 抓取脚本，可以从东方财富基金接口获取开放式基金单位净值走势，并整理成项目需要的宽表 CSV。

安装依赖：

```bash
.venv/bin/python -m pip install -e .
```

抓取默认 10 只基金的真实净值数据：

```bash
.venv/bin/python scripts/fetch_akshare_funds.py \
  --start-date 2021-01-01 \
  --output data/raw/real_fund_nav.csv \
  --metadata-output data/raw/fund_metadata.csv
```

使用真实数据运行评分系统：

```bash
.venv/bin/fund-ranking \
  --input data/raw/real_fund_nav.csv \
  --metadata data/raw/fund_metadata.csv \
  --profile balanced
```

也可以指定自己的基金代码：

```bash
.venv/bin/python scripts/fetch_akshare_funds.py \
  --codes 000001 000003 000011 000021 000031 \
  --start-date 2021-01-01 \
  --output data/raw/real_fund_nav.csv \
  --metadata-output data/raw/fund_metadata.csv
```

真实数据接口可能受网络、数据源限流或字段变更影响。如果某只基金抓取失败，脚本会跳过该基金并继续处理其他基金。

## 指标说明

| 指标 | 含义 |
|---|---|
| Annual Return | 年化收益率，衡量长期收益能力 |
| Volatility | 年化波动率，衡量收益波动程度 |
| Maximum Drawdown | 最大回撤，衡量历史最大亏损幅度 |
| Sharpe Ratio | 单位波动承担下获得的超额收益 |
| Calmar Ratio | 年化收益相对于最大回撤的表现 |
| Rolling Positive Ratio | 60 日滚动收益为正的比例，衡量稳定性 |

## 验证

```bash
.venv/bin/python -m pytest -q
```

## License

This project is licensed under the [MIT License](LICENSE).
