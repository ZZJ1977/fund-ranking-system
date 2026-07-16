import unittest
from unittest.mock import patch

import pandas as pd

from fund_ranking_system import akshare_data


class AkShareDataTest(unittest.TestCase):
    def test_fetch_fund_metadata_uses_full_name_table_for_etf_codes(self):
        fund_names = pd.DataFrame(
            {
                "基金代码": ["159325", "588170"],
                "拼音缩写": ["BDTETFNF", "KCBDTETFHX"],
                "基金简称": ["半导体ETF南方", "科创半导体ETF华夏"],
                "基金类型": ["指数型-股票", "指数型-股票"],
                "拼音全称": ["BANDAOTIETFNANFANG", "KECHUANGBANDAOTIETFHUAXIA"],
            }
        )

        with patch.object(akshare_data.ak, "fund_name_em", return_value=fund_names):
            metadata = akshare_data.fetch_fund_metadata(["159325", "588170"])

        self.assertEqual(
            metadata.loc[metadata["fund_code"] == "159325", "fund_name"].iloc[0],
            "半导体ETF南方",
        )
        self.assertEqual(
            metadata.loc[metadata["fund_code"] == "588170", "fund_name"].iloc[0],
            "科创半导体ETF华夏",
        )
        self.assertEqual(set(metadata["fund_type"]), {"指数型-股票"})


if __name__ == "__main__":
    unittest.main()
