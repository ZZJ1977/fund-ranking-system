from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


EXCLUDED_TYPES = {"货币型", "债券型", "QDII"}
ACTIVE_EQUITY_TYPES = {"股票型", "混合型", "未分类"}


def build_fund_universe(
    metrics: pd.DataFrame,
    nav: pd.DataFrame,
    fund_type: str = "active_equity",
    min_history_days: int = 700,
    min_completeness: float = 0.95,
    deduplicate_share_class: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter funds into a comparable analysis universe."""
    if metrics.empty:
        return metrics, pd.DataFrame()

    rows: list[dict[str, object]] = []
    total_dates = max(len(nav.index), 1)
    for fund, row in metrics.iterrows():
        fund_name = str(row.get("fund_name", fund))
        inferred_type = str(row.get("fund_type", "未分类"))
        observations = int(row.get("observations", 0))
        completeness = float(nav[str(fund)].notna().sum() / total_dates) if str(fund) in nav.columns else 0.0
        share_group = share_class_group(fund_name)

        reasons: list[str] = []
        if fund_type == "active_equity":
            if inferred_type in EXCLUDED_TYPES or inferred_type not in ACTIVE_EQUITY_TYPES:
                reasons.append(f"类型不属于主动权益池：{inferred_type}")
        if observations < min_history_days:
            reasons.append(f"有效交易数据不足{min_history_days}条")
        if completeness < min_completeness:
            reasons.append(f"净值完整率低于{min_completeness:.0%}")

        rows.append(
            {
                "fund": fund,
                "fund_name": fund_name,
                "fund_type": inferred_type,
                "share_group": share_group,
                "observations": observations,
                "completeness": completeness,
                "universe_eligible": not reasons,
                "exclude_reason": "；".join(reasons),
            }
        )

    audit = pd.DataFrame(rows).set_index("fund")
    eligible_index = audit.index[audit["universe_eligible"]].tolist()
    filtered = metrics.loc[eligible_index].copy()

    if deduplicate_share_class and not filtered.empty:
        keep = (
            audit.loc[filtered.index]
            .assign(_score=filtered.get("observations", 0))
            .sort_values(["share_group", "_score"], ascending=[True, False])
            .groupby("share_group")
            .head(1)
            .index
        )
        duplicate_mask = audit.index.isin(eligible_index) & ~audit.index.isin(keep)
        audit.loc[duplicate_mask, "universe_eligible"] = False
        audit.loc[duplicate_mask, "exclude_reason"] = "同一基金不同份额，保留代表份额"
        filtered = filtered.loc[keep].copy()

    return filtered, audit.sort_values(["universe_eligible", "fund_type", "fund_name"], ascending=[False, True, True])


def share_class_group(fund_name: str) -> str:
    """Remove common A/C/E share-class suffixes for rough duplicate detection."""
    name = str(fund_name).strip()
    name = re.sub(r"[\s_-]*(A|B|C|E|I|Y)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(A类|B类|C类|E类|I类|Y类)$", "", name)
    return name


def save_universe_outputs(
    audit: pd.DataFrame,
    csv_path: str | Path,
    markdown_path: str | Path,
) -> tuple[Path, Path]:
    csv_path = Path(csv_path)
    markdown_path = Path(markdown_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(csv_path)
    markdown_path.write_text(build_universe_markdown(audit), encoding="utf-8")
    return csv_path, markdown_path


def build_universe_markdown(audit: pd.DataFrame) -> str:
    if audit.empty:
        return "# 基金池准入报告\n\n没有可分析的基金。"
    total = len(audit)
    eligible = int(audit["universe_eligible"].sum())
    excluded = total - eligible
    type_counts = audit["fund_type"].value_counts().to_dict()
    type_lines = "\n".join(f"- {fund_type}: {count}" for fund_type, count in type_counts.items())
    excluded_rows = audit[~audit["universe_eligible"]].head(20)
    excluded_table = _excluded_table(excluded_rows)
    return f"""# 基金池准入报告

## 准入规则

- 默认分析主动权益类基金，排除货币型、债券型、QDII 和明显不可比品类。
- 有效交易数据不少于 700 条。
- 净值完整率不低于 95%。
- 对 A/C 等重复份额默认保留一个代表份额。

## 准入结果

- 总基金数：{total}
- 纳入分析：{eligible}
- 排除数量：{excluded}

## 类型分布

{type_lines}

## 排除样例

{excluded_table}
"""


def _excluded_table(frame: pd.DataFrame) -> str:
    rows = [
        "| 基金 | 类型 | 完整率 | 排除原因 |",
        "|---|---|---:|---|",
    ]
    if frame.empty:
        rows.append("| 无 | - | - | - |")
    for fund, row in frame.iterrows():
        rows.append(
            f"| {fund} {row.get('fund_name', '')} | {row.get('fund_type', '')} | {row.get('completeness', 0):.1%} | {row.get('exclude_reason', '')} |"
        )
    return "\n".join(rows)
