from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def load_nav_csv(path: str | Path, date_col: str = "Date") -> pd.DataFrame:
    """Load fund NAV data from a wide CSV file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"NAV file not found: {path}")

    frame = pd.read_csv(path)
    if date_col not in frame.columns:
        raise ValueError(f"CSV must contain a '{date_col}' column.")

    frame[date_col] = pd.to_datetime(frame[date_col])
    frame = frame.sort_values(date_col).set_index(date_col)
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(axis=1, how="all").ffill().dropna(how="all")

    if frame.empty:
        raise ValueError("No valid NAV data found after cleaning.")

    return frame


def common_nav_start(nav: pd.DataFrame) -> pd.Timestamp | None:
    """Return the first date where every fund has an available NAV value."""
    first_dates = []
    for fund in nav.columns:
        first_date = nav[fund].first_valid_index()
        if first_date is not None:
            first_dates.append(pd.Timestamp(first_date))
    if not first_dates:
        return None
    return max(first_dates)


def align_nav_to_common_start(nav: pd.DataFrame) -> pd.DataFrame:
    """Trim NAV data to the comparable window shared by all available funds."""
    start = common_nav_start(nav)
    if start is None:
        return nav.copy()
    aligned = nav.loc[nav.index >= start].copy()
    return aligned.ffill().dropna(how="all")


def generate_demo_nav(
    fund_count: int = 36,
    periods: int = 756,
    start: str = "2023-01-03",
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic demo NAV series for a self-contained first run."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=periods)
    market = rng.normal(0.00025, 0.008, periods)

    styles = [
        ("Growth", 0.15, 0.28, 1.15),
        ("Balanced", 0.10, 0.18, 0.85),
        ("Defensive", 0.06, 0.10, 0.45),
        ("Cyclical", 0.12, 0.34, 1.35),
        ("Stable", 0.08, 0.12, 0.55),
        ("Volatile", 0.18, 0.42, 1.55),
    ]

    nav_data: dict[str, np.ndarray] = {}
    for i in range(fund_count):
        style, annual_drift, annual_vol, beta = styles[i % len(styles)]
        daily_alpha = annual_drift / TRADING_DAYS_PER_YEAR
        daily_vol = annual_vol / np.sqrt(TRADING_DAYS_PER_YEAR)
        idiosyncratic = rng.normal(0, daily_vol, periods)

        returns = daily_alpha + beta * market + idiosyncratic

        if style in {"Cyclical", "Volatile"}:
            shock_days = rng.choice(periods, size=max(2, periods // 160), replace=False)
            returns[shock_days] += rng.normal(-0.045, 0.025, len(shock_days))

        if style == "Stable":
            returns = 0.75 * returns + 0.25 * rng.normal(0.0002, 0.004, periods)

        returns = np.clip(returns, -0.18, 0.16)
        nav = np.cumprod(1 + returns)
        nav_data[f"Fund_{i + 1:03d}_{style}"] = nav

    return pd.DataFrame(nav_data, index=dates).round(6)


def save_nav_csv(nav: pd.DataFrame, path: str | Path) -> Path:
    """Save NAV data with a Date column."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nav.to_csv(path, index_label="Date")
    return path
