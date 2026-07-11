from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .metadata import display_fund


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _num(value: float) -> str:
    return f"{value:.3f}"


def _top_table(scored: pd.DataFrame, top_n: int) -> str:
    rows = [
        "| 排名 | 基金 | 类型 | 同类排名 | 综合评分 | 风险等级 | 数据质量 | 决策辅助标签 | 年化收益率 | 年化波动率 | 最大回撤 | Sharpe | Calmar |",
        "|---:|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]

    for _, (fund, row) in enumerate(scored.head(top_n).iterrows(), start=1):
        rows.append(
                "| {rank} | {fund} | {fund_type} | {type_rank} | {score} | {risk} | {quality} | {label} | {ret} | {vol} | {dd} | {sharpe} | {calmar} |".format(
                rank=int(row["rank"]),
                fund=display_fund(str(fund), row),
                fund_type=row.get("fund_type", "未分类"),
                type_rank=row.get("type_rank", ""),
                score=_num(row["composite_score"]),
                risk=row.get("risk_level", ""),
                quality=row.get("data_quality", ""),
                label=row.get("decision_label", ""),
                ret=_pct(row["annual_return"]),
                vol=_pct(row["annual_volatility"]),
                dd=_pct(row["max_drawdown"]),
                sharpe=_num(row["sharpe"]),
                calmar=_num(row["calmar"]),
            )
        )

    return "\n".join(rows)


def _explanation_lines(scored: pd.DataFrame, top_n: int) -> str:
    lines = []
    for fund, row in scored.head(min(top_n, 5)).iterrows():
        lines.append(f"- {display_fund(str(fund), row)}：{row.get('result_explanation', row.get('decision_reason', ''))}")
    return "\n".join(lines)


def build_report(
    scored: pd.DataFrame,
    weights: dict[str, float],
    profile: str,
    top_n: int,
    figures: list[str],
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    weight_lines = "\n".join(
        f"- `{metric}`: {weight:.0%}" for metric, weight in weights.items()
    )
    figure_lines = "\n".join(f"- `{figure}`" for figure in figures)
    top_row = scored.iloc[0]
    top_fund = display_fund(str(scored.index[0]), top_row)

    return f"""# 公募基金风险收益评价分析报告

生成时间：{generated_at}

## 研究问题

如果公募基金筛选不能只看历史收益率，是否可以通过多因子风险收益评分模型，得到更均衡、更可解释的基金排名？

## 合规边界

本系统是基金历史表现分析与决策辅助工具，不构成个性化投资建议、收益承诺或买卖指令。实际投资还需要结合投资者风险承受能力、投资期限、流动性需求、费用、税务、基金合同和市场环境等因素。历史业绩不代表未来表现。

## 投资者画像

`{profile}`

## 因子权重

{weight_lines}

## Top {top_n} 基金排名

{_top_table(scored, top_n)}

## 核心结论

在 `{profile}` 权重假设下，排名第一的基金为 `{top_fund}`，综合评分为 {_num(top_row["composite_score"])}，风险等级为 `{top_row.get("risk_level", "")}`，决策辅助标签为 `{top_row.get("decision_label", "")}`。该基金的年化收益率为 {_pct(top_row["annual_return"])}，年化波动率为 {_pct(top_row["annual_volatility"])}，最大回撤为 {_pct(top_row["max_drawdown"])}，Sharpe Ratio 为 {_num(top_row["sharpe"])}，Calmar Ratio 为 {_num(top_row["calmar"])}。

模型采用百分位归一化方法，将收益率、波动率、最大回撤、Sharpe、Calmar 和滚动正收益比例等不同量纲的指标转化为 0-100 分的因子得分，再按照投资者风险偏好进行加权汇总。因此，排名结果不只是“收益率最高”的排序，而是同时考虑收益能力、风险控制、风险调整后收益和收益稳定性的综合评价。

## 决策辅助说明

系统输出的 `重点观察`、`可观察`、`高回撤预警` 和 `暂不优先` 是基于历史净值指标的研究标签。它们适合用于缩小基金研究范围和辅助比较，不应被理解为直接买入、持有或卖出建议。

## 结果解释

{_explanation_lines(scored, top_n)}

## 生成图表

{figure_lines}
"""


def save_report(report: str, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return path
