from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_fund_metadata(path: str | Path) -> pd.DataFrame:
    """Load fund code/name metadata from a CSV file."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["fund_code", "fund_name", "fund_type"]).set_index("fund_code")

    metadata = pd.read_csv(path, dtype={"fund_code": str})
    required_columns = {"fund_code", "fund_name"}
    missing = required_columns - set(metadata.columns)
    if missing:
        raise ValueError(f"Fund metadata is missing columns: {missing}")

    metadata["fund_code"] = metadata["fund_code"].str.zfill(6)
    metadata["fund_name"] = metadata["fund_name"].fillna(metadata["fund_code"])
    if "fund_type" not in metadata.columns:
        metadata["fund_type"] = metadata["fund_name"].apply(infer_fund_type)
    metadata["fund_type"] = metadata["fund_type"].fillna("未分类")
    return metadata.drop_duplicates("fund_code").set_index("fund_code")


def attach_fund_metadata(metrics: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    """Attach fund names to a metrics table indexed by fund code."""
    enriched = metrics.copy()
    if metadata.empty:
        if "fund_name" not in enriched.columns:
            enriched.insert(0, "fund_name", pd.Series(enriched.index, index=enriched.index))
        if "fund_type" not in enriched.columns:
            enriched.insert(1, "fund_type", enriched["fund_name"].apply(infer_fund_type))
        return enriched

    aligned = metadata.reindex(enriched.index.astype(str))
    enriched.insert(0, "fund_name", aligned["fund_name"].fillna(pd.Series(enriched.index, index=enriched.index)))
    if "fund_type" in aligned.columns:
        enriched.insert(1, "fund_type", aligned["fund_type"].fillna("未分类"))
    else:
        enriched.insert(1, "fund_type", enriched["fund_name"].apply(infer_fund_type))
    return enriched


def display_fund(fund_code: str, row: pd.Series) -> str:
    """Format a fund as 'code name' when metadata is available."""
    code = str(fund_code).strip()
    fund_name = row.get("fund_name")
    name = "" if pd.isna(fund_name) else str(fund_name).strip()
    if not code:
        return name
    if not name or name == code:
        return code
    return f"{code} {name}"


def infer_fund_type(fund_name: str | object) -> str:
    """Infer a broad fund type from the Chinese fund name."""
    name = "" if pd.isna(fund_name) else str(fund_name)
    if any(keyword in name for keyword in ["货币", "现金", "添利宝"]):
        return "货币型"
    if any(keyword in name for keyword in ["QDII", "全球", "海外", "港股", "美元"]):
        return "QDII"
    if any(keyword in name for keyword in ["债券", "纯债", "转债", "可转债", "短债"]):
        return "债券型"
    if any(keyword in name for keyword in ["指数", "ETF", "联接", "增强"]):
        return "指数型"
    if any(keyword in name for keyword in ["股票"]):
        return "股票型"
    if any(keyword in name for keyword in ["混合", "灵活配置", "成长", "精选", "优势", "价值"]):
        return "混合型"
    return "未分类"
