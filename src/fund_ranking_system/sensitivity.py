from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metadata import display_fund
from .scoring import score_funds


def build_sensitivity_table(all_profiles: pd.DataFrame) -> pd.DataFrame:
    """Compare rank stability across investor profiles."""
    rank_columns = [column for column in all_profiles.columns if column.endswith("_rank")]
    score_columns = [column for column in all_profiles.columns if column.endswith("_score")]

    if not rank_columns:
        raise ValueError("No profile rank columns found for sensitivity analysis.")

    metadata_columns = [column for column in ["fund_name"] if column in all_profiles.columns]
    summary = all_profiles[metadata_columns + rank_columns + score_columns].copy()
    summary["best_rank"] = summary[rank_columns].min(axis=1)
    summary["worst_rank"] = summary[rank_columns].max(axis=1)
    summary["rank_spread"] = summary["worst_rank"] - summary["best_rank"]
    summary["avg_rank"] = summary[rank_columns].mean(axis=1)
    return summary.sort_values(["avg_rank", "rank_spread"])


def build_sensitivity_markdown(
    sensitivity: pd.DataFrame,
    top_n: int = 10,
) -> str:
    """Create a concise Markdown explanation of ranking sensitivity."""
    rank_columns = _profile_rank_columns(sensitivity)
    stable = sensitivity.sort_values(["rank_spread", "avg_rank"]).head(top_n)
    sensitive = sensitivity.sort_values(["rank_spread", "avg_rank"], ascending=[False, True]).head(top_n)

    lines = [
        "# 权重敏感性分析",
        "",
        "本分析比较同一批基金在激进型、平衡型、稳健型三类投资者画像下的排名变化。",
        "`rank_spread` 表示一只基金在不同画像下的最好排名与最差排名之差，数值越小，说明排名对权重假设越不敏感。",
        "",
        "## 排名较稳定的基金",
        "",
        _rank_table(stable, rank_columns),
        "",
        "## 排名变化较大的基金",
        "",
        _rank_table(sensitive, rank_columns),
        "",
        "## 模型解释",
        "",
        "权重并不是客观唯一的参数，而是投资者风险偏好的表达。"
        "因此我没有只给出一组排名，而是设计了多种风险偏好画像，并比较排名变化。"
        "如果某只基金在不同画像下都排名靠前，说明它的综合表现相对稳健；"
        "如果排名波动很大，说明它可能依赖某类特定指标，例如高收益或低回撤。",
    ]
    return "\n".join(lines)


def save_sensitivity_outputs(
    sensitivity: pd.DataFrame,
    csv_path: str | Path,
    markdown_path: str | Path,
    top_n: int = 10,
) -> tuple[Path, Path]:
    csv_path = Path(csv_path)
    markdown_path = Path(markdown_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    sensitivity.to_csv(csv_path)
    markdown_path.write_text(build_sensitivity_markdown(sensitivity, top_n), encoding="utf-8")
    return csv_path, markdown_path


def monte_carlo_weight_perturbation(
    metrics: pd.DataFrame,
    base_weights: dict[str, float],
    n_simulations: int = 1000,
    top_k: int = 10,
    concentration: float = 120.0,
    random_state: int = 42,
) -> pd.DataFrame:
    """Perturb weights around a base profile and summarize rank robustness."""
    metrics_order = list(base_weights)
    base = np.array([base_weights[metric] for metric in metrics_order], dtype=float)
    base = base / base.sum()
    rng = np.random.default_rng(random_state)
    alpha = np.maximum(base * concentration, 0.1)
    ranks = {fund: [] for fund in metrics.index}
    selected = {fund: 0 for fund in metrics.index}

    for _ in range(n_simulations):
        sampled = rng.dirichlet(alpha)
        weights = dict(zip(metrics_order, sampled, strict=True))
        scored = score_funds(metrics, weights)
        for fund, rank in scored["rank"].items():
            rank_value = int(rank)
            ranks[fund].append(rank_value)
            if rank_value <= top_k:
                selected[fund] += 1

    rows = []
    for fund, values in ranks.items():
        series = pd.Series(values)
        rows.append(
            {
                "fund": fund,
                "fund_name": metrics.loc[fund].get("fund_name", fund),
                "top_k_frequency": selected[fund] / n_simulations,
                "median_rank": float(series.median()),
                "rank_q1": float(series.quantile(0.25)),
                "rank_q3": float(series.quantile(0.75)),
                "rank_iqr": float(series.quantile(0.75) - series.quantile(0.25)),
            }
        )
    return pd.DataFrame(rows).set_index("fund").sort_values(
        ["top_k_frequency", "median_rank"],
        ascending=[False, True],
    )


def save_monte_carlo_outputs(
    robustness: pd.DataFrame,
    csv_path: str | Path,
    markdown_path: str | Path,
    top_n: int = 10,
    top_k: int = 10,
) -> tuple[Path, Path]:
    csv_path = Path(csv_path)
    markdown_path = Path(markdown_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    robustness.to_csv(csv_path)
    markdown_path.write_text(build_monte_carlo_markdown(robustness, top_n, top_k), encoding="utf-8")
    return csv_path, markdown_path


def build_monte_carlo_markdown(robustness: pd.DataFrame, top_n: int, top_k: int) -> str:
    rows = [
        "| 基金 | TopK入选频率 | 排名中位数 | Rank IQR |",
        "|---|---:|---:|---:|",
    ]
    for fund, row in robustness.head(top_n).iterrows():
        rows.append(
            f"| {display_fund(str(fund), row)} | {row['top_k_frequency']:.1%} | {row['median_rank']:.0f} | {row['rank_q1']:.0f}-{row['rank_q3']:.0f} |"
        )
    return f"""# Monte Carlo 权重扰动稳健性分析

本分析以当前投资者画像权重为中心，随机生成附近权重组合并重复评分，观察基金排名是否稳定。

- `TopK入选频率`：进入 Top {top_k} 的比例。
- `排名中位数`：多次扰动后的排名中位数。
- `Rank IQR`：排名四分位区间，区间越窄说明越稳健。

## 稳健性较强的基金

{chr(10).join(rows)}
"""


def _rank_table(frame: pd.DataFrame, rank_columns: list[str]) -> str:
    headers = ["基金", *[column.replace("_rank", "") for column in rank_columns], "rank_spread"]
    rows = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]

    for fund, row in frame.iterrows():
        values = [display_fund(str(fund), row)]
        values.extend(str(int(row[column])) for column in rank_columns)
        values.append(str(int(row["rank_spread"])))
        rows.append("| " + " | ".join(values) + " |")

    return "\n".join(rows)


def _profile_rank_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in frame.columns
        if column.endswith("_rank") and column not in {"best_rank", "worst_rank", "avg_rank"}
    ]
