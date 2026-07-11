import unittest

import pandas as pd

from fund_ranking_system.advisory import add_decision_labels


class AdvisoryTest(unittest.TestCase):
    def test_add_decision_labels_flags_high_drawdown(self):
        scored = pd.DataFrame(
            {
                "observations": [300],
                "annual_volatility": [0.32],
                "max_drawdown": [-0.65],
                "sharpe": [0.1],
                "composite_score": [85.0],
                "fund_type": ["混合型"],
            },
            index=["000001"],
        )

        labeled = add_decision_labels(scored, max_drawdown_limit=-0.6)

        self.assertEqual(labeled.loc["000001", "risk_level"], "高风险")
        self.assertEqual(labeled.loc["000001", "decision_label"], "高回撤预警")
        self.assertIn("decision_reason", labeled.columns)
        self.assertIn("result_explanation", labeled.columns)
        self.assertIn("混合型", labeled.loc["000001", "result_explanation"])


if __name__ == "__main__":
    unittest.main()
