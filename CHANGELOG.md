# Changelog

## v0.5.0 - Product Readiness and Evaluation Layer

- Added model effectiveness evaluation with Rank IC, Top hit-rate uplift, and ML-vs-base return uplift.
- Added data quality diagnostics for NAV completeness, missing days, long gaps, abnormal jumps, quality scores, and recommendations.
- Added strategy benchmark aggregation across static benchmarks, Walk-Forward, adaptive validation, and portfolio rebalance backtests.
- Added saved analysis presets for custom factor weights and portfolio objectives/constraints in SQLite and the FastAPI web UI.
- Added on-page previews and download links for model evaluation, data quality diagnostics, and strategy benchmark reports.
- Included the new reports in Word, PDF, and Excel export bundles and refreshed product-facing README messaging.

## v0.4.0 - Constrained Portfolio Optimization

- Added configurable portfolio constraints for objective, fund count, single-fund weight cap, drawdown floor, Sharpe floor, rebalance interval, turnover cap, and transaction cost assumptions.
- Added portfolio recommendation explanations, fund-type concentration controls, and pairwise correlation controls.
- Added constrained optimized portfolio construction with objective-aware weights and turnover-aware rebalancing.
- Added portfolio constraint CSV, recommendation CSV/report, risk-control CSV, optimized portfolio weight chart, and constrained rebalance backtest outputs.
- Exposed portfolio constraints in the FastAPI web form, analysis history, downloads, and Office/Excel export bundle.
- Updated CLI options so constrained portfolio analysis can run outside the web dashboard.

## v0.3.0 - ML-Assisted Scoring

- Added walk-forward training sample generation for machine-learning assisted factor learning.
- Added non-negative ridge-based factor weight learning with profile-weight blending and safe fallbacks.
- Added ML ranking, learned weight CSV, training sample CSV, and ML model report outputs.
- Added original-vs-ML ranking comparison outputs and on-page ML result tables.
- Added Word, PDF, and Excel export bundles for easier user-facing downloads.
- Exposed ML-assisted scoring downloads in the FastAPI web dashboard.

## v0.2.1 - Download Link Compatibility

- Fixed historical run pages so download buttons only appear when the underlying report files exist.
- Added compatibility for older `p3_research_enhancement.md` report files.

## v0.2.0 - LIME Local Explainability

- Added a LIME-style local explanation module for fund-level score sensitivity.
- Added `lime_explanations.csv` and `lime_explanations.md` to pipeline outputs.
- Exposed LIME explanation downloads in the FastAPI web dashboard.
- Added version-aware CI/CD checks, package build artifacts, and tag-based GitHub releases.

## v0.1.0 - Initial Risk-Return Ranking System

- Built the core mutual fund risk-return ranking pipeline.
- Added AkShare data fetching, SQLite caching, FastAPI dashboard, reports, charts, and validation outputs.
