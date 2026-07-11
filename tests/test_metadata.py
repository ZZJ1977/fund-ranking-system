import unittest

import pandas as pd

from fund_ranking_system.metadata import attach_fund_metadata, display_fund, infer_fund_type


class MetadataTest(unittest.TestCase):
    def test_attach_fund_metadata_adds_name_column(self):
        metrics = pd.DataFrame({"annual_return": [0.1]}, index=["000001"])
        metadata = pd.DataFrame({"fund_name": ["华夏成长混合"]}, index=["000001"])

        enriched = attach_fund_metadata(metrics, metadata)

        self.assertEqual(enriched.loc["000001", "fund_name"], "华夏成长混合")
        self.assertEqual(enriched.loc["000001", "fund_type"], "混合型")
        self.assertEqual(display_fund("000001", enriched.loc["000001"]), "000001 华夏成长混合")
        self.assertEqual(infer_fund_type("某某中证500ETF联接"), "指数型")

    def test_attach_fund_metadata_handles_empty_metadata(self):
        metrics = pd.DataFrame({"annual_return": [0.1]}, index=["华夏成长混合"])

        enriched = attach_fund_metadata(metrics, pd.DataFrame())

        self.assertEqual(enriched.loc["华夏成长混合", "fund_type"], "混合型")


if __name__ == "__main__":
    unittest.main()
