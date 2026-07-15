from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .fund_universe import nav_anomaly_count
from .metadata import display_fund


def save_data_quality_outputs(
    nav: pd.DataFrame,
    metrics: pd.DataFrame,
    universe_audit: pd.DataFrame,
    reports_dir: str | Path,
) -> tuple[Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = build_data_quality_diagnostics(nav, metrics, universe_audit)
    csv_path = reports_dir / "data_quality_diagnostics.csv"
    report_path = reports_dir / "data_quality_diagnostics.md"
    diagnostics.to_csv(csv_path, index=False)
    report_path.write_text(build_data_quality_report(diagnostics), encoding="utf-8")
    return csv_path, report_path


def build_data_quality_diagnostics(
    nav: pd.DataFrame,
    metrics: pd.DataFrame,
    universe_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if nav.empty:
        return pd.DataFrame(
            columns=[
                "fund",
                "fund_name",
                "fund_type",
                "start_date",
                "end_date",
                "observations",
                "completeness",
                "missing_days",
                "longest_gap_days",
                "max_daily_jump",
                "nav_anomaly_count",
                "quality_score",
                "quality_level",
                "diagnostics",
                "recommendation",
            ]
        )

    frame = nav.sort_index()
    total_dates = max(len(frame.index), 1)
    audit = universe_audit if universe_audit is not None else pd.DataFrame()
    rows: list[dict[str, object]] = []
    for fund in frame.columns:
        key = str(fund)
        series = pd.to_numeric(frame[fund], errors="coerce")
        valid = series.dropna()
        metric_row = metrics.loc[key] if key in metrics.index else pd.Series(dtype=object)
        audit_row = audit.loc[key] if not audit.empty and key in audit.index else pd.Series(dtype=object)
        observations = int(valid.count())
        completeness = observations / total_dates
        returns = valid.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        anomaly_count = int(audit_row.get("nav_anomaly_count", nav_anomaly_count(series)))
        quality_score = float(audit_row.get("quality_score", _quality_score(observations, completeness, anomaly_count)))
        diagnostics = _diagnostic_text(observations, completeness, anomaly_count, returns)
        rows.append(
            {
                "fund": key,
                "fund_name": metric_row.get("fund_name", audit_row.get("fund_name", "")),
                "fund_type": metric_row.get("fund_type", audit_row.get("fund_type", "未分类")),
                "start_date": valid.index.min().date().isoformat() if not valid.empty else "",
                "end_date": valid.index.max().date().isoformat() if not valid.empty else "",
                "observations": observations,
                "completeness": float(completeness),
                "missing_days": int(total_dates - observations),
                "longest_gap_days": _longest_gap_days(valid.index),
                "max_daily_jump": float(returns.abs().max()) if not returns.empty else 0.0,
                "nav_anomaly_count": anomaly_count,
                "quality_score": quality_score,
                "quality_level": _quality_level(quality_score),
                "diagnostics": diagnostics,
                "recommendation": _quality_recommendation(quality_score, diagnostics),
            }
        )
    return pd.DataFrame(rows).sort_values(["quality_score", "fund"], ascending=[True, True])


def build_data_quality_report(diagnostics: pd.DataFrame) -> str:
    if diagnostics.empty:
        return "# 数据质量诊断\n\n当前没有可诊断的净值数据。"

    total = len(diagnostics)
    weak = int((diagnostics["quality_level"] == "需谨慎").sum())
    warning = int((diagnostics["quality_level"] == "关注").sum())
    avg_quality = float(diagnostics["quality_score"].mean())
    avg_completeness = float(diagnostics["completeness"].mean())
    max_anomalies = int(diagnostics["nav_anomaly_count"].max())
    rows = [
        "| 基金 | 类型 | 完整率 | 缺失天数 | 最长断档 | 异常跳变 | 质量分 | 诊断 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in diagnostics.head(15).itertuples(index=False):
        rows.append(
            "| {fund} | {fund_type} | {completeness:.1%} | {missing} | {gap} | {anomaly} | {score:.1f} | {diagnostics} |".format(
                fund=display_fund(str(row.fund), pd.Series({"fund_name": row.fund_name})),
                fund_type=row.fund_type,
                completeness=float(row.completeness),
                missing=int(row.missing_days),
                gap=int(row.longest_gap_days),
                anomaly=int(row.nav_anomaly_count),
                score=float(row.quality_score),
                diagnostics=row.diagnostics,
            )
        )

    return f"""# 数据质量诊断

## 定位

本报告用于回答：本次基金池的数据是否足够稳定，排名、ML 训练和回测结果是否有可靠的数据基础。

## 总览

- 基金数量：{total}
- 平均完整率：{avg_completeness:.1%}
- 平均质量分：{avg_quality:.1f}
- 需关注基金：{warning}
- 需谨慎基金：{weak}
- 单只基金最高异常跳变次数：{max_anomalies}

## 低质量优先检查清单

{chr(10).join(rows)}

## 使用建议

- `质量正常`：可以进入多因子评分、ML 辅助评分和回测。
- `关注`：建议重点查看缺失、断档或净值跳变，必要时缩短比较窗口。
- `需谨慎`：排名和回测可信度会明显下降，建议补齐数据或从基金池中剔除。
"""


def _quality_score(observations: int, completeness: float, anomaly_count: int) -> float:
    history_score = min(observations / 700, 1.0)
    anomaly_penalty = min(anomaly_count * 0.05, 0.5)
    return float(max(min(100 * (0.5 * history_score + 0.5 * completeness) - 100 * anomaly_penalty, 100), 0))


def _quality_level(score: float) -> str:
    if score >= 85:
        return "质量正常"
    if score >= 65:
        return "关注"
    return "需谨慎"


def _diagnostic_text(observations: int, completeness: float, anomaly_count: int, returns: pd.Series) -> str:
    issues: list[str] = []
    if observations < 252:
        issues.append("样本不足一年")
    elif observations < 700:
        issues.append("历史长度偏短")
    if completeness < 0.9:
        issues.append("净值缺失偏多")
    if anomaly_count:
        issues.append(f"异常跳变{anomaly_count}次")
    if not returns.empty and float(returns.abs().max()) > 0.2:
        issues.append("存在极端单日波动")
    return "；".join(issues) if issues else "质量正常"


def _quality_recommendation(score: float, diagnostics: str) -> str:
    if score >= 85:
        return "可用于评分和回测"
    if "异常跳变" in diagnostics or "极端单日波动" in diagnostics:
        return "建议核对净值复权和异常日期"
    if "缺失" in diagnostics or "样本" in diagnostics:
        return "建议补齐数据或降低回测窗口要求"
    return "建议作为辅助观察，不单独作为结论依据"


def _longest_gap_days(index: pd.Index) -> int:
    if len(index) < 2:
        return 0
    dates = pd.to_datetime(index).sort_values()
    gaps = dates.to_series().diff().dt.days.dropna()
    return int(gaps.max()) if not gaps.empty else 0
