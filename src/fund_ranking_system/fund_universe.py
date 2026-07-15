from __future__ import annotations

import re
from pathlib import Path

import numpy as np
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
        strategy_group = strategy_name_group(fund_name)
        anomaly_count = nav_anomaly_count(nav[str(fund)]) if str(fund) in nav.columns else 0
        quality_flags = quality_flag_text(observations, completeness, anomaly_count, min_history_days, min_completeness)
        quality_score = universe_quality_score(observations, completeness, anomaly_count, min_history_days)

        reasons: list[str] = []
        if fund_type == "active_equity":
            if inferred_type in EXCLUDED_TYPES or inferred_type not in ACTIVE_EQUITY_TYPES:
                reasons.append(f"类型不属于主动权益池：{inferred_type}")
        if observations < min_history_days:
            reasons.append(f"有效交易数据不足{min_history_days}条")
        if completeness < min_completeness:
            reasons.append(f"净值完整率低于{min_completeness:.0%}")
        if anomaly_count >= 5:
            reasons.append(f"净值异常跳变较多：{anomaly_count}次")

        rows.append(
            {
                "fund": fund,
                "fund_name": fund_name,
                "fund_type": inferred_type,
                "share_group": share_group,
                "strategy_group": strategy_group,
                "observations": observations,
                "completeness": completeness,
                "nav_anomaly_count": anomaly_count,
                "quality_score": quality_score,
                "quality_flags": quality_flags,
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

    if not audit.empty:
        duplicate_strategy_mask = audit["strategy_group"].duplicated(keep=False) & audit["universe_eligible"]
        audit.loc[duplicate_strategy_mask, "quality_flags"] = audit.loc[duplicate_strategy_mask, "quality_flags"].apply(
            lambda text: _append_flag(str(text), "疑似同策略重复产品")
        )

    return filtered, audit.sort_values(
        ["universe_eligible", "quality_score", "fund_type", "fund_name"],
        ascending=[False, False, True, True],
    )


def share_class_group(fund_name: str) -> str:
    """Remove common A/C/E share-class suffixes for rough duplicate detection."""
    name = str(fund_name).strip()
    name = re.sub(r"[\s_-]*(A|B|C|E|I|Y)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(A类|B类|C类|E类|I类|Y类)$", "", name)
    return name


def strategy_name_group(fund_name: str) -> str:
    name = share_class_group(fund_name)
    name = re.sub(r"(混合型?|股票型?|债券型?|指数型?|联接|发起式|LOF|ETF|QDII|人民币|美元|增强|优选|精选)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\s（）()A-Za-z0-9_-]+", "", name)
    return name or share_class_group(fund_name)


def nav_anomaly_count(series: pd.Series, threshold: float = 0.12) -> int:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 3:
        return 0
    returns = values.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    return int((returns.abs() > threshold).sum())


def universe_quality_score(
    observations: int,
    completeness: float,
    anomaly_count: int,
    min_history_days: int,
) -> float:
    history_score = min(observations / max(min_history_days, 1), 1.0)
    anomaly_penalty = min(anomaly_count * 0.04, 0.4)
    score = 100 * (0.55 * history_score + 0.45 * max(min(completeness, 1.0), 0.0)) - 100 * anomaly_penalty
    return float(max(min(score, 100.0), 0.0))


def quality_flag_text(
    observations: int,
    completeness: float,
    anomaly_count: int,
    min_history_days: int,
    min_completeness: float,
) -> str:
    flags: list[str] = []
    if observations < min_history_days:
        flags.append("样本期不足")
    if completeness < min_completeness:
        flags.append("净值缺失较多")
    if anomaly_count > 0:
        flags.append(f"净值跳变{anomaly_count}次")
    return "；".join(flags) if flags else "质量正常"


def _append_flag(text: str, flag: str) -> str:
    if not text or text == "质量正常":
        return flag
    if flag in text:
        return text
    return f"{text}；{flag}"


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
    avg_quality = float(audit["quality_score"].mean()) if "quality_score" in audit.columns else 0.0
    quality_issue_count = int((audit.get("quality_flags", pd.Series(dtype=object)) != "质量正常").sum()) if "quality_flags" in audit.columns else 0
    excluded_rows = audit[~audit["universe_eligible"]].head(20)
    excluded_table = _excluded_table(excluded_rows)
    quality_table = _quality_table(audit.head(20))
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
- 平均质量分：{avg_quality:.1f}
- 质量提示数量：{quality_issue_count}

## 类型分布

{type_lines}

## 排除样例

{excluded_table}

## 数据质量与重复产品提示

{quality_table}
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


def _quality_table(frame: pd.DataFrame) -> str:
    rows = [
        "| 基金 | 类型 | 完整率 | 异常跳变 | 质量分 | 质量提示 |",
        "|---|---|---:|---:|---:|---|",
    ]
    if frame.empty:
        rows.append("| 无 | - | - | - | - | - |")
    for fund, row in frame.iterrows():
        rows.append(
            f"| {fund} {row.get('fund_name', '')} | {row.get('fund_type', '')} | {row.get('completeness', 0):.1%} | {int(row.get('nav_anomaly_count', 0))} | {float(row.get('quality_score', 0)):.1f} | {row.get('quality_flags', '')} |"
        )
    return "\n".join(rows)
