import unittest

import pandas as pd

from fund_ranking_system.portfolio import PortfolioConstraints
from fund_ranking_system.web import (
    _lime_explanation_table,
    _lime_preview_rows,
    _page,
    _parse_codes,
    _ranking_table,
    _resolve_codes,
    _standalone_page,
    _fund_dynamic_weight_section,
    _fund_metric_cards,
    health,
)


class WebTest(unittest.TestCase):
    def test_index_loads(self):
        html = _page()

        self.assertIn("公募基金风险收益分析系统", html)

    def test_parse_codes_normalizes_codes(self):
        self.assertEqual(_parse_codes("1, 000011 83"), ["000001", "000011", "000083"])

    def test_resolve_codes_uses_default_pool(self):
        self.assertIn("000011", _resolve_codes("", "mixed"))

    def test_page_renders_search_and_download_sections(self):
        html = _page(
            rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "rank": 1, "composite_score": 80}],
            adaptive_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "dynamic_rank": 1, "dynamic_score": 84, "base_rank": 1, "base_score": 80, "top_dynamic_factors": "Sharpe 28.0%", "dynamic_weight_reason": "稳定性较好"}],
            adaptive_weight_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "annual_return": 0.18, "sharpe": 0.28, "max_drawdown": 0.22, "calmar": 0.12, "annual_volatility": 0.09, "rolling_positive_ratio": 0.11}],
            ml_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "ml_rank": 1, "ml_score": 82}],
            comparison_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "original_rank": 1, "ml_rank": 1, "rank_change": 0, "original_score": 80, "ml_score": 82}],
            model_evaluation_rows=[{"period_id": 1, "hold_start": "2024-01-01", "hold_end": "2024-03-31", "base_rank_ic": 0.1, "ml_rank_ic": 0.2, "hit_rate_uplift": 0.1, "ml_excess_return_vs_base": 0.02, "evaluation_label": "ML改善"}],
            data_quality_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "fund_type": "混合型", "completeness": 0.98, "missing_days": 2, "nav_anomaly_count": 0, "quality_score": 92, "quality_level": "质量正常", "recommendation": "可用于评分和回测"}],
            strategy_benchmark_rows=[{"scope": "Walk-Forward", "strategy": "Top 10", "baseline_strategy": "All Funds", "excess_annual_return": 0.02, "excess_sharpe": 0.3, "drawdown_improvement": 0.01, "risk_adjusted_label": "优于基准"}],
            portfolio_rows=[{"portfolio": "动态权重TopN等权", "fund_count": 3, "annual_return": 0.08, "annual_volatility": 0.12, "max_drawdown": -0.16, "sharpe": 0.67, "win_rate": 0.55}],
            recommendation_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "fund_type": "混合型", "weight": 0.25, "selection_reason": "符合防守组合目标", "risk_note": "最大回撤 -12.0%", "diversification_note": "混合型 合计占比 50.0%"}],
            lime_rows=[{"fund": "000011", "fund_name": "华夏大盘精选混合A", "positive_factors": "sharpe (+1.20)", "negative_factors": "annual_volatility (-0.80)", "surrogate_r2": 0.91, "black_box_score": 82}],
            search_rows=[{"fund_code": "000011", "fund_name": "华夏大盘精选混合A"}],
            report_text="# 报告\n\n| 排名 | 基金 |\n|---:|---|\n| 1 | 000011 |",
            success=True,
            run_status="success",
            portfolio_constraints=PortfolioConstraints(objective="defensive", max_position_weight=0.25, transaction_cost_bps=8),
        )

        self.assertIn("基金搜索结果", html)
        self.assertIn("下载结果", html)
        self.assertIn("Word 综合报告", html)
        self.assertIn("PDF 综合报告", html)
        self.assertIn("Excel 数据汇总", html)
        self.assertIn('aria-label="常用下载"', html)
        self.assertIn("常用文件已放在上方", html)
        self.assertIn("<details", html)
        self.assertIn("报告文档", html)
        self.assertIn("组合约束", html)
        self.assertIn("防守组合", html)
        self.assertIn("同类占比上限", html)
        self.assertIn("最高相关阈值", html)
        self.assertIn("基金级动态权重报告", html)
        self.assertIn("基金级动态权重 CSV", html)
        self.assertIn("基准与同类对比报告", html)
        self.assertIn("组合构建报告", html)
        self.assertIn("组合再平衡报告", html)
        self.assertIn("组合构建摘要 CSV", html)
        self.assertIn("组合持仓权重 CSV", html)
        self.assertIn("组合约束配置 CSV", html)
        self.assertIn("组合建议说明书", html)
        self.assertIn("组合建议明细 CSV", html)
        self.assertIn("组合风险控制 CSV", html)
        self.assertIn("优化组合权重图", html)
        self.assertIn("组合再平衡结果 CSV", html)
        self.assertIn("动态权重验证报告", html)
        self.assertIn("同类基金对比 CSV", html)
        self.assertIn("动态权重排名", html)
        self.assertIn("LIME 局部解释 CSV", html)
        self.assertIn("ML 辅助评分报告", html)
        self.assertIn("ML 辅助排名", html)
        self.assertIn("原始排名 vs ML 排名", html)
        self.assertIn("模型效果评估", html)
        self.assertIn("数据质量诊断", html)
        self.assertIn("策略回测基准", html)
        self.assertIn("使用自定义评分权重", html)
        self.assertIn("保存方案", html)
        self.assertIn("LIME 局部解释预览", html)
        self.assertIn("组合构建摘要", html)
        self.assertIn("组合建议说明", html)
        self.assertIn("符合防守组合目标", html)
        self.assertIn("图表结果", html)
        self.assertIn("chart-viewer", html)
        self.assertIn("chart-option", html)
        self.assertIn("chart-main-image", html)
        self.assertIn("打开原图", html)
        self.assertIn("分析任务已完成", html)
        self.assertIn("<table>", html)

    def test_ranking_table_links_to_fund_detail(self):
        html = _ranking_table(
            [{"fund": "000011", "fund_name": "华夏大盘精选混合A", "rank": 1, "composite_score": 80}],
            run_id=7,
        )

        self.assertIn('/runs/7/funds/000011', html)

    def test_running_page_auto_refreshes(self):
        html = _page(run_status="running", run_id=1)

        self.assertIn('http-equiv="refresh"', html)
        self.assertIn("分析任务运行中", html)

    def test_lime_preview_rows_groups_factors(self):
        explanations = pd.DataFrame(
            [
                {"fund": "000011", "fund_name": "华夏大盘精选混合A", "feature": "sharpe", "local_weight": 1.2, "abs_weight": 1.2, "surrogate_r2": 0.9, "black_box_score": 82},
                {"fund": "000011", "fund_name": "华夏大盘精选混合A", "feature": "annual_volatility", "local_weight": -0.8, "abs_weight": 0.8, "surrogate_r2": 0.9, "black_box_score": 82},
            ]
        )

        rows = _lime_preview_rows(explanations, 10)
        html = _lime_explanation_table(rows)

        self.assertEqual(rows[0]["positive_factors"], "sharpe (+1.20)")
        self.assertIn("annual_volatility (-0.80)", html)

    def test_health_endpoint(self):
        payload = health()

        self.assertEqual(payload["status"], "ok")

    def test_fund_detail_sections_render(self):
        row = pd.Series(
            {
                "fund": "000011",
                "fund_name": "华夏大盘精选混合A",
                "composite_score": 80,
                "annual_return": 0.1,
                "annual_volatility": 0.2,
                "max_drawdown": -0.3,
                "sharpe": 0.5,
                "calmar": 0.33,
                "risk_level": "中高风险",
                "decision_label": "重点观察",
                "result_explanation": "样例解释",
            }
        )
        weights = pd.DataFrame(
            [
                {
                    "fund": "000011",
                    "feature_label": "Sharpe",
                    "profile_base_weight": 0.25,
                    "ml_reference_weight": 0.3,
                    "dynamic_weight": 0.32,
                    "weight_delta": 0.02,
                    "factor_score": 90,
                    "adjustment_reason": "风险调整后收益较强",
                }
            ]
        )

        html = _standalone_page(
            "详情",
            _fund_metric_cards(row) + _fund_dynamic_weight_section(weights, "000011"),
        )

        self.assertIn("指标摘要", html)
        self.assertIn("基金级动态权重", html)
        self.assertIn("风险调整后收益较强", html)


if __name__ == "__main__":
    unittest.main()
