from __future__ import annotations

import argparse
import html
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import uvicorn
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from .pipeline import run_pipeline
from .scoring import DEFAULT_PROFILES
from .storage import FundDatabase

WEB_RAW_DIR = Path("data/raw/web")
WEB_REPORTS_DIR = Path("reports/web")
WEB_PROCESSED_DIR = Path("data/processed/web")
FUND_POOLS = {
    "custom": ("自定义基金代码", []),
    "mixed": ("混合/主动权益样例", ["000001", "000011", "000021", "000031", "000173"]),
    "index": ("指数/ETF联接样例", ["000051", "000071", "001052", "005918", "110020"]),
    "bond": ("债券/稳健样例", ["000003", "000032", "000047", "000191", "000286"]),
}

app = FastAPI(title="Fund Ranking System")


@app.get("/", response_class=HTMLResponse)
def index(
    codes: str = "000001 000003 000011 000021 000031",
    start_date: str = "2021-01-01",
    profile: str = "balanced",
    top_n: int = 10,
    fund_pool: str = "custom",
) -> str:
    return _page(codes=codes, start_date=start_date, profile=profile, top_n=top_n, fund_pool=fund_pool)


@app.post("/analyze", response_class=HTMLResponse)
def analyze(
    codes: str = Form(""),
    start_date: str = Form("2021-01-01"),
    profile: str = Form("balanced"),
    top_n: int = Form(10),
    fund_pool: str = Form("custom"),
    keyword: str = Form(""),
) -> str:
    normalized_codes = _resolve_codes(codes, fund_pool)
    search_rows = _search_rows(keyword)

    if len(normalized_codes) < 2:
        return _page(
            codes=" ".join(normalized_codes) or codes,
            start_date=start_date,
            profile=profile,
            top_n=top_n,
            fund_pool=fund_pool,
            keyword=keyword,
            search_rows=search_rows,
            error="至少输入 2 只基金代码，排名才有比较意义。",
        )
    if profile not in DEFAULT_PROFILES:
        return _page(
            codes=" ".join(normalized_codes),
            start_date=start_date,
            profile="balanced",
            top_n=top_n,
            fund_pool=fund_pool,
            keyword=keyword,
            search_rows=search_rows,
            error=f"未知投资者画像: {profile}",
        )

    nav_path = WEB_RAW_DIR / "fund_nav.csv"
    metadata_path = WEB_RAW_DIR / "fund_metadata.csv"

    try:
        cache_message = _fetch_funds(normalized_codes, start_date, nav_path, metadata_path)
        run_slug = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        reports_dir = WEB_REPORTS_DIR / "runs" / run_slug
        processed_dir = WEB_PROCESSED_DIR / "runs" / run_slug
        result = run_pipeline(
            input_path=nav_path,
            metadata_path=metadata_path,
            profile=profile,
            top_n=top_n,
            reports_dir=reports_dir,
            processed_dir=processed_dir,
        )
        run_id = FundDatabase().record_analysis(
            normalized_codes,
            start_date,
            profile,
            top_n,
            result.report_path,
            reports_dir=result.report_path.parent,
            processed_dir=result.metrics_path.parent,
        )
    except Exception as exc:
        return _page(
            codes=" ".join(normalized_codes),
            start_date=start_date,
            profile=profile,
            top_n=top_n,
            fund_pool=fund_pool,
            keyword=keyword,
            search_rows=search_rows,
            error=f"分析失败：{exc}",
        )

    ranking = pd.read_csv(result.ranking_paths[profile]).head(top_n)
    rows = ranking.to_dict(orient="records")
    ml_rows = pd.read_csv(result.ml_ranking_path).head(top_n).to_dict(orient="records")
    comparison_rows = pd.read_csv(result.ml_comparison_path).head(top_n).to_dict(orient="records")
    report_text = result.report_path.read_text(encoding="utf-8")
    return _page(
        codes=" ".join(normalized_codes),
        start_date=start_date,
        profile=profile,
        top_n=top_n,
        fund_pool=fund_pool,
        keyword=keyword,
        rows=rows,
        ml_rows=ml_rows,
        comparison_rows=comparison_rows,
        search_rows=search_rows,
        report_text=report_text,
        cache_message=cache_message,
        run_id=run_id,
        data_stats=FundDatabase().nav_stats(normalized_codes),
        success=True,
    )


@app.get("/search", response_class=HTMLResponse)
def search(
    keyword: str = "",
    codes: str = "000001 000003 000011 000021 000031",
    start_date: str = "2021-01-01",
    profile: str = "balanced",
    top_n: int = 10,
    fund_pool: str = "custom",
) -> str:
    return _page(
        codes=codes,
        start_date=start_date,
        profile=profile,
        top_n=top_n,
        fund_pool=fund_pool,
        keyword=keyword,
        search_rows=_search_rows(keyword),
    )


@app.post("/pools/save", response_class=HTMLResponse)
def save_pool(
    pool_name: str = Form(...),
    pool_codes: str = Form(...),
) -> str:
    codes = _parse_codes(pool_codes)
    if not pool_name.strip() or len(codes) < 2:
        return _page(error="基金池名称不能为空，且至少需要 2 只基金。")
    FundDatabase().save_pool(pool_name.strip(), codes)
    return _page(codes=" ".join(codes), fund_pool=f"saved:{pool_name.strip()}")


@app.post("/pools/delete", response_class=HTMLResponse)
def delete_pool(pool_name: str = Form(...)) -> str:
    FundDatabase().delete_pool(pool_name.strip())
    return _page()


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int) -> str:
    run = FundDatabase().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    report_path = Path(str(run["report_path"]))
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else "报告文件不存在。"
    ranking_path = Path(str(run["reports_dir"])) / f"ranking_{run['profile']}.csv"
    rows = pd.read_csv(ranking_path).head(int(run["top_n"])).to_dict(orient="records") if ranking_path.exists() else []
    ml_path = Path(str(run["reports_dir"])) / f"ranking_ml_{run['profile']}.csv"
    ml_rows = pd.read_csv(ml_path).head(int(run["top_n"])).to_dict(orient="records") if ml_path.exists() else []
    comparison_path = Path(str(run["reports_dir"])) / f"ranking_comparison_{run['profile']}.csv"
    comparison_rows = pd.read_csv(comparison_path).head(int(run["top_n"])).to_dict(orient="records") if comparison_path.exists() else []
    return _page(
        codes=" ".join(run["codes"]),
        start_date=str(run["start_date"]),
        profile=str(run["profile"]),
        top_n=int(run["top_n"]),
        rows=rows,
        ml_rows=ml_rows,
        comparison_rows=comparison_rows,
        report_text=report_text,
        run_id=run_id,
        data_stats=FundDatabase().nav_stats(run["codes"]),
        success=True,
    )


@app.get("/reports/{filename}")
def report_file(filename: str) -> FileResponse:
    path = WEB_REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report file not found.")
    return FileResponse(path)


@app.get("/runs/{run_id}/reports/{filename}")
def run_report_file(run_id: int, filename: str) -> FileResponse:
    run = FundDatabase().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    path = Path(str(run["reports_dir"])) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run report file not found.")
    return FileResponse(path)


@app.get("/runs/{run_id}/processed/{filename}")
def run_processed_file(run_id: int, filename: str) -> FileResponse:
    run = FundDatabase().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    path = Path(str(run["processed_dir"])) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run processed file not found.")
    return FileResponse(path)


@app.get("/processed/{filename}")
def processed_file(filename: str) -> FileResponse:
    path = WEB_PROCESSED_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Processed file not found.")
    return FileResponse(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local fund ranking web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("fund_ranking_system.web:app", host=args.host, port=args.port, reload=False)


def _parse_codes(codes: str) -> list[str]:
    return [code.strip().zfill(6) for code in codes.replace(",", " ").split() if code.strip()]


def _resolve_codes(codes: str, fund_pool: str) -> list[str]:
    if fund_pool.startswith("saved:"):
        pool_name = fund_pool.split(":", 1)[1]
        for pool in FundDatabase().list_pools():
            if pool["name"] == pool_name:
                return list(pool["codes"])
    pool_codes = FUND_POOLS.get(fund_pool, FUND_POOLS["custom"])[1]
    if pool_codes:
        return pool_codes
    return _parse_codes(codes)


def _search_rows(keyword: str) -> list[dict[str, str]]:
    if not keyword.strip():
        return []

    try:
        from .akshare_data import search_funds

        return search_funds(keyword).to_dict(orient="records")
    except Exception as exc:
        return [{"fund_code": "搜索失败", "fund_name": str(exc)}]


def _fetch_funds(
    codes: list[str],
    start_date: str,
    nav_path: Path,
    metadata_path: Path,
) -> str:
    from .akshare_data import fetch_fund_metadata, fetch_many_funds

    WEB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    db = FundDatabase()
    cached_codes = db.cached_codes(codes, start_date)
    missing_codes = [code for code in codes if code not in cached_codes]

    if missing_codes:
        metadata = fetch_fund_metadata(missing_codes)
        nav = fetch_many_funds(missing_codes, start_date, sleep_seconds=0.2)
        db.save_metadata(metadata)
        db.save_nav(nav)

    nav = db.load_nav(codes, start_date)
    metadata = db.load_metadata(codes)
    if nav.empty:
        raise RuntimeError("本地缓存和远程接口都没有可用净值数据。")

    nav.to_csv(nav_path, index_label="Date")
    metadata.to_csv(metadata_path, index=False)
    return f"缓存命中 {len(cached_codes)} 只，远程补抓 {len(missing_codes)} 只。"


def _page(
    codes: str = "000001 000003 000011 000021 000031",
    start_date: str = "2021-01-01",
    profile: str = "balanced",
    top_n: int = 10,
    fund_pool: str = "custom",
    keyword: str = "",
    rows: list[dict[str, object]] | None = None,
    ml_rows: list[dict[str, object]] | None = None,
    comparison_rows: list[dict[str, object]] | None = None,
    search_rows: list[dict[str, str]] | None = None,
    report_text: str = "",
    cache_message: str = "",
    run_id: int | None = None,
    data_stats: list[dict[str, object]] | None = None,
    success: bool = False,
    error: str = "",
) -> str:
    profile_options = "\n".join(
        f'<option value="{name}" {"selected" if name == profile else ""}>{name}</option>'
        for name in sorted(DEFAULT_PROFILES)
    )
    saved_pools = FundDatabase().list_pools()
    pool_options = "\n".join(
        f'<option value="{key}" {"selected" if key == fund_pool else ""}>{label}</option>'
        for key, (label, _) in FUND_POOLS.items()
    )
    pool_options += "\n" + "\n".join(
        f'<option value="saved:{html.escape(str(pool["name"]))}" {"selected" if fund_pool == "saved:" + str(pool["name"]) else ""}>我的基金池：{html.escape(str(pool["name"]))}</option>'
        for pool in saved_pools
    )
    table = _ranking_table(rows or [])
    ml_table = _ml_ranking_table(ml_rows or [])
    comparison_table = _ranking_comparison_table(comparison_rows or [])
    search_section = _search_section(search_rows or [])
    history = _history_section(FundDatabase().recent_runs())
    data_status = _data_status_section(data_stats or [])
    pool_manager = _pool_manager_section(saved_pools)
    downloads = _download_section(profile, run_id) if success else ""
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    cache_html = f'<div class="cache-status">{html.escape(cache_message)}</div>' if cache_message else ""
    figures = ""
    if success:
        figure_base = f"/runs/{run_id}/reports" if run_id else "/reports"
        figures = f"""
        <div class="figure-grid">
          <img src="{figure_base}/risk_return_{profile}.png" alt="Risk return scatter">
          <img src="{figure_base}/top_scores_{profile}.png" alt="Top scores">
          <img src="{figure_base}/nav_top_{profile}.png" alt="NAV trend">
          <img src="{figure_base}/drawdown_top_{profile}.png" alt="Drawdown trend">
        </div>
        """

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>公募基金风险收益分析系统</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #176b87;
      --warn: #a94f19;
      --error: #b42318;
      --ok: #027a48;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 17px;
    }}
    header {{
      padding: 24px 32px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    .sub {{ color: var(--muted); max-width: 960px; line-height: 1.6; }}
    main {{ padding: 24px 32px 48px; }}
    form {{
      display: grid;
      grid-template-columns: minmax(280px, 2fr) 190px 160px 160px 120px auto;
      gap: 12px;
      align-items: end;
      padding: 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    label {{ display: grid; gap: 6px; font-size: 15px; color: var(--muted); }}
    input, select {{
      height: 44px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
      color: var(--text);
      background: #fff;
    }}
    button {{
      height: 44px;
      border: 0;
      border-radius: 6px;
      padding: 0 18px;
      background: var(--accent);
      color: white;
      font-weight: 600;
      cursor: pointer;
    }}
    button.secondary {{
      background: #eef2f6;
      color: var(--text);
      border: 1px solid var(--line);
    }}
    .loading {{
      display: none;
      margin: 16px 0;
      padding: 14px 16px;
      background: #eef8fb;
      border: 1px solid #b9dce6;
      border-radius: 8px;
      color: var(--accent);
      font-weight: 600;
    }}
    body.is-loading .loading {{ display: block; }}
    body.is-loading button[type="submit"] {{ opacity: 0.72; cursor: wait; }}
    .error {{
      margin: 16px 0;
      padding: 14px 16px;
      color: var(--error);
      background: #fff1f0;
      border: 1px solid #fecdca;
      border-radius: 8px;
      line-height: 1.6;
    }}
    .cache-status {{
      margin: 16px 0;
      padding: 12px 16px;
      color: var(--ok);
      background: #ecfdf3;
      border: 1px solid #abefc6;
      border-radius: 8px;
      line-height: 1.6;
    }}
    .notice {{
      margin: 16px 0;
      color: var(--warn);
      line-height: 1.6;
      font-size: 16px;
    }}
    .section {{
      margin-top: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .section h2 {{ margin: 0; padding: 16px 18px; font-size: 22px; border-bottom: 1px solid var(--line); }}
    .table-wrap {{ width: 100%; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 15px; table-layout: auto; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); background: #fbfcfd; font-weight: 600; }}
    th.num, td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    td.fund-cell {{ min-width: 220px; }}
    td.reason-cell {{ min-width: 260px; line-height: 1.55; }}
    .report-body {{ padding: 4px 18px 20px; line-height: 1.75; }}
    .report-body h1 {{ font-size: 26px; margin: 18px 0 12px; }}
    .report-body h2 {{ border: 0; padding: 0; font-size: 21px; margin: 24px 0 10px; }}
    .report-body p {{ margin: 10px 0; }}
    .report-body ul {{ margin: 10px 0 16px 24px; padding: 0; }}
    .report-body code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #eef2f6; padding: 2px 5px; border-radius: 4px; }}
    .report-body table {{ margin: 12px 0 18px; }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      padding: 16px;
    }}
    .toolbar a {{
      display: inline-flex;
      align-items: center;
      height: 40px;
      padding: 0 14px;
      border-radius: 6px;
      background: #eef2f6;
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--line);
      font-weight: 600;
    }}
    .mini-form {{
      grid-template-columns: minmax(180px, 240px) minmax(280px, 1fr) auto;
      margin: 16px;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .figure-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(280px, 1fr));
      gap: 16px;
      padding: 16px;
    }}
    img {{ width: 100%; background: #fff; border: 1px solid var(--line); border-radius: 6px; }}
    pre {{
      margin: 0;
      padding: 16px;
      white-space: pre-wrap;
      line-height: 1.55;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 15px;
    }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      form {{ grid-template-columns: 1fr; }}
      .figure-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>公募基金风险收益分析系统</h1>
    <div class="sub">输入基金代码后，系统会抓取真实净值数据，计算风险收益指标、多因子评分、风险等级和决策辅助标签。</div>
  </header>
  <main>
    <form method="post" action="/analyze" id="analysis-form">
      <label>基金代码
        <input name="codes" value="{codes}" placeholder="000001 000011 000083">
      </label>
      <label>默认基金池
        <select name="fund_pool">{pool_options}</select>
      </label>
      <label>起始日期
        <input name="start_date" value="{start_date}">
      </label>
      <label>投资者画像
        <select name="profile">{profile_options}</select>
      </label>
      <label>Top N
        <input name="top_n" type="number" min="2" max="50" value="{top_n}">
      </label>
      <button type="submit">开始分析</button>
    </form>
    <form method="get" action="/search" style="margin-top: 12px; grid-template-columns: minmax(280px, 1fr) auto;">
      <label>基金名称/代码搜索
        <input name="keyword" value="{html.escape(keyword)}" placeholder="例如：华夏成长 / 沪深300 / 000011">
      </label>
      <input type="hidden" name="codes" value="{html.escape(codes)}">
      <input type="hidden" name="start_date" value="{html.escape(start_date)}">
      <input type="hidden" name="profile" value="{html.escape(profile)}">
      <input type="hidden" name="top_n" value="{top_n}">
      <input type="hidden" name="fund_pool" value="{html.escape(fund_pool)}">
      <button type="submit" class="secondary">搜索基金</button>
    </form>
    <div class="loading">正在抓取真实基金净值并生成报告，请稍等几秒...</div>
    {error_html}
    {cache_html}
    <div class="notice">本系统仅用于历史表现分析和研究辅助，不构成个性化投资建议、收益承诺或买卖指令。</div>
    {search_section}
    {pool_manager}
    {data_status}
    {table}
    {ml_table}
    {comparison_table}
    {downloads}
    {figures}
    {_report_section(report_text)}
    {history}
  </main>
  <script>
    const form = document.getElementById('analysis-form');
    if (form) {{
      form.addEventListener('submit', () => {{
        document.body.classList.add('is-loading');
        const button = form.querySelector('button[type="submit"]');
        if (button) button.textContent = '分析中...';
      }});
    }}
  </script>
</body>
</html>"""


def _ranking_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"num\">{row.get('rank', '')}</td>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund', '')))} {html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td>{html.escape(str(row.get('fund_type', '未分类')))}</td>"
        f"<td class=\"num\">{row.get('type_rank', '')}</td>"
        f"<td class=\"num\">{float(row.get('composite_score', 0)):.2f}</td>"
        f"<td>{html.escape(str(row.get('risk_level', '')))}</td>"
        f"<td>{html.escape(str(row.get('data_quality', '')))}</td>"
        f"<td>{html.escape(str(row.get('decision_label', '')))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('result_explanation', row.get('decision_reason', ''))))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>排名结果</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th class="num">排名</th><th>基金</th><th>类型</th><th class="num">同类排名</th><th class="num">综合评分</th><th>风险等级</th><th>数据质量</th><th>标签</th><th>解释</th></tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _search_section(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund_code', '')))}</td>"
        f"<td>{html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td>{html.escape(str(row.get('fund_type', '未分类')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>基金搜索结果</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金代码</th><th>基金名称</th><th>类型</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _ml_ranking_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"num\">{row.get('ml_rank', '')}</td>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund', '')))} {html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td class=\"num\">{float(row.get('ml_score', 0)):.2f}</td>"
        f"<td class=\"num\">{float(row.get('annual_return', 0)):.2%}</td>"
        f"<td class=\"num\">{float(row.get('max_drawdown', 0)):.2%}</td>"
        f"<td class=\"num\">{float(row.get('sharpe', 0)):.3f}</td>"
        f"<td>{html.escape(str(row.get('ml_model_status', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>ML 辅助排名</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="num">ML排名</th><th>基金</th><th class="num">ML评分</th><th class="num">年化收益</th><th class="num">最大回撤</th><th class="num">Sharpe</th><th>模型状态</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _ranking_comparison_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund', '')))} {html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td class=\"num\">{row.get('original_rank', '')}</td>"
        f"<td class=\"num\">{row.get('ml_rank', '')}</td>"
        f"<td class=\"num\">{int(row.get('rank_change', 0)):+d}</td>"
        f"<td class=\"num\">{float(row.get('original_score', 0)):.2f}</td>"
        f"<td class=\"num\">{float(row.get('ml_score', 0)):.2f}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('comparison_reason', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>原始排名 vs ML 排名</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金</th><th class="num">原始排名</th><th class="num">ML排名</th><th class="num">排名变化</th><th class="num">原始评分</th><th class="num">ML评分</th><th>说明</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _download_section(profile: str, run_id: int | None) -> str:
    report_base = f"/runs/{run_id}/reports" if run_id else "/reports"
    processed_base = f"/runs/{run_id}/processed" if run_id else "/processed"
    files = [
        ("Word 综合报告", f"{report_base}/analysis_reports.docx", "reports", "analysis_reports.docx"),
        ("PDF 综合报告", f"{report_base}/analysis_reports.pdf", "reports", "analysis_reports.pdf"),
        ("Excel 数据汇总", f"{report_base}/analysis_data.xlsx", "reports", "analysis_data.xlsx"),
        ("主分析报告", f"{report_base}/fund_analysis_report.md", "reports", "fund_analysis_report.md"),
        ("基金池准入报告", f"{report_base}/fund_universe.md", "reports", "fund_universe.md"),
        ("Walk-Forward 验证报告", f"{report_base}/backtest_summary.md", "reports", "backtest_summary.md"),
        ("因子贡献解释", f"{report_base}/factor_contributions.md", "reports", "factor_contributions.md"),
        ("LIME 局部解释", f"{report_base}/lime_explanations.md", "reports", "lime_explanations.md"),
        ("ML 辅助评分报告", f"{report_base}/ml_model_report.md", "reports", "ml_model_report.md"),
        ("原始/ML 排名对比", f"{report_base}/ranking_comparison.md", "reports", "ranking_comparison.md"),
        ("因子相关性诊断", f"{report_base}/factor_diagnostics.md", "reports", "factor_diagnostics.md"),
        ("权重敏感性报告", f"{report_base}/weight_sensitivity.md", "reports", "weight_sensitivity.md"),
        ("权重扰动稳健性报告", f"{report_base}/weight_robustness.md", "reports", "weight_robustness.md"),
        ("研究附录", f"{report_base}/research_enhancement.md", "reports", "research_enhancement.md"),
        ("P3 研究报告", f"{report_base}/p3_research_enhancement.md", "reports", "p3_research_enhancement.md"),
        ("当前画像排名 CSV", f"{report_base}/ranking_{profile}.csv", "reports", f"ranking_{profile}.csv"),
        ("Walk-Forward 结果 CSV", f"{report_base}/walk_forward_results.csv", "reports", "walk_forward_results.csv"),
        ("因子贡献 CSV", f"{report_base}/factor_contributions.csv", "reports", "factor_contributions.csv"),
        ("LIME 局部解释 CSV", f"{report_base}/lime_explanations.csv", "reports", "lime_explanations.csv"),
        ("ML 学习权重 CSV", f"{report_base}/ml_learned_weights.csv", "reports", "ml_learned_weights.csv"),
        ("ML 辅助排名 CSV", f"{report_base}/ranking_ml_{profile}.csv", "reports", f"ranking_ml_{profile}.csv"),
        ("原始/ML 排名对比 CSV", f"{report_base}/ranking_comparison_{profile}.csv", "reports", f"ranking_comparison_{profile}.csv"),
        ("ML 训练样本 CSV", f"{report_base}/ml_training_samples.csv", "reports", "ml_training_samples.csv"),
        ("全部画像排名 CSV", f"{processed_base}/ranking_all_profiles.csv", "processed", "ranking_all_profiles.csv"),
        ("指标明细 CSV", f"{processed_base}/fund_metrics.csv", "processed", "fund_metrics.csv"),
    ]
    available_files = _available_downloads(files, run_id)
    links = "\n".join(f'<a href="{href}" download>{label}</a>' for label, href in available_files)
    return f"""
    <section class="section">
      <h2>下载结果</h2>
      <div class="toolbar">{links}</div>
    </section>
    """


def _available_downloads(
    files: list[tuple[str, str, str, str]],
    run_id: int | None,
) -> list[tuple[str, str]]:
    if run_id is None:
        return [(label, href) for label, href, _, _ in files]

    run = FundDatabase().get_run(run_id)
    if run is None:
        return []

    roots = {
        "reports": Path(str(run["reports_dir"])),
        "processed": Path(str(run["processed_dir"])),
    }
    available = []
    seen_labels = set()
    for label, href, root_name, filename in files:
        path = roots[root_name] / filename
        if path.exists() and label not in seen_labels:
            available.append((label, href))
            seen_labels.add(label)
    return available


def _data_status_section(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row['fund_code']))}</td>"
        f"<td>{html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td>{html.escape(str(row.get('fund_type', '未分类')))}</td>"
        f"<td>{html.escape(str(row['start_date']))}</td>"
        f"<td>{html.escape(str(row['end_date']))}</td>"
        f"<td class=\"num\">{row['row_count']}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>本地数据状态</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金代码</th><th>基金名称</th><th>类型</th><th>最早日期</th><th>最新日期</th><th class="num">数据条数</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _pool_manager_section(pools: list[dict[str, object]]) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(pool['name']))}</td>"
        f"<td>{html.escape(' '.join(pool['codes']))}</td>"
        f"<td>{html.escape(str(pool['updated_at']))}</td>"
        f"<td><form method=\"post\" action=\"/pools/delete\" style=\"display:block;padding:0;border:0;background:transparent;\"><input type=\"hidden\" name=\"pool_name\" value=\"{html.escape(str(pool['name']))}\"><button class=\"secondary\" type=\"submit\">删除</button></form></td>"
        "</tr>"
        for pool in pools
    )
    table = ""
    if rows:
        table = f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>名称</th><th>基金代码</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """
    return f"""
    <section class="section">
      <h2>基金池管理</h2>
      <form method="post" action="/pools/save" class="mini-form">
        <label>基金池名称
          <input name="pool_name" placeholder="例如：我的观察池">
        </label>
        <label>基金代码
          <input name="pool_codes" placeholder="000001 000011 000083">
        </label>
        <button type="submit">保存基金池</button>
      </form>
      {table}
    </section>
    """


def _history_section(runs: list[dict[str, object]]) -> str:
    if not runs:
        return ""

    body = "\n".join(
        _history_row(run)
        for run in runs
    )
    return f"""
    <section class="section">
      <h2>最近分析历史</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>基金代码</th><th>起始日期</th><th>画像</th><th class="num">Top N</th><th>操作</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _history_row(run: dict[str, object]) -> str:
    params = urlencode(
        {
            "codes": " ".join(run["codes"]),
            "start_date": run["start_date"],
            "profile": run["profile"],
            "top_n": run["top_n"],
            "fund_pool": "custom",
        }
    )
    return (
        "<tr>"
        f"<td>{html.escape(str(run['created_at']))}</td>"
        f"<td>{html.escape(' '.join(run['codes']))}</td>"
        f"<td>{html.escape(str(run['start_date']))}</td>"
        f"<td>{html.escape(str(run['profile']))}</td>"
        f"<td class=\"num\">{run['top_n']}</td>"
        f"<td><a href=\"/runs/{run['id']}\">打开</a> · <a href=\"/?{params}\">复用</a></td>"
        "</tr>"
    )


def _report_section(report_text: str) -> str:
    if not report_text:
        return ""
    return f"""
    <section class="section">
      <h2>分析报告</h2>
      <div class="report-body">{_markdown_to_html(report_text)}</div>
    </section>
    """


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    in_list = False
    index = 0

    while index < len(lines):
        line = lines[index].strip()

        if not line:
            if in_list:
                output.append("</ul>")
                in_list = False
            index += 1
            continue

        if _is_markdown_table_start(lines, index):
            if in_list:
                output.append("</ul>")
                in_list = False
            table_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            output.append(_markdown_table_to_html(table_lines))
            continue

        if line.startswith("# "):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<h1>{_inline_markdown(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<h2>{_inline_markdown(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{_inline_markdown(line[2:])}</li>")
        else:
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<p>{_inline_markdown(line)}</p>")

        index += 1

    if in_list:
        output.append("</ul>")

    return "\n".join(output)


def _is_markdown_table_start(lines: list[str], index: int) -> bool:
    separator = lines[index + 1].strip().replace("|", "").strip() if index + 1 < len(lines) else ""
    return (
        index + 1 < len(lines)
        and lines[index].strip().startswith("|")
        and bool(separator)
        and all(char in "-: " for char in separator)
    )


def _markdown_table_to_html(table_lines: list[str]) -> str:
    rows = [_split_markdown_row(line) for line in table_lines]
    if len(rows) < 2:
        return ""

    headers = rows[0]
    body_rows = rows[2:]
    header_html = "".join(f"<th>{_inline_markdown(cell)}</th>" for cell in headers)
    body_html = "\n".join(
        "<tr>"
        + "".join(
            f"<td class=\"{'num' if _looks_numeric(cell) else ''}\">{_inline_markdown(cell)}</td>"
            for cell in row
        )
        + "</tr>"
        for row in body_rows
    )
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    """


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    parts = escaped.split("`")
    for index in range(1, len(parts), 2):
        parts[index] = f"<code>{parts[index]}</code>"
    return "".join(parts)


def _looks_numeric(text: str) -> bool:
    cleaned = text.replace("%", "").replace(".", "").replace("-", "").strip()
    return bool(cleaned) and cleaned.isdigit()
