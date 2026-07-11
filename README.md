# Fund Ranking System

A local-deployable mutual fund risk-return analysis system with FastAPI, AkShare, SQLite cache, multi-factor scoring, charts, and report generation.

[中文说明](README.zh-CN.md) · [Local Deployment](docs/local_deployment.md) · [Demo Guide](docs/demo_guide.md) · [Project Report](docs/project_report.md)

> This project is for historical performance analysis and research assistance only. It is not personalized investment advice, a return guarantee, or a buy/sell signal.

## Preview

![Demo](docs/assets/demo.gif)

![Web UI](docs/assets/web-ui.png)

![Ranking Results](docs/assets/web-results.png)

## Why This Project

Mutual fund screening is often reduced to historical return ranking. This project extends that workflow into a reproducible risk-return analysis pipeline:

```text
Fund NAV data
  -> data cleaning
  -> return calculation
  -> risk-return metrics
  -> multi-factor scoring
  -> ranking, charts, reports
```

It is designed as a small but complete financial data application rather than a single notebook.

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
| Natural-language explanations | Explains ranking results in readable Chinese text |
| Web dashboard | Search funds, analyze fund pools, view charts, and download reports |
| SQLite cache | Stores fund metadata, NAV history, custom fund pools, and analysis runs |
| Independent result pages | Keeps each analysis run in a separate report directory |
| Fund universe filter | Applies comparable-universe rules and A/C share-class deduplication |
| Factor diagnostics | Reports Spearman factor correlations to flag information overlap |
| Exact score explanation | Decomposes each weighted score into factor contributions |
| Walk-forward validation | Tests whether high-ranked funds show out-of-sample differentiation |
| Weight robustness | Uses Monte Carlo weight perturbation to measure ranking stability |

## Quick Start

### Option 1: Local Python

```bash
git clone https://github.com/ZZJ1977/fund-ranking-system.git
cd fund-ranking-system
bash scripts/run_web.sh
```

Open:

```text
http://127.0.0.1:8000
```

Try these fund codes:

```text
000001 000011 000083
```

### Option 2: Docker

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

- `data/raw/demo_fund_nav.csv`
- `data/raw/fund_metadata.csv`
- `data/processed/fund_metrics.csv`
- `data/processed/ranking_all_profiles.csv`
- `reports/ranking_<profile>.csv`
- `reports/weight_sensitivity.csv`
- `reports/weight_sensitivity.md`
- `reports/fund_universe.md`
- `reports/factor_diagnostics.md`
- `reports/factor_contributions.md`
- `reports/weight_robustness.md`
- `reports/backtest_summary.md`
- `reports/walk_forward_results.csv`
- `reports/fund_analysis_report.md`
- `reports/*.png`

Ranking tables include:

- `fund_type`: inferred broad fund type, such as equity, hybrid, bond, index, money market, or QDII
- `type_rank`: rank within the same inferred fund type
- `data_quality`: data coverage and calculation quality warning
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

## Test

```bash
python -m pytest -q
```

## Safety Notes

- The default web server binds to `127.0.0.1` for local use.
- The app does not upload local files.
- The app only fetches public fund data through external data interfaces.
- Do not expose the default local setup directly to the public internet without authentication, rate limiting, logging, HTTPS, and compliance review.

## License

This project is licensed under the [MIT License](LICENSE).
