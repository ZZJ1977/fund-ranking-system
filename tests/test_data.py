import unittest

import pandas as pd

from fund_ranking_system.data import align_nav_to_common_start, common_nav_start


class DataTest(unittest.TestCase):
    def test_align_nav_to_common_start_uses_latest_first_valid_date(self):
        dates = pd.bdate_range("2024-01-01", periods=5)
        nav = pd.DataFrame(
            {
                "159325": [1.00, 1.01, 1.02, 1.03, 1.04],
                "588170": [None, None, 2.00, 2.01, 2.02],
            },
            index=dates,
        )

        self.assertEqual(common_nav_start(nav), dates[2])

        aligned = align_nav_to_common_start(nav)

        self.assertEqual(aligned.index[0], dates[2])
        self.assertEqual(aligned.index[-1], dates[-1])
        self.assertFalse(aligned.iloc[0].isna().any())


if __name__ == "__main__":
    unittest.main()
