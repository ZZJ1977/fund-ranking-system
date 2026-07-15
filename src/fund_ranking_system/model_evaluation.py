from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .scoring import SCORE_METRICS, score_funds


def save_model_evaluation_outputs(
    training_samples: pd.DataFrame,
    base_weights: dict[str, float],
    ml_weights: dict[str, float],
    reports_dir: str | Path,
    top_pct: float = 0.2,
) -> tuple[Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    evaluation = evaluate_model_effectiveness(training_samples, base_weights, ml_weights, top_pct=top_pct)
    csv_path = reports_dir / "ml_evaluation.csv"
    report_path = reports_dir / "ml_evaluation.md"
    evaluation.to_csv(csv_path, index=False)
    report_path.write_text(build_model_evaluation_report(evaluation), encoding="utf-8")
    return csv_path, report_path


def evaluate_model_effectiveness(
    training_samples: pd.DataFrame,
    base_weights: dict[str, float],
    ml_weights: dict[str, float],
    top_pct: float = 0.2,
) -> pd.DataFrame:
    required = {"period_id", "future_return", "future_return_rank", *SCORE_METRICS}
    if training_samples.empty or not required.issubset(training_samples.columns):
        return pd.DataFrame(columns=_evaluation_columns())

    rows: list[dict[str, object]] = []
    for period_id, group in training_samples.dropna(subset=["future_return", "future_return_rank"]).groupby("period_id"):
        if len(group) < 3:
            continue
        metrics = group.set_index("fund")[SCORE_METRICS].apply(pd.to_numeric, errors="coerce")
        future_rank = group.set_index("fund")["future_return_rank"].astype(float)
        future_return = group.set_index("fund")["future_return"].astype(float)
        base_scored = score_funds(metrics, _usable_weights(base_weights))
        ml_scored = score_funds(metrics, _usable_weights(ml_weights))
        top_count = max(1, int(np.ceil(len(group) * top_pct)))
        base_top = base_scored.head(top_count).index
        ml_top = ml_scored.head(top_count).index
        actual_top = future_rank.nlargest(top_count).index
        base_rank_ic = _spearman(base_scored["composite_score"], future_rank)
        ml_rank_ic = _spearman(ml_scored["composite_score"], future_rank)
        base_top_return = float(future_return.reindex(base_top).mean())
        ml_top_return = float(future_return.reindex(ml_top).mean())
        all_return = float(future_return.mean())
        rows.append(
            {
                "period_id": int(period_id),
                "train_start": group["train_start"].iloc[0],
                "train_end": group["train_end"].iloc[0],
                "hold_start": group["hold_start"].iloc[0],
                "hold_end": group["hold_end"].iloc[0],
                "sample_count": int(len(group)),
                "top_count": int(top_count),
                "base_rank_ic": base_rank_ic,
                "ml_rank_ic": ml_rank_ic,
                "rank_ic_uplift": ml_rank_ic - base_rank_ic if pd.notna(ml_rank_ic) and pd.notna(base_rank_ic) else np.nan,
                "base_top_hit_rate": _hit_rate(base_top, actual_top),
                "ml_top_hit_rate": _hit_rate(ml_top, actual_top),
                "hit_rate_uplift": _hit_rate(ml_top, actual_top) - _hit_rate(base_top, actual_top),
                "all_funds_future_return": all_return,
                "base_top_future_return": base_top_return,
                "ml_top_future_return": ml_top_return,
                "ml_excess_return_vs_base": ml_top_return - base_top_return,
                "ml_excess_return_vs_all": ml_top_return - all_return,
                "evaluation_label": _evaluation_label(ml_top_return - base_top_return, _hit_rate(ml_top, actual_top) - _hit_rate(base_top, actual_top)),
            }
        )
    return pd.DataFrame(rows, columns=_evaluation_columns())


def build_model_evaluation_report(evaluation: pd.DataFrame) -> str:
    if evaluation.empty:
        return """# 模型效果评估

当前训练样本不足，无法生成模型效果评估。建议扩大基金池或延长净值历史。"""

    summary = {
        "periods": int(evaluation["period_id"].nunique()),
        "sample_count": int(evaluation["sample_count"].sum()),
        "base_rank_ic": float(evaluation["base_rank_ic"].mean()),
        "ml_rank_ic": float(evaluation["ml_rank_ic"].mean()),
        "hit_uplift": float(evaluation["hit_rate_uplift"].mean()),
        "return_uplift": float(evaluation["ml_excess_return_vs_base"].mean()),
        "positive_periods": int((evaluation["ml_excess_return_vs_base"] > 0).sum()),
    }
    rows = [
        "| 窗口 | 持有期 | Base Rank IC | ML Rank IC | 命中率提升 | ML相对Base收益 | 结论 |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in evaluation.tail(12).itertuples(index=False):
        rows.append(
            "| {period} | {hold_start} ~ {hold_end} | {base_ic:.3f} | {ml_ic:.3f} | {hit:+.1%} | {ret:+.2%} | {label} |".format(
                period=int(row.period_id),
                hold_start=row.hold_start,
                hold_end=row.hold_end,
                base_ic=float(row.base_rank_ic) if pd.notna(row.base_rank_ic) else float("nan"),
                ml_ic=float(row.ml_rank_ic) if pd.notna(row.ml_rank_ic) else float("nan"),
                hit=float(row.hit_rate_uplift) if pd.notna(row.hit_rate_uplift) else 0.0,
                ret=float(row.ml_excess_return_vs_base) if pd.notna(row.ml_excess_return_vs_base) else 0.0,
                label=row.evaluation_label,
            )
        )

    return f"""# 模型效果评估

## 定位

本页不只展示 ML 权重，而是检查 ML 辅助模型在滚动历史窗口中是否相对原始画像权重带来更好的样本外区分能力。

## 总览

- 有效评估窗口：{summary['periods']}
- 基金级样本数：{summary['sample_count']}
- 原始权重平均 Rank IC：{summary['base_rank_ic']:.3f}
- ML 权重平均 Rank IC：{summary['ml_rank_ic']:.3f}
- 平均 Top 命中率提升：{summary['hit_uplift']:+.1%}
- 平均 Top 组合收益提升：{summary['return_uplift']:+.2%}
- ML 收益优于 Base 的窗口数：{summary['positive_periods']} / {summary['periods']}

## 最近评估窗口

{chr(10).join(rows)}

## 使用边界

Rank IC、Top 命中率和收益提升用于衡量历史样本外区分能力，不代表未来收益承诺。若评估窗口较少或提升不稳定，应把 ML 结果作为辅助参考，而不是替代原始多因子模型。
"""


def _evaluation_columns() -> list[str]:
    return [
        "period_id",
        "train_start",
        "train_end",
        "hold_start",
        "hold_end",
        "sample_count",
        "top_count",
        "base_rank_ic",
        "ml_rank_ic",
        "rank_ic_uplift",
        "base_top_hit_rate",
        "ml_top_hit_rate",
        "hit_rate_uplift",
        "all_funds_future_return",
        "base_top_future_return",
        "ml_top_future_return",
        "ml_excess_return_vs_base",
        "ml_excess_return_vs_all",
        "evaluation_label",
    ]


def _usable_weights(weights: dict[str, float]) -> dict[str, float]:
    return {metric: float(weights.get(metric, 0.0)) for metric in SCORE_METRICS if metric in weights}


def _spearman(score: pd.Series, future_rank: pd.Series) -> float:
    aligned = pd.concat([score.rename("score"), future_rank.rename("future")], axis=1).dropna()
    if len(aligned) < 3 or aligned["score"].nunique() <= 1 or aligned["future"].nunique() <= 1:
        return float("nan")
    return float(aligned["score"].rank().corr(aligned["future"].rank()))


def _hit_rate(selected: pd.Index, actual_top: pd.Index) -> float:
    selected_set = set(selected)
    actual_set = set(actual_top)
    if not selected_set:
        return 0.0
    return len(selected_set & actual_set) / len(selected_set)


def _evaluation_label(return_uplift: float, hit_uplift: float) -> str:
    if return_uplift > 0 and hit_uplift >= 0:
        return "ML改善"
    if return_uplift < 0 and hit_uplift <= 0:
        return "ML未改善"
    return "信号分化"
