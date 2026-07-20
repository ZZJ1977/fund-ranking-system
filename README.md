# Fund Ranking System

![CI](https://github.com/ZZJ1977/fund-ranking-system/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Version](https://img.shields.io/badge/Version-v0.5.0-176b87)
![FastAPI](https://img.shields.io/badge/FastAPI-Web%20Dashboard-009688)
![AkShare](https://img.shields.io/badge/Data-AkShare-orange)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)
![License](https://img.shields.io/badge/License-MIT-green)

A local-first mutual fund risk-return research workstation for China's public fund market. It fetches real NAV data through AkShare, caches it in SQLite, ranks funds with transparent multi-factor and ML-assisted models, checks data quality and model effectiveness, compares strategies against benchmarks, and exports Word/PDF/Excel reports.

[中文说明](README.zh-CN.md) · [Changelog](CHANGELOG.md) · [Local Deployment](docs/local_deployment.md) · [Sample Outputs](docs/sample_outputs/README.md) · [Demo Guide](docs/demo_guide.md) · [Project Report](docs/project_report.md) · [100-Fund Validation](docs/real_world_validation.md) · [Contributing](CONTRIBUTING.md)

> This project is for historical performance analysis and research assistance only. It is not personalized investment advice, a return guarantee, or a buy/sell signal.

## What You Get

- A usable FastAPI web dashboard, not just a notebook.
- Real public fund NAV fetching with local SQLite caching.
- Multi-factor scoring across return, volatility, drawdown, Sharpe, Calmar, and rolling stability.
- Three investor profiles: `aggressive`, `balanced`, and `conservative`.
- Explainable rankings with risk labels, data-quality warnings, and natural-language reasons.
- Walk-forward validation, ML-assisted scoring, model effectiveness evaluation, data quality diagnostics, dynamic fund-level weights, portfolio construction, portfolio recommendation explanations, concentration/correlation controls, portfolio rebalance benchmarking, LIME-style local explanations, saved analysis presets, Office/PDF exports, and weight robustness checks.
- Docker and Windows/macOS/Linux local deployment instructions.

## Preview

![Demo](docs/assets/demo.gif)

![Web UI](docs/assets/web-ui.png)

![Ranking Results](docs/assets/web-results.png)

![Chart Viewer](docs/assets/chart-viewer.png)

## Why This Project

Mutual fund screening is often reduced to historical return ranking. This project extends that workflow into a reproducible risk-return analysis pipeline:

```text
Fund NAV data
  -> data cleaning
  -> return calculation
  -> risk-return metrics
  -> multi-factor scoring
  -> ranking, chart viewer, Office/PDF reports
```

It is designed as a small but complete financial data application rather than a single notebook.

## Product Workflow

```text
Choose fund codes or a saved pool
  -> run data quality and model checks
  -> compare base, adaptive, ML, and portfolio results
  -> inspect one large chart at a time
  -> export Word, PDF, and Excel outputs
```

The main form keeps advanced scoring weights and portfolio constraints collapsed by default, so new users can run an analysis quickly while experienced users can still tune the model and save presets.

## Features

| Feature | Description |
|---|---|
| Real fund data | Fetches open-end fund NAV data and fund names through AkShare |
| Multi-factor scoring | Combines return, volatility, drawdown, Sharpe, Calmar, and stability |
| Investor profiles | Supports `aggressive`, `balanced`, and `conservative` weighting schemes |
| Sensitivity analysis | Compares ranking changes under different risk preferences |
| Risk labels | Generates risk levels, observation labels, and explanatory reasons |
| Fund type grouping | Infers broad fund types and adds within-type ranking |
| Data quality checks | Flags short sample windows, missing rolling windows, and abnormal volatility |
| Data quality diagnostics | Scores NAV completeness, missing days, long gaps, abnormal jumps, and gives remediation suggestions |
| Natural-language explanations | Explains ranking results in readable Chinese text |
| Web dashboard | Search funds, analyze fund pools, view charts, and download reports |
| Fund detail pages | Drill into one fund's metrics, ranks, dynamic weights, LIME, and factor contributions |
| SQLite cache | Stores fund metadata, NAV history, custom fund pools, and analysis runs |
| Saved analysis presets | Saves custom factor weights and portfolio targets/constraints for reuse |
| Independent result pages | Keeps each analysis run in a separate report directory |
| Fund universe filter | Applies comparable-universe rules and A/C share-class deduplication |
| Fund quality governance | Scores history length, NAV completeness, abnormal jumps, and suspected duplicated strategies |
| Factor diagnostics | Reports Spearman factor correlations to flag information overlap |
| Exact score explanation | Decomposes each weighted score into factor contributions |
| LIME local explanation | Uses local perturbations and a weighted linear surrogate to explain score sensitivity around one fund |
| ML-assisted scoring | Learns factor weights from walk-forward samples and produces an ML comparison ranking |
| Model effectiveness evaluation | Compares ML vs base weights with Rank IC, Top hit-rate uplift, and future-return uplift |
| Benchmarks and peers | Compares Top-N portfolios against the fund-pool benchmark, optional external benchmark, and peer percentiles |
| Strategy benchmark layer | Aggregates static benchmark, Walk-Forward, adaptive validation, and rebalance backtest results |
| Portfolio construction | Builds base Top-N, adaptive Top-N, ML Top-N, risk-parity, drawdown-constrained, and user-constrained portfolios |
| Portfolio recommendation explanations | Explains why each fund is selected, why it receives its weight, and what risk/diversification notes apply |
| Portfolio constraints | Lets users configure objective, holding count, single-fund cap, fund-type cap, correlation threshold, drawdown floor, Sharpe floor, turnover cap, and transaction cost assumptions |
| Concentration and correlation controls | Tracks inferred fund-type exposure and high-correlation fund pairs in dedicated risk-control outputs |
| Portfolio rebalance backtest | Re-ranks funds on rolling windows and compares fixed, adaptive, constrained, risk-parity, and all-fund portfolios |
| Explanation visuals | Exports dynamic-weight, LIME local-weight, and rank-change charts |
| Adaptive validation | Tests fund-level dynamic weights with walk-forward out-of-sample validation |
| User-friendly exports | Exports a Word report bundle, PDF report bundle, and Excel data workbook |
| Walk-forward validation | Tests whether high-ranked funds show out-of-sample differentiation |
| Weight robustness | Uses Monte Carlo weight perturbation to measure ranking stability |

## Quick Start

### Option 1: macOS / Linux

```bash
git clone https://github.com/ZZJ1977/fund-ranking-system.git
cd fund-ranking-system
bash scripts/run_web.sh
```

For a detached local service with a PID file and log:

```bash
bash scripts/start_web.sh
tail -f tmp/fund-ranking-web.log
bash scripts/stop_web.sh
```

Open:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/health
```

Try these fund codes:

```text
000001 000011 000083 110022 005827
```

### Option 2: Windows PowerShell

```powershell
git clone https://github.com/ZZJ1977/fund-ranking-system.git
cd fund-ranking-system
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\fund-ranking-web.exe --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

### Option 3: Docker

```bash
git clone https://github.com/ZZJ1977/fund-ranking-system.git
cd fund-ranking-system
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000
```

The Docker container keeps generated data under mounted local folders:

```text
data/
reports/
```

`docker compose ps` shows the container health status after startup.

## Real Fund Sample

You can start with a diversified 30-fund sample covering active equity, hybrid, consumption, healthcare, technology, index-linked, LOF, and QDII funds:

```text
110022 005827 001938 003096 161725 270042 001052 519674 001714 000988
002001 000991 519732 260108 163406 160222 162605 000248 001475 001410
004851 005669 006327 007119 008086 009341 010347 011011 012414 013356
```

Fetch real NAV data and generate project-ready CSV files:

```bash
python scripts/fetch_akshare_funds.py \
  --codes 110022 005827 001938 003096 161725 270042 001052 519674 001714 000988 002001 000991 519732 260108 163406 160222 162605 000248 001475 001410 004851 005669 006327 007119 008086 009341 010347 011011 012414 013356 \
  --start-date 2021-01-01 \
  --output data/raw/real_fund_nav.csv \
  --metadata-output data/raw/fund_metadata.csv
```

Then run the ranking pipeline:

```bash
fund-ranking \
  --input data/raw/real_fund_nav.csv \
  --metadata data/raw/fund_metadata.csv \
  --profile balanced
```

## Command Line Demo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest
fund-ranking --demo --profile balanced
```

Analyze your own wide-format NAV CSV:

```bash
fund-ranking --input data/raw/your_fund_nav.csv --profile balanced
```

Optionally include an external benchmark NAV CSV, such as an index series:

```bash
fund-ranking --input data/raw/your_fund_nav.csv --benchmark data/raw/benchmark_nav.csv --profile balanced
```

Run constrained portfolio optimization from the CLI:

```bash
fund-ranking --input data/raw/your_fund_nav.csv --profile balanced \
  --portfolio-objective defensive \
  --portfolio-min-funds 4 \
  --portfolio-max-funds 8 \
  --max-position-weight 0.25 \
  --max-type-weight 0.55 \
  --max-pair-correlation 0.85 \
  --portfolio-max-drawdown -0.35 \
  --portfolio-min-sharpe 0.1 \
  --rebalance-days 63 \
  --max-turnover 0.4 \
  --transaction-cost-bps 8
```

Expected CSV format:

```csv
Date,Fund_A,Fund_B,Fund_C
2023-01-03,1.0000,1.0000,1.0000
2023-01-04,1.0021,0.9987,1.0032
2023-01-05,1.0045,1.0018,1.0011
```

## Metrics

| Metric | Meaning |
|---|---|
| Annual Return | Long-term return capability |
| Annual Volatility | Return fluctuation risk |
| Maximum Drawdown | Largest historical peak-to-trough loss |
| Sharpe Ratio | Excess return per unit of volatility |
| Calmar Ratio | Annual return relative to maximum drawdown |
| Rolling Positive Ratio | Share of positive 60-day rolling return windows |

## Scoring Model

```text
Fund Score =
w1 * Annual Return
+ w2 * Sharpe Ratio
+ w3 * Maximum Drawdown
+ w4 * Calmar Ratio
+ w5 * Annual Volatility
+ w6 * Rolling Positive Ratio
```

Built-in investor profiles:

| Profile | Preference |
|---|---|
| `aggressive` | Emphasizes return and return persistence |
| `balanced` | Balances return, drawdown, risk-adjusted return, and stability |
| `conservative` | Emphasizes drawdown control, volatility control, and holding experience |

## Project Structure

```text
fund-ranking-system
├── data
├── docs
├── reports
├── scripts
├── src/fund_ranking_system
├── tests
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Generated Outputs

- Curated demo bundle: [docs/sample_outputs](docs/sample_outputs/README.md)
- Word report sample: [analysis_reports.docx](docs/sample_outputs/analysis_reports.docx)
- PDF report sample: [analysis_reports.pdf](docs/sample_outputs/analysis_reports.pdf)
- Excel workbook sample: [analysis_data.xlsx](docs/sample_outputs/analysis_data.xlsx)
- `data/raw/demo_fund_nav.csv`
- `data/raw/fund_metadata.csv`
- `data/processed/fund_metrics.csv`
- `data/processed/ranking_all_profiles.csv`
- `reports/ranking_<profile>.csv`
- `reports/weight_sensitivity.csv`
- `reports/weight_sensitivity.md`
- `reports/fund_universe.md`
- `reports/data_quality_diagnostics.md`
- `reports/data_quality_diagnostics.csv`
- `reports/factor_diagnostics.md`
- `reports/factor_contributions.md`
- `reports/lime_explanations.md`
- `reports/lime_explanations.csv`
- `reports/adaptive_weight_report.md`
- `reports/adaptive_factor_weights.csv`
- `reports/ranking_adaptive_<profile>.csv`
- `reports/benchmark_comparison.md`
- `reports/benchmark_comparison.csv`
- `reports/peer_comparison_<profile>.csv`
- `reports/portfolio_construction.md`
- `reports/portfolio_summary.csv`
- `reports/portfolio_weights_<profile>.csv`
- `reports/portfolio_constraints.csv`
- `reports/portfolio_recommendation.md`
- `reports/portfolio_recommendations.csv`
- `reports/portfolio_risk_controls.csv`
- `reports/portfolio_optimized_weights.png`
- `reports/portfolio_rebalance_report.md`
- `reports/portfolio_rebalance_results.csv`
- `reports/portfolio_rebalance_periods.csv`
- `reports/portfolio_rebalance_cumulative_return.png`
- `reports/adaptive_backtest_summary.md`
- `reports/adaptive_walk_forward_results.csv`
- `reports/dynamic_weight_top_factors.png`
- `reports/lime_local_weight_bars.png`
- `reports/rank_comparison_changes.png`
- `reports/ml_model_report.md`
- `reports/ml_evaluation.md`
- `reports/ml_evaluation.csv`
- `reports/ml_learned_weights.csv`
- `reports/ranking_ml_<profile>.csv`
- `reports/ml_training_samples.csv`
- `reports/ranking_comparison_<profile>.csv`
- `reports/ranking_comparison.md`
- `reports/weight_robustness.md`
- `reports/strategy_benchmark.md`
- `reports/strategy_benchmark.csv`
- `reports/backtest_summary.md`
- `reports/walk_forward_results.csv`
- `reports/fund_analysis_report.md`
- `reports/analysis_reports.docx`
- `reports/analysis_reports.pdf`
- `reports/analysis_data.xlsx`
- `reports/*.png`

Ranking tables include:

- `fund_type`: inferred broad fund type, such as equity, hybrid, bond, index, money market, or QDII
- `type_rank`: rank within the same inferred fund type
- `data_quality`: data coverage and calculation quality warning
- `quality_score`: fund-pool quality score based on history, completeness, and abnormal NAV jumps
- `result_explanation`: natural-language explanation of each result

## Model Validation

The project includes a walk-forward validation module:

```text
lookback window
  -> calculate metrics and score funds
  -> select Top 10 / Top 20%
  -> observe the next holding window
  -> compare with all-fund equal-weight portfolio
```

This does not claim that the model predicts future returns. It checks whether historical risk-return scores have out-of-sample differentiation ability.

### 100-Fund Real Sample Result

A real-data experiment with 100 stock/hybrid mutual fund candidates was run with the `balanced` profile. After universe filtering, 55 funds were eligible for analysis.

| Portfolio | Annual Return | Sharpe | Volatility | Max Drawdown | Win Rate |
|---|---:|---:|---:|---:|---:|
| Top 10 | -2.29% | -0.11 | 21.59% | -33.51% | 47.2% |
| Top 20% | -3.26% | -0.15 | 21.35% | -35.33% | 47.6% |
| All Funds | -5.51% | -0.25 | 21.94% | -39.77% | 45.4% |

In this sample, the top-ranked portfolios still had negative returns, but they showed better return, Sharpe, drawdown, and win-rate characteristics than the all-fund equal-weight portfolio. See [100-Fund Validation](docs/real_world_validation.md).

## Who This Is For

- Students building a finance, data analysis, or fintech portfolio project.
- Python learners who want a complete data pipeline instead of a single script.
- Quant research beginners exploring fund ranking, risk metrics, and model validation.
- Interview reviewers who want to see reproducible data fetching, analysis, storage, web UI, and reporting in one small project.

## Roadmap

- Add scheduled background updates for selected fund pools.
- Add richer fund metadata, such as manager tenure, fee level, fee structure, and fund size.
- Add documentation link checks and Docker health checks in CI.

## Test

```bash
python -m pytest -q
```

## Safety Notes

- The default web server binds to `127.0.0.1` for local use.
- The app does not upload local files.
- The app only fetches public fund data through external data interfaces.
- Do not expose the default local setup directly to the public internet without authentication, rate limiting, logging, HTTPS, and compliance review.
- Generated rankings are research labels, not financial advice.

## License

This project is licensed under the [MIT License](LICENSE).
