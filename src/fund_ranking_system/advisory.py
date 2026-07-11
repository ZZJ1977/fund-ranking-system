from __future__ import annotations

import pandas as pd


def add_decision_labels(
    scored: pd.DataFrame,
    min_observations: int = 252,
    max_drawdown_limit: float = -0.6,
) -> pd.DataFrame:
    """Add risk, data quality and non-personalized decision-support labels."""
    labeled = scored.copy()
    labeled["risk_level"] = labeled.apply(_risk_level, axis=1)
    labeled["data_quality"] = labeled.apply(
        lambda row: _data_quality(row, min_observations=min_observations),
        axis=1,
    )
    labeled["decision_label"] = labeled.apply(
        lambda row: _decision_label(row, max_drawdown_limit=max_drawdown_limit),
        axis=1,
    )
    labeled["decision_reason"] = labeled.apply(_decision_reason, axis=1)
    labeled["result_explanation"] = labeled.apply(_result_explanation, axis=1)
    return labeled


def _risk_level(row: pd.Series) -> str:
    volatility = row["annual_volatility"]
    drawdown = row["max_drawdown"]

    if volatility >= 0.28 or drawdown <= -0.55:
        return "高风险"
    if volatility >= 0.18 or drawdown <= -0.35:
        return "中高风险"
    if volatility >= 0.10 or drawdown <= -0.20:
        return "中等风险"
    return "较低风险"


def _decision_label(row: pd.Series, max_drawdown_limit: float) -> str:
    if row["observations"] < 252:
        return "暂不纳入核心观察池"
    if row["max_drawdown"] <= max_drawdown_limit:
        return "高回撤预警"
    if row["composite_score"] >= 80:
        return "重点观察"
    if row["composite_score"] >= 60:
        return "可观察"
    return "暂不优先"


def _decision_reason(row: pd.Series) -> str:
    parts: list[str] = []

    if row["composite_score"] >= 80:
        parts.append("综合评分较高")
    elif row["composite_score"] >= 60:
        parts.append("综合评分处于中上水平")
    else:
        parts.append("综合评分相对靠后")

    if row["max_drawdown"] <= -0.55:
        parts.append("历史最大回撤较深")
    elif row["max_drawdown"] >= -0.30:
        parts.append("历史回撤控制相对较好")

    if row["sharpe"] > 0:
        parts.append("风险调整后收益为正")
    else:
        parts.append("风险调整后收益偏弱")

    return "；".join(parts)


def _data_quality(row: pd.Series, min_observations: int) -> str:
    observations = int(row.get("observations", 0))
    issues: list[str] = []
    if observations < min_observations:
        issues.append("样本期较短")
    if pd.isna(row.get("rolling_positive_ratio")):
        issues.append("滚动收益窗口不足")
    if row.get("annual_volatility", 0) <= 0:
        issues.append("波动率异常")
    if not issues:
        return "数据较充分"
    return "；".join(issues)


def _result_explanation(row: pd.Series) -> str:
    fund_type = str(row.get("fund_type", "未分类"))
    score = float(row.get("composite_score", 0))
    drawdown = float(row.get("max_drawdown", 0))
    volatility = float(row.get("annual_volatility", 0))
    sharpe = float(row.get("sharpe", 0))
    data_quality = str(row.get("data_quality", ""))

    if score >= 80:
        opening = "综合表现靠前"
    elif score >= 60:
        opening = "综合表现处于中上水平"
    else:
        opening = "综合表现相对靠后"

    risk_note = "回撤控制相对较好"
    if drawdown <= -0.55:
        risk_note = "历史最大回撤较深，需要重点关注下行风险"
    elif drawdown <= -0.35 or volatility >= 0.18:
        risk_note = "波动或回撤压力较明显"

    sharpe_note = "风险调整后收益为正" if sharpe > 0 else "风险调整后收益偏弱"
    quality_note = "" if data_quality == "数据较充分" else f"；同时存在{data_quality}问题"
    return f"该基金归类为{fund_type}，{opening}，{risk_note}，{sharpe_note}{quality_note}。"
