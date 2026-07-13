# Changelog

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
