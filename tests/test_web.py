import unittest

from fund_ranking_system.web import _page, _parse_codes, _resolve_codes


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
            search_rows=[{"fund_code": "000011", "fund_name": "华夏大盘精选混合A"}],
            report_text="# 报告\n\n| 排名 | 基金 |\n|---:|---|\n| 1 | 000011 |",
            success=True,
        )

        self.assertIn("基金搜索结果", html)
        self.assertIn("下载结果", html)
        self.assertIn("LIME 局部解释 CSV", html)
        self.assertIn("<table>", html)


if __name__ == "__main__":
    unittest.main()
