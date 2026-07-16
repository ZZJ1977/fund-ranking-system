import unittest

from fund_ranking_system.time_utils import display_time, now_text


class TimeUtilsTest(unittest.TestCase):
    def test_display_time_converts_legacy_utc_to_beijing_time(self):
        self.assertEqual(display_time("2026-07-16 05:51:29"), "2026-07-16 13:51:29")

    def test_display_time_keeps_offset_aware_beijing_time(self):
        self.assertEqual(display_time("2026-07-16 13:51:29+08:00"), "2026-07-16 13:51:29")

    def test_now_text_includes_beijing_offset(self):
        self.assertTrue(now_text().endswith("+08:00"))


if __name__ == "__main__":
    unittest.main()
