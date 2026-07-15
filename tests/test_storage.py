import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fund_ranking_system.storage import FundDatabase


class StorageTest(unittest.TestCase):
    def test_save_and_load_nav_metadata_and_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = FundDatabase(Path(tmpdir) / "test.db")
            metadata = pd.DataFrame(
                [{"fund_code": "000001", "fund_name": "华夏成长混合", "fund_type": "混合型"}]
            )
            nav = pd.DataFrame(
                {"000001": [1.0, 1.1]},
                index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
            )

            db.save_metadata(metadata)
            db.save_nav(nav)
            loaded_nav = db.load_nav(["000001"], "2024-01-01")
            loaded_metadata = db.load_metadata(["000001"])
            cached = db.cached_codes(["000001"], "2024-01-01", min_rows=2)
            run_id = db.record_analysis(
                ["000001"],
                "2024-01-01",
                "balanced",
                10,
                "reports/test.md",
                portfolio_constraints={"objective": "defensive", "max_position_weight": 0.25},
            )
            pending_id = db.record_analysis(
                ["000001", "000002"],
                "2024-01-01",
                "balanced",
                5,
                "reports/pending.md",
                status="running",
            )
            db.update_analysis_status(
                pending_id,
                "failed",
                error_message="上游数据不可用",
            )
            db.save_pool("观察池", ["000001", "000002"])
            db.save_preset(
                "低回撤方案",
                "custom",
                {"annual_return": 0.1, "max_drawdown": 0.5},
                {"objective": "defensive"},
            )

            self.assertEqual(loaded_nav.shape, (2, 1))
            self.assertEqual(loaded_metadata.loc[0, "fund_name"], "华夏成长混合")
            self.assertEqual(loaded_metadata.loc[0, "fund_type"], "混合型")
            self.assertEqual(cached, {"000001"})
            self.assertEqual(db.get_run(run_id)["profile"], "balanced")
            self.assertEqual(db.get_run(run_id)["portfolio_constraints"]["objective"], "defensive")
            self.assertEqual(db.get_run(run_id)["status"], "success")
            self.assertEqual(db.get_run(pending_id)["status"], "failed")
            self.assertEqual(db.get_run(pending_id)["error_message"], "上游数据不可用")
            self.assertEqual(db.recent_runs()[0]["profile"], "balanced")
            self.assertIn("portfolio_constraints", db.recent_runs()[0])
            self.assertEqual(db.fund_codes(), ["000001"])
            self.assertEqual(db.nav_stats(["000001"])[0]["row_count"], 2)
            self.assertEqual(db.list_pools()[0]["name"], "观察池")
            self.assertEqual(db.get_preset("低回撤方案")["profile"], "custom")
            self.assertEqual(db.list_presets()[0]["portfolio_constraints"]["objective"], "defensive")
            db.delete_preset("低回撤方案")
            self.assertIsNone(db.get_preset("低回撤方案"))


if __name__ == "__main__":
    unittest.main()
