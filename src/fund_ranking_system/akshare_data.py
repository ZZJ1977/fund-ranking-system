from __future__ import annotations

import time

import akshare as ak
import pandas as pd

from .metadata import infer_fund_type


def fetch_open_fund_list() -> pd.DataFrame:
    fund_list = ak.fund_open_fund_daily_em()
    required_columns = {"基金代码", "基金简称"}
    missing = required_columns - set(fund_list.columns)
    if missing:
        raise ValueError(f"AkShare fund list is missing columns: {missing}")

    normalized = fund_list.copy()
    normalized["基金代码"] = normalized["基金代码"].astype(str).str.zfill(6)
    return normalized


def fetch_fund_metadata(codes: list[str]) -> pd.DataFrame:
    fund_list = fetch_open_fund_list()
    normalized_codes = {code.zfill(6) for code in codes}
    metadata = fund_list[["基金代码", "基金简称"]].copy()
    metadata = metadata[metadata["基金代码"].isin(normalized_codes)]
    metadata = metadata.rename(columns={"基金代码": "fund_code", "基金简称": "fund_name"})
    metadata["fund_type"] = metadata["fund_name"].apply(infer_fund_type)
    return metadata.sort_values("fund_code")


def search_funds(keyword: str, limit: int = 20) -> pd.DataFrame:
    keyword = keyword.strip()
    if not keyword:
        return pd.DataFrame(columns=["fund_code", "fund_name", "fund_type"])

    fund_list = fetch_open_fund_list()
    mask = fund_list["基金代码"].str.contains(keyword, na=False) | fund_list["基金简称"].str.contains(
        keyword, na=False
    )
    result = fund_list.loc[mask, ["基金代码", "基金简称"]].head(limit).copy()
    result = result.rename(columns={"基金代码": "fund_code", "基金简称": "fund_name"})
    result["fund_type"] = result["fund_name"].apply(infer_fund_type)
    return result


def fetch_fund_nav(code: str, start_date: str) -> pd.Series:
    frame = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")

    required_columns = {"净值日期", "单位净值"}
    missing = required_columns - set(frame.columns)
    if missing:
        raise ValueError(f"AkShare response for {code} is missing columns: {missing}")

    frame["净值日期"] = pd.to_datetime(frame["净值日期"])
    frame["单位净值"] = pd.to_numeric(frame["单位净值"], errors="coerce")
    frame = frame.dropna(subset=["净值日期", "单位净值"])
    frame = frame[frame["净值日期"] >= pd.to_datetime(start_date)]
    frame = frame.sort_values("净值日期")

    if frame.empty:
        raise ValueError(f"No NAV rows for {code} after {start_date}.")

    series = frame.set_index("净值日期")["单位净值"]
    series.name = code
    return series


def fetch_many_funds(codes: list[str], start_date: str, sleep_seconds: float) -> pd.DataFrame:
    series_list: list[pd.Series] = []
    failures: list[tuple[str, str]] = []

    for code in codes:
        print(f"Fetching {code}...")
        try:
            series_list.append(fetch_fund_nav(code, start_date))
        except Exception as exc:
            failures.append((code, str(exc)))
            print(f"Failed {code}: {exc}")

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if not series_list:
        failure_text = "; ".join(f"{code}: {reason}" for code, reason in failures)
        raise RuntimeError(f"No fund NAV data fetched. Failures: {failure_text}")

    nav = pd.concat(series_list, axis=1)
    return nav.sort_index().dropna(how="all").ffill()
