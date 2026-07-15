from __future__ import annotations

import argparse
import html
import socket
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import pandas as pd
import uvicorn
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .pipeline import run_pipeline
from .portfolio import PORTFOLIO_OBJECTIVES, PortfolioConstraints, normalize_portfolio_constraints
from .scoring import DEFAULT_PROFILES, SCORE_METRICS
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
FACTOR_LABELS = {
    "annual_return": "年化收益",
    "sharpe": "Sharpe",
    "max_drawdown": "最大回撤",
    "calmar": "Calmar",
    "annual_volatility": "年化波动",
    "rolling_positive_ratio": "滚动正收益",
}

app = FastAPI(title="Fund Ranking System")


@app.get("/health")
def health() -> dict[str, object]:
    db = FundDatabase()
    db.recent_runs(limit=1)
    return {
        "status": "ok",
        "service": "fund-ranking-system",
        "database": str(db.path),
        "reports_dir": str(WEB_REPORTS_DIR),
    }


@app.get("/", response_class=HTMLResponse)
def index(
    codes: str = "000001 000003 000011 000021 000031",
    start_date: str = "2021-01-01",
    profile: str = "balanced",
    top_n: int = 10,
    fund_pool: str = "custom",
    preset: str = "",
    use_custom_weights: str = "",
    weight_annual_return: float | None = None,
    weight_sharpe: float | None = None,
    weight_max_drawdown: float | None = None,
    weight_calmar: float | None = None,
    weight_annual_volatility: float | None = None,
    weight_rolling_positive_ratio: float | None = None,
    portfolio_objective: str = "balanced",
    portfolio_min_funds: int = 3,
    portfolio_max_funds: int = 8,
    max_position_weight: float = 0.35,
    max_type_weight: float = 0.65,
    max_pair_correlation: float = 0.9,
    portfolio_max_drawdown: float = -0.45,
    portfolio_min_sharpe: float = 0.0,
    rebalance_days: int = 63,
    max_turnover: float = 0.6,
    transaction_cost_bps: float = 0.0,
) -> str:
    portfolio_constraints = normalize_portfolio_constraints(
        objective=portfolio_objective,
        min_funds=portfolio_min_funds,
        max_funds=portfolio_max_funds,
        max_position_weight=max_position_weight,
        max_type_weight=max_type_weight,
        max_pair_correlation=max_pair_correlation,
        max_drawdown_floor=portfolio_max_drawdown,
        min_sharpe=portfolio_min_sharpe,
        rebalance_days=rebalance_days,
        max_turnover=max_turnover,
        transaction_cost_bps=transaction_cost_bps,
    )
    factor_weights = _factor_weights_from_values(
        profile,
        weight_annual_return,
        weight_sharpe,
        weight_max_drawdown,
        weight_calmar,
        weight_annual_volatility,
        weight_rolling_positive_ratio,
    )
    if preset:
        saved = FundDatabase().get_preset(preset)
        if saved is not None:
            profile = str(saved["profile"])
            portfolio_constraints = normalize_portfolio_constraints(saved.get("portfolio_constraints"))
            factor_weights = _normalize_factor_weights(saved.get("factor_weights"), profile)
            use_custom_weights = "1"
    if profile == "custom":
        use_custom_weights = "1"
    return _page(
        codes=codes,
        start_date=start_date,
        profile=profile,
        top_n=top_n,
        fund_pool=fund_pool,
        preset=preset,
        factor_weights=factor_weights,
        use_custom_weights=_truthy(use_custom_weights),
        portfolio_constraints=portfolio_constraints,
    )


@app.post("/analyze", response_model=None)
def analyze(
    background_tasks: BackgroundTasks,
    codes: str = Form(""),
    start_date: str = Form("2021-01-01"),
    profile: str = Form("balanced"),
    top_n: int = Form(10),
    fund_pool: str = Form("custom"),
    keyword: str = Form(""),
    preset: str = Form(""),
    use_custom_weights: str = Form(""),
    weight_annual_return: float | None = Form(None),
    weight_sharpe: float | None = Form(None),
    weight_max_drawdown: float | None = Form(None),
    weight_calmar: float | None = Form(None),
    weight_annual_volatility: float | None = Form(None),
    weight_rolling_positive_ratio: float | None = Form(None),
    portfolio_objective: str = Form("balanced"),
    portfolio_min_funds: int = Form(3),
    portfolio_max_funds: int = Form(8),
    max_position_weight: float = Form(0.35),
    max_type_weight: float = Form(0.65),
    max_pair_correlation: float = Form(0.9),
    portfolio_max_drawdown: float = Form(-0.45),
    portfolio_min_sharpe: float = Form(0.0),
    rebalance_days: int = Form(63),
    max_turnover: float = Form(0.6),
    transaction_cost_bps: float = Form(0.0),
) -> HTMLResponse | RedirectResponse:
    normalized_codes = _resolve_codes(codes, fund_pool)
    search_rows = _search_rows(keyword)
    use_custom = _truthy(use_custom_weights) or profile == "custom"
    factor_weights = _factor_weights_from_values(
        profile,
        weight_annual_return,
        weight_sharpe,
        weight_max_drawdown,
        weight_calmar,
        weight_annual_volatility,
        weight_rolling_positive_ratio,
    )
    portfolio_constraints = normalize_portfolio_constraints(
        objective=portfolio_objective,
        min_funds=portfolio_min_funds,
        max_funds=portfolio_max_funds,
        max_position_weight=max_position_weight,
        max_type_weight=max_type_weight,
        max_pair_correlation=max_pair_correlation,
        max_drawdown_floor=portfolio_max_drawdown,
        min_sharpe=portfolio_min_sharpe,
        rebalance_days=rebalance_days,
        max_turnover=max_turnover,
        transaction_cost_bps=transaction_cost_bps,
    )

    if len(normalized_codes) < 2:
        return HTMLResponse(
            _page(
                codes=" ".join(normalized_codes) or codes,
                start_date=start_date,
                profile=profile,
                top_n=top_n,
                fund_pool=fund_pool,
                keyword=keyword,
                preset=preset,
                search_rows=search_rows,
                factor_weights=factor_weights,
                use_custom_weights=use_custom,
                portfolio_constraints=portfolio_constraints,
                error="至少输入 2 只基金代码，排名才有比较意义。",
            )
        )
    if profile not in DEFAULT_PROFILES and not use_custom:
        return HTMLResponse(
            _page(
                codes=" ".join(normalized_codes),
                start_date=start_date,
                profile="balanced",
                top_n=top_n,
                fund_pool=fund_pool,
                keyword=keyword,
                preset=preset,
                search_rows=search_rows,
                factor_weights=factor_weights,
                use_custom_weights=use_custom,
                portfolio_constraints=portfolio_constraints,
                error=f"未知投资者画像: {profile}",
            )
        )

    run_slug = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    reports_dir = WEB_REPORTS_DIR / "runs" / run_slug
    processed_dir = WEB_PROCESSED_DIR / "runs" / run_slug
    report_path = reports_dir / "fund_analysis_report.md"
    run_id = FundDatabase().record_analysis(
        normalized_codes,
        start_date,
        profile,
        top_n,
        report_path,
        reports_dir=reports_dir,
        processed_dir=processed_dir,
        status="running",
        portfolio_constraints=portfolio_constraints.to_dict(),
        factor_weights=factor_weights if use_custom else {},
    )
    background_tasks.add_task(
        _run_analysis_job,
        run_id,
        normalized_codes,
        start_date,
        profile,
        top_n,
        reports_dir,
        processed_dir,
        portfolio_constraints,
        factor_weights if use_custom else None,
    )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


def _run_analysis_job(
    run_id: int,
    normalized_codes: list[str],
    start_date: str,
    profile: str,
    top_n: int,
    reports_dir: Path,
    processed_dir: Path,
    portfolio_constraints: PortfolioConstraints,
    custom_weights: dict[str, float] | None = None,
) -> None:
    db = FundDatabase()
    raw_dir = WEB_RAW_DIR / "runs" / str(run_id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    nav_path = raw_dir / "fund_nav.csv"
    metadata_path = raw_dir / "fund_metadata.csv"

    try:
        _fetch_funds(normalized_codes, start_date, nav_path, metadata_path)
        result = run_pipeline(
            input_path=nav_path,
            metadata_path=metadata_path,
            profile=profile,
            top_n=top_n,
            reports_dir=reports_dir,
            processed_dir=processed_dir,
            portfolio_constraints=portfolio_constraints,
            custom_weights=custom_weights,
        )
        db.update_analysis_status(
            run_id,
            "success",
            report_path=result.report_path,
            reports_dir=result.report_path.parent,
            processed_dir=result.metrics_path.parent,
        )
    except Exception as exc:
        db.update_analysis_status(run_id, "failed", error_message=str(exc))


@app.get("/runs/{run_id}/status")
def run_status(run_id: int) -> dict[str, object]:
    run = FundDatabase().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {
        "id": run_id,
        "status": run.get("status", "success"),
        "error_message": run.get("error_message", ""),
        "completed_at": run.get("completed_at", ""),
        "url": f"/runs/{run_id}",
    }


@app.get("/search", response_class=HTMLResponse)
def search(
    keyword: str = "",
    codes: str = "000001 000003 000011 000021 000031",
    start_date: str = "2021-01-01",
    profile: str = "balanced",
    top_n: int = 10,
    fund_pool: str = "custom",
    preset: str = "",
    use_custom_weights: str = "",
    weight_annual_return: float | None = None,
    weight_sharpe: float | None = None,
    weight_max_drawdown: float | None = None,
    weight_calmar: float | None = None,
    weight_annual_volatility: float | None = None,
    weight_rolling_positive_ratio: float | None = None,
    portfolio_objective: str = "balanced",
    portfolio_min_funds: int = 3,
    portfolio_max_funds: int = 8,
    max_position_weight: float = 0.35,
    max_type_weight: float = 0.65,
    max_pair_correlation: float = 0.9,
    portfolio_max_drawdown: float = -0.45,
    portfolio_min_sharpe: float = 0.0,
    rebalance_days: int = 63,
    max_turnover: float = 0.6,
    transaction_cost_bps: float = 0.0,
) -> str:
    factor_weights = _factor_weights_from_values(
        profile,
        weight_annual_return,
        weight_sharpe,
        weight_max_drawdown,
        weight_calmar,
        weight_annual_volatility,
        weight_rolling_positive_ratio,
    )
    portfolio_constraints = normalize_portfolio_constraints(
        objective=portfolio_objective,
        min_funds=portfolio_min_funds,
        max_funds=portfolio_max_funds,
        max_position_weight=max_position_weight,
        max_type_weight=max_type_weight,
        max_pair_correlation=max_pair_correlation,
        max_drawdown_floor=portfolio_max_drawdown,
        min_sharpe=portfolio_min_sharpe,
        rebalance_days=rebalance_days,
        max_turnover=max_turnover,
        transaction_cost_bps=transaction_cost_bps,
    )
    return _page(
        codes=codes,
        start_date=start_date,
        profile=profile,
        top_n=top_n,
        fund_pool=fund_pool,
        preset=preset,
        keyword=keyword,
        search_rows=_search_rows(keyword),
        factor_weights=factor_weights,
        use_custom_weights=_truthy(use_custom_weights) or profile == "custom",
        portfolio_constraints=portfolio_constraints,
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


@app.post("/presets/save", response_model=None)
def save_preset(
    preset_name: str = Form(...),
    codes: str = Form(""),
    start_date: str = Form("2021-01-01"),
    profile: str = Form("balanced"),
    top_n: int = Form(10),
    fund_pool: str = Form("custom"),
    use_custom_weights: str = Form(""),
    weight_annual_return: float | None = Form(None),
    weight_sharpe: float | None = Form(None),
    weight_max_drawdown: float | None = Form(None),
    weight_calmar: float | None = Form(None),
    weight_annual_volatility: float | None = Form(None),
    weight_rolling_positive_ratio: float | None = Form(None),
    portfolio_objective: str = Form("balanced"),
    portfolio_min_funds: int = Form(3),
    portfolio_max_funds: int = Form(8),
    max_position_weight: float = Form(0.35),
    max_type_weight: float = Form(0.65),
    max_pair_correlation: float = Form(0.9),
    portfolio_max_drawdown: float = Form(-0.45),
    portfolio_min_sharpe: float = Form(0.0),
    rebalance_days: int = Form(63),
    max_turnover: float = Form(0.6),
    transaction_cost_bps: float = Form(0.0),
) -> HTMLResponse | RedirectResponse:
    name = preset_name.strip()
    if not name:
        return HTMLResponse(_page(error="方案名称不能为空。"))
    constraints = normalize_portfolio_constraints(
        objective=portfolio_objective,
        min_funds=portfolio_min_funds,
        max_funds=portfolio_max_funds,
        max_position_weight=max_position_weight,
        max_type_weight=max_type_weight,
        max_pair_correlation=max_pair_correlation,
        max_drawdown_floor=portfolio_max_drawdown,
        min_sharpe=portfolio_min_sharpe,
        rebalance_days=rebalance_days,
        max_turnover=max_turnover,
        transaction_cost_bps=transaction_cost_bps,
    )
    factor_weights = _factor_weights_from_values(
        profile,
        weight_annual_return,
        weight_sharpe,
        weight_max_drawdown,
        weight_calmar,
        weight_annual_volatility,
        weight_rolling_positive_ratio,
    )
    FundDatabase().save_preset(
        name,
        profile,
        factor_weights if _truthy(use_custom_weights) else _normalize_factor_weights(DEFAULT_PROFILES.get(profile), profile),
        constraints.to_dict(),
    )
    return RedirectResponse(
        url="/?" + _settings_query(
            codes=codes,
            start_date=start_date,
            profile=profile,
            top_n=top_n,
            fund_pool=fund_pool,
            preset=name,
            factor_weights=factor_weights,
            use_custom_weights=True,
            portfolio_constraints=constraints,
        ),
        status_code=303,
    )


@app.post("/presets/delete", response_model=None)
def delete_preset(preset_name: str = Form(...)) -> RedirectResponse:
    FundDatabase().delete_preset(preset_name.strip())
    return RedirectResponse(url="/", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int) -> str:
    run = FundDatabase().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    status = str(run.get("status", "success"))
    if status == "running":
        portfolio_constraints = normalize_portfolio_constraints(run.get("portfolio_constraints"))
        return _page(
            codes=" ".join(run["codes"]),
            start_date=str(run["start_date"]),
            profile=str(run["profile"]),
            top_n=int(run["top_n"]),
            run_id=run_id,
            run_status=status,
            data_stats=FundDatabase().nav_stats(run["codes"]),
            factor_weights=_normalize_factor_weights(run.get("factor_weights"), str(run["profile"])),
            use_custom_weights=bool(run.get("factor_weights")),
            portfolio_constraints=portfolio_constraints,
        )
    if status == "failed":
        portfolio_constraints = normalize_portfolio_constraints(run.get("portfolio_constraints"))
        return _page(
            codes=" ".join(run["codes"]),
            start_date=str(run["start_date"]),
            profile=str(run["profile"]),
            top_n=int(run["top_n"]),
            run_id=run_id,
            run_status=status,
            data_stats=FundDatabase().nav_stats(run["codes"]),
            factor_weights=_normalize_factor_weights(run.get("factor_weights"), str(run["profile"])),
            use_custom_weights=bool(run.get("factor_weights")),
            portfolio_constraints=portfolio_constraints,
            error=f"分析失败：{run.get('error_message', '')}",
        )

    report_path = Path(str(run["report_path"]))
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else "报告文件不存在。"
    ranking_path = Path(str(run["reports_dir"])) / f"ranking_{run['profile']}.csv"
    rows = _read_csv(ranking_path).head(int(run["top_n"])).to_dict(orient="records") if ranking_path.exists() else []
    ml_path = Path(str(run["reports_dir"])) / f"ranking_ml_{run['profile']}.csv"
    ml_rows = _read_csv(ml_path).head(int(run["top_n"])).to_dict(orient="records") if ml_path.exists() else []
    adaptive_path = Path(str(run["reports_dir"])) / f"ranking_adaptive_{run['profile']}.csv"
    adaptive_rows = _read_csv(adaptive_path).head(int(run["top_n"])).to_dict(orient="records") if adaptive_path.exists() else []
    comparison_path = Path(str(run["reports_dir"])) / f"ranking_comparison_{run['profile']}.csv"
    comparison_rows = _read_csv(comparison_path).head(int(run["top_n"])).to_dict(orient="records") if comparison_path.exists() else []
    model_evaluation_path = Path(str(run["reports_dir"])) / "ml_evaluation.csv"
    model_evaluation_rows = _read_csv(model_evaluation_path).tail(6).to_dict(orient="records") if model_evaluation_path.exists() else []
    data_quality_path = Path(str(run["reports_dir"])) / "data_quality_diagnostics.csv"
    data_quality_rows = _read_csv(data_quality_path).head(8).to_dict(orient="records") if data_quality_path.exists() else []
    strategy_benchmark_path = Path(str(run["reports_dir"])) / "strategy_benchmark.csv"
    strategy_benchmark_rows = _read_csv(strategy_benchmark_path).to_dict(orient="records") if strategy_benchmark_path.exists() else []
    adaptive_weights_path = Path(str(run["reports_dir"])) / "adaptive_factor_weights.csv"
    adaptive_weight_rows = _adaptive_weight_preview_rows(_read_csv(adaptive_weights_path), adaptive_rows) if adaptive_weights_path.exists() else []
    lime_path = Path(str(run["reports_dir"])) / "lime_explanations.csv"
    lime_rows = _lime_preview_rows(_read_csv(lime_path), int(run["top_n"])) if lime_path.exists() else []
    portfolio_path = Path(str(run["reports_dir"])) / "portfolio_summary.csv"
    portfolio_rows = _read_csv(portfolio_path).to_dict(orient="records") if portfolio_path.exists() else []
    recommendation_path = Path(str(run["reports_dir"])) / "portfolio_recommendations.csv"
    recommendation_rows = _read_csv(recommendation_path).to_dict(orient="records") if recommendation_path.exists() else []
    return _page(
        codes=" ".join(run["codes"]),
        start_date=str(run["start_date"]),
        profile=str(run["profile"]),
        top_n=int(run["top_n"]),
        rows=rows,
        ml_rows=ml_rows,
        adaptive_rows=adaptive_rows,
        adaptive_weight_rows=adaptive_weight_rows,
        comparison_rows=comparison_rows,
        model_evaluation_rows=model_evaluation_rows,
        data_quality_rows=data_quality_rows,
        strategy_benchmark_rows=strategy_benchmark_rows,
        lime_rows=lime_rows,
        portfolio_rows=portfolio_rows,
        recommendation_rows=recommendation_rows,
        report_text=report_text,
        run_id=run_id,
        run_status=status,
        data_stats=FundDatabase().nav_stats(run["codes"]),
        factor_weights=_normalize_factor_weights(run.get("factor_weights"), str(run["profile"])),
        use_custom_weights=bool(run.get("factor_weights")),
        portfolio_constraints=normalize_portfolio_constraints(run.get("portfolio_constraints")),
        success=True,
    )


@app.get("/runs/{run_id}/funds/{fund}", response_class=HTMLResponse)
def fund_detail(run_id: int, fund: str) -> str:
    run = FundDatabase().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if str(run.get("status", "success")) != "success":
        raise HTTPException(status_code=409, detail="Run is not complete.")

    reports_dir = Path(str(run["reports_dir"]))
    processed_dir = Path(str(run["processed_dir"]))
    profile = str(run["profile"])
    selected = _normalize_fund_key(fund)

    metrics = _read_csv(processed_dir / "fund_metrics.csv")
    ranking = _read_csv(reports_dir / f"ranking_{profile}.csv")
    adaptive = _read_csv(reports_dir / f"ranking_adaptive_{profile}.csv")
    ml = _read_csv(reports_dir / f"ranking_ml_{profile}.csv")
    peers = _read_csv(reports_dir / f"peer_comparison_{profile}.csv")
    adaptive_weights = _read_csv(reports_dir / "adaptive_factor_weights.csv")
    lime = _read_csv(reports_dir / "lime_explanations.csv")
    contributions = _read_csv(reports_dir / "factor_contributions.csv")

    base_row = _find_fund_row(ranking if not ranking.empty else metrics, selected)
    if base_row is None:
        raise HTTPException(status_code=404, detail="Fund not found in this run.")
    fund_name = str(base_row.get("fund_name", ""))
    title = f"{_display_code(selected)} {fund_name}".strip()

    body = "\n".join(
        [
            f'<p><a href="/runs/{run_id}">返回本次分析</a></p>',
            f"<h1>{html.escape(title)}</h1>",
            _fund_metric_cards(base_row),
            _fund_rank_summary(base_row, _find_fund_row(adaptive, selected), _find_fund_row(ml, selected), _find_fund_row(peers, selected)),
            _fund_dynamic_weight_section(adaptive_weights, selected),
            _fund_lime_section(lime, selected),
            _fund_contribution_section(contributions, selected),
            _fund_peer_section(peers, selected),
        ]
    )
    return _standalone_page(f"{title} - 基金详情", body)


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
    _ensure_port_available(args.host, args.port)
    uvicorn.run("fund_ranking_system.web:app", host=args.host, port=args.port, reload=False)


def _ensure_port_available(host: str, port: int) -> None:
    bind_host = "" if host in {"0.0.0.0", "::"} else host
    family = socket.AF_INET6 if ":" in host and host != "0.0.0.0" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_host, port))
        except OSError as exc:
            raise SystemExit(
                f"端口 {port} 已被占用，Web 服务没有启动。请关闭占用进程，"
                f"或使用 --port 指定其他端口，例如：fund-ranking-web --port {port + 1}"
            ) from exc


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
    nav_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
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


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"fund": str})


def _factor_weights_from_values(
    profile: str,
    annual_return: float | None,
    sharpe: float | None,
    max_drawdown: float | None,
    calmar: float | None,
    annual_volatility: float | None,
    rolling_positive_ratio: float | None,
) -> dict[str, float]:
    values = {
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "annual_volatility": annual_volatility,
        "rolling_positive_ratio": rolling_positive_ratio,
    }
    if all(value is None for value in values.values()):
        return _normalize_factor_weights(DEFAULT_PROFILES.get(profile), profile)
    return _normalize_factor_weights(values, profile)


def _normalize_factor_weights(weights: object, profile: str = "balanced") -> dict[str, float]:
    fallback = DEFAULT_PROFILES.get(profile, DEFAULT_PROFILES["balanced"])
    source = weights if isinstance(weights, dict) and weights else fallback
    normalized = {}
    for metric in SCORE_METRICS:
        try:
            normalized[metric] = max(float(source.get(metric, fallback.get(metric, 0.0))), 0.0)
        except (TypeError, ValueError, AttributeError):
            normalized[metric] = max(float(fallback.get(metric, 0.0)), 0.0)
    total = sum(normalized.values())
    if total <= 0:
        normalized = {metric: max(float(fallback.get(metric, 0.0)), 0.0) for metric in SCORE_METRICS}
        total = sum(normalized.values())
    if total <= 0:
        return {metric: 1 / len(SCORE_METRICS) for metric in SCORE_METRICS}
    return {metric: value / total for metric, value in normalized.items()}


def _factor_weight_controls(weights: dict[str, float]) -> str:
    return "\n".join(
        f"""<label>{html.escape(FACTOR_LABELS.get(metric, metric))}
	          <input name="weight_{metric}" type="number" min="0" max="1" step="0.01" value="{weights.get(metric, 0.0):.2f}">
	        </label>"""
        for metric in SCORE_METRICS
    )


def _factor_weight_hidden_inputs(weights: dict[str, float]) -> str:
    return "\n".join(
        f'<input type="hidden" name="weight_{metric}" value="{weights.get(metric, 0.0):.4f}">'
        for metric in SCORE_METRICS
    )


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _settings_query(
    *,
    codes: str,
    start_date: str,
    profile: str,
    top_n: int,
    fund_pool: str,
    preset: str,
    factor_weights: dict[str, float],
    use_custom_weights: bool,
    portfolio_constraints: PortfolioConstraints,
) -> str:
    params: dict[str, object] = {
        "codes": codes,
        "start_date": start_date,
        "profile": profile,
        "top_n": top_n,
        "fund_pool": fund_pool,
        "preset": preset,
        "use_custom_weights": "1" if use_custom_weights else "",
        "portfolio_objective": portfolio_constraints.objective,
        "portfolio_min_funds": portfolio_constraints.min_funds,
        "portfolio_max_funds": portfolio_constraints.max_funds,
        "max_position_weight": f"{portfolio_constraints.max_position_weight:.4f}",
        "max_type_weight": f"{portfolio_constraints.max_type_weight:.4f}",
        "max_pair_correlation": f"{portfolio_constraints.max_pair_correlation:.4f}",
        "portfolio_max_drawdown": f"{portfolio_constraints.max_drawdown_floor:.4f}",
        "portfolio_min_sharpe": f"{portfolio_constraints.min_sharpe:.4f}",
        "rebalance_days": portfolio_constraints.rebalance_days,
        "max_turnover": f"{portfolio_constraints.max_turnover:.4f}",
        "transaction_cost_bps": f"{portfolio_constraints.transaction_cost_bps:.2f}",
    }
    for metric in SCORE_METRICS:
        params[f"weight_{metric}"] = f"{factor_weights.get(metric, 0.0):.4f}"
    return urlencode(params)


def _normalize_fund_key(value: object) -> str:
    text = str(value).strip()
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def _display_code(value: object) -> str:
    return _normalize_fund_key(value)


def _find_fund_row(frame: pd.DataFrame, fund: str) -> pd.Series | None:
    if frame.empty:
        return None
    selected = _normalize_fund_key(fund)
    if "fund" in frame.columns:
        keys = frame["fund"].map(_normalize_fund_key)
        matched = frame[keys == selected]
        if not matched.empty:
            return matched.iloc[0]
    index_keys = pd.Series(frame.index, index=frame.index).map(_normalize_fund_key)
    if selected in set(index_keys):
        return frame.loc[index_keys[index_keys == selected].index[0]]
    return None


def _page(
    codes: str = "000001 000003 000011 000021 000031",
    start_date: str = "2021-01-01",
    profile: str = "balanced",
    top_n: int = 10,
    fund_pool: str = "custom",
    preset: str = "",
    keyword: str = "",
    rows: list[dict[str, object]] | None = None,
    ml_rows: list[dict[str, object]] | None = None,
    adaptive_rows: list[dict[str, object]] | None = None,
    adaptive_weight_rows: list[dict[str, object]] | None = None,
    comparison_rows: list[dict[str, object]] | None = None,
    lime_rows: list[dict[str, object]] | None = None,
    model_evaluation_rows: list[dict[str, object]] | None = None,
    data_quality_rows: list[dict[str, object]] | None = None,
    strategy_benchmark_rows: list[dict[str, object]] | None = None,
    portfolio_rows: list[dict[str, object]] | None = None,
    recommendation_rows: list[dict[str, object]] | None = None,
    search_rows: list[dict[str, str]] | None = None,
    report_text: str = "",
    cache_message: str = "",
    run_id: int | None = None,
    run_status: str = "",
    data_stats: list[dict[str, object]] | None = None,
    factor_weights: dict[str, float] | None = None,
    use_custom_weights: bool = False,
    portfolio_constraints: PortfolioConstraints | dict[str, object] | None = None,
    success: bool = False,
    error: str = "",
) -> str:
    portfolio_constraints = normalize_portfolio_constraints(portfolio_constraints)
    factor_weights = _normalize_factor_weights(factor_weights, profile)
    profile_names = sorted(set(DEFAULT_PROFILES) | {"custom"})
    profile_options = "\n".join(
        f'<option value="{name}" {"selected" if name == profile else ""}>{name}</option>'
        for name in profile_names
    )
    portfolio_objective_options = "\n".join(
        f'<option value="{key}" {"selected" if key == portfolio_constraints.objective else ""}>{label}</option>'
        for key, label in PORTFOLIO_OBJECTIVES.items()
    )
    db = FundDatabase()
    saved_pools = db.list_pools()
    saved_presets = db.list_presets()
    pool_options = "\n".join(
        f'<option value="{key}" {"selected" if key == fund_pool else ""}>{label}</option>'
        for key, (label, _) in FUND_POOLS.items()
    )
    pool_options += "\n" + "\n".join(
        f'<option value="saved:{html.escape(str(pool["name"]))}" {"selected" if fund_pool == "saved:" + str(pool["name"]) else ""}>我的基金池：{html.escape(str(pool["name"]))}</option>'
        for pool in saved_pools
    )
    preset_options = '<option value="">不使用保存方案</option>' + "\n" + "\n".join(
        f'<option value="{html.escape(str(item["name"]))}" {"selected" if preset == str(item["name"]) else ""}>{html.escape(str(item["name"]))}</option>'
        for item in saved_presets
    )
    custom_checked = "checked" if use_custom_weights else ""
    factor_controls = _factor_weight_controls(factor_weights)
    table = _ranking_table(rows or [], run_id)
    adaptive_table = _adaptive_ranking_table(adaptive_rows or [], run_id)
    adaptive_weight_table = _adaptive_weight_table(adaptive_weight_rows or [])
    ml_table = _ml_ranking_table(ml_rows or [], run_id)
    comparison_table = _ranking_comparison_table(comparison_rows or [], run_id)
    model_evaluation_table = _model_evaluation_table(model_evaluation_rows or [])
    data_quality_table = _data_quality_diagnostics_table(data_quality_rows or [])
    strategy_benchmark_table = _strategy_benchmark_table(strategy_benchmark_rows or [])
    portfolio_table = _portfolio_summary_table(portfolio_rows or [])
    recommendation_table = _portfolio_recommendation_table(recommendation_rows or [])
    lime_table = _lime_explanation_table(lime_rows or [], run_id)
    search_section = _search_section(search_rows or [])
    history = _history_section(FundDatabase().recent_runs())
    data_status = _data_status_section(data_stats or [])
    pool_manager = _pool_manager_section(saved_pools)
    preset_manager = _preset_manager_section(saved_presets)
    downloads = _download_section(profile, run_id) if success else ""
    status_panel = _run_status_section(run_status)
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    cache_html = f'<div class="cache-status">{html.escape(cache_message)}</div>' if cache_message else ""
    refresh_tag = '<meta http-equiv="refresh" content="5">' if run_status == "running" else ""
    figures = _figure_section(profile, run_id) if success else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  {refresh_tag}
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
	    .advanced-panel {{
      grid-column: 1 / -1;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      overflow: hidden;
    }}
    .advanced-panel summary {{
      cursor: pointer;
      padding: 12px 14px;
      font-weight: 700;
      color: var(--text);
      list-style-position: inside;
    }}
    .advanced-panel .panel-grid {{
      display: grid;
      gap: 12px;
      padding: 0 12px 12px;
    }}
	    .constraint-panel .panel-grid {{
      grid-template-columns: repeat(5, minmax(140px, 1fr));
	    }}
	    .weight-panel .panel-grid {{
	      display: grid;
	      grid-template-columns: repeat(4, minmax(140px, 1fr));
	    }}
	    .checkline {{
	      display: flex;
	      gap: 8px;
	      align-items: center;
	      color: var(--text);
	      font-weight: 600;
	    }}
	    .checkline input {{ height: 18px; width: 18px; }}
	    .preset-actions {{
	      display: grid;
	      grid-template-columns: minmax(160px, 1fr) auto;
	      gap: 10px;
	      align-items: end;
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
    .run-status {{
      margin: 16px 0;
      padding: 14px 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
      line-height: 1.6;
    }}
    .run-status strong {{ display: block; margin-bottom: 4px; }}
    .run-status.running {{ border-color: #b9dce6; background: #eef8fb; color: var(--accent); }}
    .run-status.success {{ border-color: #abefc6; background: #ecfdf3; color: var(--ok); }}
    .run-status.failed {{ border-color: #fecdca; background: #fff1f0; color: var(--error); }}
    .status-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 600;
      border: 1px solid var(--line);
      background: #eef2f6;
      white-space: nowrap;
    }}
    .status-badge.running {{ color: var(--accent); border-color: #b9dce6; background: #eef8fb; }}
    .status-badge.success {{ color: var(--ok); border-color: #abefc6; background: #ecfdf3; }}
    .status-badge.failed {{ color: var(--error); border-color: #fecdca; background: #fff1f0; }}
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
    .report-body h3 {{ border: 0; padding: 0; font-size: 18px; margin: 20px 0 8px; }}
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
    .toolbar a, .download-group a {{
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
    .download-primary {{
      padding-bottom: 8px;
    }}
    .download-groups {{
      display: grid;
      grid-template-columns: repeat(2, minmax(280px, 1fr));
      gap: 12px;
      padding: 0 16px 16px;
    }}
    .download-group {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      overflow: hidden;
    }}
    .download-group summary {{
      cursor: pointer;
      padding: 12px 14px;
      font-weight: 700;
      color: var(--text);
      list-style-position: inside;
    }}
    .download-group .toolbar {{
      padding: 0 12px 12px;
      gap: 8px;
    }}
    .download-hint {{
      margin: 0;
      padding: 0 16px 12px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .mini-form {{
      grid-template-columns: minmax(180px, 240px) minmax(280px, 1fr) auto;
      margin: 16px;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    img {{ width: 100%; background: #fff; border: 1px solid var(--line); border-radius: 6px; }}
    .section-lede {{
      margin: 0;
      padding: 12px 18px 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }}
    .chart-viewer {{
      display: grid;
      grid-template-columns: minmax(220px, 300px) minmax(0, 1fr);
      gap: 16px;
      padding: 16px;
      align-items: start;
    }}
    .chart-picker {{
      display: grid;
      gap: 8px;
      max-height: 720px;
      overflow-y: auto;
      padding-right: 4px;
    }}
    .chart-option {{
      width: 100%;
      min-height: 56px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      color: var(--text);
      text-align: left;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .chart-option:hover {{
      border-color: #9eb7c2;
      background: #f2f6f8;
    }}
    .chart-option.is-active {{
      border-color: var(--accent);
      background: #e9f3f5;
      box-shadow: inset 4px 0 0 var(--accent);
    }}
    .chart-option-group {{
      display: block;
      margin-bottom: 3px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .chart-stage {{
      margin: 0;
      background: #f6f7f9;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
    }}
    .chart-stage a {{
      display: block;
      background: #f6f7f9;
    }}
    .chart-stage img {{
      min-height: 560px;
      max-height: 78vh;
      object-fit: contain;
      box-sizing: border-box;
      padding: 10px;
      border: 0;
      border-radius: 0;
      display: block;
      background: #f6f7f9;
    }}
    .chart-caption {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-top: 1px solid var(--line);
      background: #fff;
    }}
    .chart-caption-title {{
      display: flex;
      flex-direction: column;
      gap: 3px;
    }}
    .chart-caption strong {{
      font-size: 16px;
    }}
    .chart-caption span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .chart-open {{
      flex: 0 0 auto;
      color: var(--accent);
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
    }}
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
	      .constraint-panel .panel-grid {{ grid-template-columns: 1fr; }}
	      .weight-panel .panel-grid {{ grid-template-columns: 1fr; }}
	      .preset-actions {{ grid-template-columns: 1fr; }}
	      .chart-viewer {{ grid-template-columns: 1fr; }}
	      .chart-picker {{ grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: none; padding-right: 0; }}
	      .chart-stage img {{ min-height: 360px; max-height: 70vh; }}
	      .download-groups {{ grid-template-columns: 1fr; }}
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
	      <label>分析方案
	        <select name="preset" id="preset-select">{preset_options}</select>
	      </label>
	      <details class="advanced-panel weight-panel">
	        <summary>评分权重</summary>
	        <div class="panel-grid">
	          <label class="checkline"><input type="checkbox" name="use_custom_weights" value="1" {custom_checked}>使用自定义评分权重</label>
	          {factor_controls}
	          <div class="preset-actions">
	            <label>保存方案名称
	              <input name="preset_name" value="{html.escape(preset)}" placeholder="例如：低回撤观察方案">
	            </label>
	            <button type="submit" class="secondary" formaction="/presets/save" formmethod="post">保存方案</button>
	          </div>
	        </div>
	      </details>
	      <details class="advanced-panel constraint-panel">
        <summary>组合约束</summary>
        <div class="panel-grid">
          <label>组合目标
            <select name="portfolio_objective">{portfolio_objective_options}</select>
          </label>
          <label>最少持仓
            <input name="portfolio_min_funds" type="number" min="1" max="50" value="{portfolio_constraints.min_funds}">
          </label>
          <label>最多持仓
            <input name="portfolio_max_funds" type="number" min="1" max="80" value="{portfolio_constraints.max_funds}">
          </label>
          <label>单只上限
            <input name="max_position_weight" type="number" min="0.05" max="1" step="0.01" value="{portfolio_constraints.max_position_weight:.2f}">
          </label>
          <label>同类占比上限
            <input name="max_type_weight" type="number" min="0.10" max="1" step="0.01" value="{portfolio_constraints.max_type_weight:.2f}">
          </label>
          <label>最高相关阈值
            <input name="max_pair_correlation" type="number" min="0" max="1" step="0.01" value="{portfolio_constraints.max_pair_correlation:.2f}">
          </label>
          <label>回撤下限
            <input name="portfolio_max_drawdown" type="number" min="-0.95" max="0" step="0.01" value="{portfolio_constraints.max_drawdown_floor:.2f}">
          </label>
          <label>最低 Sharpe
            <input name="portfolio_min_sharpe" type="number" min="-5" max="10" step="0.01" value="{portfolio_constraints.min_sharpe:.2f}">
          </label>
          <label>再平衡天数
            <input name="rebalance_days" type="number" min="21" max="252" step="21" value="{portfolio_constraints.rebalance_days}">
          </label>
          <label>最大换手率
            <input name="max_turnover" type="number" min="0" max="1" step="0.01" value="{portfolio_constraints.max_turnover:.2f}">
          </label>
          <label>交易成本 bps
            <input name="transaction_cost_bps" type="number" min="0" max="500" step="1" value="{portfolio_constraints.transaction_cost_bps:.0f}">
          </label>
        </div>
      </details>
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
	      <input type="hidden" name="preset" value="{html.escape(preset)}">
	      <input type="hidden" name="use_custom_weights" value="{'1' if use_custom_weights else ''}">
	      {_factor_weight_hidden_inputs(factor_weights)}
	      <input type="hidden" name="portfolio_objective" value="{html.escape(portfolio_constraints.objective)}">
      <input type="hidden" name="portfolio_min_funds" value="{portfolio_constraints.min_funds}">
      <input type="hidden" name="portfolio_max_funds" value="{portfolio_constraints.max_funds}">
      <input type="hidden" name="max_position_weight" value="{portfolio_constraints.max_position_weight:.2f}">
      <input type="hidden" name="max_type_weight" value="{portfolio_constraints.max_type_weight:.2f}">
      <input type="hidden" name="max_pair_correlation" value="{portfolio_constraints.max_pair_correlation:.2f}">
      <input type="hidden" name="portfolio_max_drawdown" value="{portfolio_constraints.max_drawdown_floor:.2f}">
      <input type="hidden" name="portfolio_min_sharpe" value="{portfolio_constraints.min_sharpe:.2f}">
      <input type="hidden" name="rebalance_days" value="{portfolio_constraints.rebalance_days}">
      <input type="hidden" name="max_turnover" value="{portfolio_constraints.max_turnover:.2f}">
      <input type="hidden" name="transaction_cost_bps" value="{portfolio_constraints.transaction_cost_bps:.0f}">
      <button type="submit" class="secondary">搜索基金</button>
    </form>
    <div class="loading">正在抓取真实基金净值并生成报告，请稍等几秒...</div>
    {status_panel}
    {error_html}
    {cache_html}
    <div class="notice">本系统仅用于历史表现分析和研究辅助，不构成个性化投资建议、收益承诺或买卖指令。</div>
	    {search_section}
	    {pool_manager}
	    {preset_manager}
	    {data_status}
    {table}
    {adaptive_table}
    {adaptive_weight_table}
	    {ml_table}
	    {comparison_table}
	    {model_evaluation_table}
	    {data_quality_table}
	    {strategy_benchmark_table}
	    {portfolio_table}
    {recommendation_table}
    {lime_table}
    {downloads}
    {figures}
    {_report_section(report_text)}
    {history}
  </main>
  <script>
	    const form = document.getElementById('analysis-form');
	    if (form) {{
	      form.addEventListener('submit', (event) => {{
	        document.body.classList.add('is-loading');
	        const button = event.submitter || form.querySelector('button[type="submit"]');
	        if (button) button.textContent = button.getAttribute('formaction') === '/presets/save' ? '保存中...' : '分析中...';
	      }});
	    }}
	    const presetSelect = document.getElementById('preset-select');
	    if (presetSelect) {{
	      presetSelect.addEventListener('change', () => {{
	        const value = presetSelect.value;
	        const url = new URL(window.location.href);
	        if (value) {{
	          url.searchParams.set('preset', value);
	        }} else {{
	          url.searchParams.delete('preset');
	        }}
	        window.location.href = url.toString();
	      }});
	    }}
	    const chartImage = document.getElementById('chart-main-image');
	    const chartOpenLink = document.getElementById('chart-open-link');
	    const chartOpenText = document.getElementById('chart-open-text');
	    const chartLabel = document.getElementById('chart-main-label');
	    const chartGroup = document.getElementById('chart-main-group');
	    const chartButtons = document.querySelectorAll('.chart-option');
	    if (chartImage && chartOpenLink && chartLabel && chartGroup && chartButtons.length) {{
	      chartButtons.forEach((button) => {{
	        button.addEventListener('click', () => {{
	          const src = button.dataset.chartSrc;
	          const label = button.dataset.chartLabel || '图表';
	          const group = button.dataset.chartGroup || '图表';
	          if (!src) return;
	          chartImage.src = src;
	          chartImage.alt = label;
	          chartOpenLink.href = src;
	          if (chartOpenText) chartOpenText.href = src;
	          chartLabel.textContent = label;
	          chartGroup.textContent = group;
	          chartButtons.forEach((item) => {{
	            item.classList.remove('is-active');
	            item.setAttribute('aria-pressed', 'false');
	          }});
	          button.classList.add('is-active');
	          button.setAttribute('aria-pressed', 'true');
	        }});
	      }});
	    }}
	  </script>
</body>
</html>"""


def _fund_link(row: dict[str, object], run_id: int | None) -> str:
    fund = _normalize_fund_key(row.get("fund", ""))
    label = f"{_display_code(fund)} {row.get('fund_name', '')}".strip()
    safe_label = html.escape(label)
    if run_id is None or not fund:
        return safe_label
    return f'<a href="/runs/{run_id}/funds/{quote(fund)}">{safe_label}</a>'


def _ranking_table(rows: list[dict[str, object]], run_id: int | None = None) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"num\">{row.get('rank', '')}</td>"
        f"<td class=\"fund-cell\">{_fund_link(row, run_id)}</td>"
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


def _adaptive_ranking_table(rows: list[dict[str, object]], run_id: int | None = None) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"num\">{row.get('dynamic_rank', '')}</td>"
        f"<td class=\"fund-cell\">{_fund_link(row, run_id)}</td>"
        f"<td class=\"num\">{float(row.get('dynamic_score', 0)):.2f}</td>"
        f"<td class=\"num\">{_format_optional_number(row.get('base_rank'))}</td>"
        f"<td class=\"num\">{_format_optional_number(row.get('base_score'), digits=2)}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('top_dynamic_factors', '')))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('dynamic_weight_reason', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>动态权重排名</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="num">动态排名</th><th>基金</th><th class="num">动态评分</th><th class="num">原排名</th><th class="num">原评分</th><th>主要动态权重</th><th>调整说明</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _adaptive_weight_preview_rows(
    weight_table: pd.DataFrame,
    adaptive_rows: list[dict[str, object]],
    max_funds: int = 5,
) -> list[dict[str, object]]:
    if weight_table.empty or not adaptive_rows:
        return []
    rows: list[dict[str, object]] = []
    for row in adaptive_rows[:max_funds]:
        fund = str(row.get("fund", ""))
        fund_rows = weight_table[weight_table["fund"].astype(str) == fund]
        if fund_rows.empty:
            continue
        weights = dict(zip(fund_rows["feature"], fund_rows["dynamic_weight"], strict=False))
        first = fund_rows.iloc[0]
        rows.append(
            {
                "fund": fund,
                "fund_name": first.get("fund_name", row.get("fund_name", "")),
                "annual_return": weights.get("annual_return", 0.0),
                "sharpe": weights.get("sharpe", 0.0),
                "max_drawdown": weights.get("max_drawdown", 0.0),
                "calmar": weights.get("calmar", 0.0),
                "annual_volatility": weights.get("annual_volatility", 0.0),
                "rolling_positive_ratio": weights.get("rolling_positive_ratio", 0.0),
            }
        )
    return rows


def _adaptive_weight_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund', '')))} {html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td class=\"num\">{float(row.get('annual_return', 0)):.1%}</td>"
        f"<td class=\"num\">{float(row.get('sharpe', 0)):.1%}</td>"
        f"<td class=\"num\">{float(row.get('max_drawdown', 0)):.1%}</td>"
        f"<td class=\"num\">{float(row.get('calmar', 0)):.1%}</td>"
        f"<td class=\"num\">{float(row.get('annual_volatility', 0)):.1%}</td>"
        f"<td class=\"num\">{float(row.get('rolling_positive_ratio', 0)):.1%}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>基金级动态权重</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金</th><th class="num">年化收益</th><th class="num">Sharpe</th><th class="num">最大回撤</th><th class="num">Calmar</th><th class="num">年化波动</th><th class="num">滚动正收益比例</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _ml_ranking_table(rows: list[dict[str, object]], run_id: int | None = None) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"num\">{row.get('ml_rank', '')}</td>"
        f"<td class=\"fund-cell\">{_fund_link(row, run_id)}</td>"
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


def _ranking_comparison_table(rows: list[dict[str, object]], run_id: int | None = None) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{_fund_link(row, run_id)}</td>"
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


def _model_evaluation_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td class=\"num\">{_format_metric(row.get('period_id'), digits=0)}</td>"
        f"<td>{html.escape(str(row.get('hold_start', '')))} ~ {html.escape(str(row.get('hold_end', '')))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('base_rank_ic'), digits=3)}</td>"
        f"<td class=\"num\">{_format_metric(row.get('ml_rank_ic'), digits=3)}</td>"
        f"<td class=\"num\">{_format_signed_percent(row.get('hit_rate_uplift'))}</td>"
        f"<td class=\"num\">{_format_signed_percent(row.get('ml_excess_return_vs_base'))}</td>"
        f"<td>{html.escape(str(row.get('evaluation_label', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>模型效果评估</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="num">窗口</th><th>持有期</th><th class="num">Base IC</th><th class="num">ML IC</th><th class="num">命中率提升</th><th class="num">收益提升</th><th>结论</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _data_quality_diagnostics_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund', '')))} {html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td>{html.escape(str(row.get('fund_type', '')))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('completeness'))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('missing_days'), digits=0)}</td>"
        f"<td class=\"num\">{_format_metric(row.get('nav_anomaly_count'), digits=0)}</td>"
        f"<td class=\"num\">{_format_metric(row.get('quality_score'), digits=1)}</td>"
        f"<td>{html.escape(str(row.get('quality_level', '')))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('recommendation', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>数据质量诊断</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金</th><th>类型</th><th class="num">完整率</th><th class="num">缺失天数</th><th class="num">异常跳变</th><th class="num">质量分</th><th>等级</th><th>建议</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _strategy_benchmark_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('scope', '')))}</td>"
        f"<td>{html.escape(str(row.get('strategy', '')))}</td>"
        f"<td>{html.escape(str(row.get('baseline_strategy', '')))}</td>"
        f"<td class=\"num\">{_format_signed_percent(row.get('excess_annual_return'))}</td>"
        f"<td class=\"num\">{_format_optional_number(row.get('excess_sharpe'), digits=2)}</td>"
        f"<td class=\"num\">{_format_signed_percent(row.get('drawdown_improvement'))}</td>"
        f"<td>{html.escape(str(row.get('risk_adjusted_label', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>策略回测基准</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>模块</th><th>策略</th><th>基准</th><th class="num">年化收益差</th><th class="num">Sharpe差</th><th class="num">回撤改善</th><th>结论</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _portfolio_summary_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('portfolio', '')))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('fund_count'), digits=0)}</td>"
        f"<td class=\"num\">{_format_percent(row.get('annual_return'))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('annual_volatility'))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('max_drawdown'))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('sharpe'), digits=2)}</td>"
        f"<td class=\"num\">{_format_percent(row.get('win_rate'))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>组合构建摘要</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>组合</th><th class="num">基金数</th><th class="num">年化收益</th><th class="num">年化波动</th><th class="num">最大回撤</th><th class="num">Sharpe</th><th class="num">胜率</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _portfolio_recommendation_table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{html.escape(str(row.get('fund', '')))} {html.escape(str(row.get('fund_name', '')))}</td>"
        f"<td>{html.escape(str(row.get('fund_type', '')))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('weight'))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('selection_reason', '')))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('risk_note', '')))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('diversification_note', '')))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>组合建议说明</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金</th><th>类型</th><th class="num">权重</th><th>入选原因</th><th>风险提示</th><th>分散化说明</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _lime_preview_rows(explanations: pd.DataFrame, top_n: int) -> list[dict[str, object]]:
    if explanations.empty or "fund" not in explanations.columns:
        return []

    rows: list[dict[str, object]] = []
    for fund in explanations["fund"].drop_duplicates().head(top_n):
        fund_rows = explanations[explanations["fund"] == fund].copy()
        fund_rows["local_weight"] = pd.to_numeric(fund_rows["local_weight"], errors="coerce").fillna(0.0)
        fund_rows["abs_weight"] = pd.to_numeric(fund_rows["abs_weight"], errors="coerce").fillna(
            fund_rows["local_weight"].abs()
        )
        fund_rows = fund_rows.sort_values("abs_weight", ascending=False)
        first = fund_rows.iloc[0]
        positive = fund_rows[fund_rows["local_weight"] > 0].head(2)
        negative = fund_rows[fund_rows["local_weight"] < 0].head(2)
        rows.append(
            {
                "fund": fund,
                "fund_name": first.get("fund_name", ""),
                "positive_factors": _lime_factor_list(positive),
                "negative_factors": _lime_factor_list(negative),
                "surrogate_r2": first.get("surrogate_r2", 0.0),
                "black_box_score": first.get("black_box_score", 0.0),
            }
        )
    return rows


def _lime_factor_list(rows: pd.DataFrame) -> str:
    if rows.empty:
        return "无明显因子"
    parts = []
    for _, row in rows.iterrows():
        feature = str(row.get("feature", ""))
        weight = float(row.get("local_weight", 0.0))
        parts.append(f"{feature} ({weight:+.2f})")
    return "；".join(parts)


def _lime_explanation_table(rows: list[dict[str, object]], run_id: int | None = None) -> str:
    if not rows:
        return ""

    body = "\n".join(
        "<tr>"
        f"<td class=\"fund-cell\">{_fund_link(row, run_id)}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('positive_factors', '')))}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('negative_factors', '')))}</td>"
        f"<td class=\"num\">{float(row.get('surrogate_r2', 0)):.3f}</td>"
        f"<td class=\"num\">{float(row.get('black_box_score', 0)):.2f}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
    <section class="section">
      <h2>LIME 局部解释预览</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>基金</th><th>局部正向因子</th><th>局部负向因子</th><th class="num">代理R²</th><th class="num">评分</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _fund_metric_cards(row: pd.Series) -> str:
    items = [
        ("综合评分", _format_metric(row.get("composite_score"), digits=2)),
        ("年化收益", _format_percent(row.get("annual_return"))),
        ("年化波动", _format_percent(row.get("annual_volatility"))),
        ("最大回撤", _format_percent(row.get("max_drawdown"))),
        ("Sharpe", _format_metric(row.get("sharpe"), digits=3)),
        ("Calmar", _format_metric(row.get("calmar"), digits=3)),
        ("风险等级", str(row.get("risk_level", ""))),
        ("标签", str(row.get("decision_label", ""))),
    ]
    cells = "\n".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in items
    )
    explanation = html.escape(str(row.get("result_explanation", row.get("decision_reason", ""))))
    return f"""
    <section class="section">
      <h2>指标摘要</h2>
      <div class="table-wrap"><table><tbody>{cells}</tbody></table></div>
      <div class="report-body"><p>{explanation}</p></div>
    </section>
    """


def _fund_rank_summary(
    base_row: pd.Series,
    adaptive_row: pd.Series | None,
    ml_row: pd.Series | None,
    peer_row: pd.Series | None,
) -> str:
    rows = [
        ("原始排名", _format_metric(base_row.get("rank"), digits=0), _format_metric(base_row.get("composite_score"), digits=2)),
        (
            "动态权重排名",
            _format_metric(adaptive_row.get("dynamic_rank") if adaptive_row is not None else None, digits=0),
            _format_metric(adaptive_row.get("dynamic_score") if adaptive_row is not None else None, digits=2),
        ),
        (
            "ML辅助排名",
            _format_metric(ml_row.get("ml_rank") if ml_row is not None else None, digits=0),
            _format_metric(ml_row.get("ml_score") if ml_row is not None else None, digits=2),
        ),
        (
            "基金池百分位",
            _format_percent(peer_row.get("pool_percentile") if peer_row is not None else None),
            "越高表示在本次基金池内越靠前",
        ),
        (
            "同类百分位",
            _format_percent(peer_row.get("type_percentile") if peer_row is not None else None),
            f"同类数量：{_format_metric(peer_row.get('type_count') if peer_row is not None else None, digits=0)}",
        ),
    ]
    body = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td class=\"num\">{html.escape(rank)}</td><td>{html.escape(score)}</td></tr>"
        for label, rank, score in rows
    )
    return f"""
    <section class="section">
      <h2>排名与同类位置</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>项目</th><th class="num">排名/百分位</th><th>说明/评分</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _fund_dynamic_weight_section(weight_table: pd.DataFrame, fund: str) -> str:
    rows = _matching_rows(weight_table, fund)
    if rows.empty:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('feature_label', row.get('feature', ''))))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('profile_base_weight'))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('ml_reference_weight'))}</td>"
        f"<td class=\"num\">{_format_percent(row.get('dynamic_weight'))}</td>"
        f"<td class=\"num\">{_format_signed_percent(row.get('weight_delta'))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('factor_score'), digits=2)}</td>"
        f"<td class=\"reason-cell\">{html.escape(str(row.get('adjustment_reason', '')))}</td>"
        "</tr>"
        for _, row in rows.sort_values("dynamic_weight", ascending=False).iterrows()
    )
    return f"""
    <section class="section">
      <h2>基金级动态权重</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>因子</th><th class="num">基础权重</th><th class="num">ML参考</th><th class="num">动态权重</th><th class="num">调整</th><th class="num">因子得分</th><th>原因</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _fund_lime_section(lime: pd.DataFrame, fund: str) -> str:
    rows = _matching_rows(lime, fund)
    if rows.empty:
        return ""
    rows = rows.sort_values("abs_weight", ascending=False).head(8)
    body = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('feature', '')))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('local_weight'), digits=3)}</td>"
        f"<td>{html.escape(str(row.get('local_direction', '')))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('surrogate_r2'), digits=3)}</td>"
        "</tr>"
        for _, row in rows.iterrows()
    )
    return f"""
    <section class="section">
      <h2>LIME 局部解释</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>局部因子</th><th class="num">局部权重</th><th>方向</th><th class="num">代理R²</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _fund_contribution_section(contributions: pd.DataFrame, fund: str) -> str:
    rows = _matching_rows(contributions, fund)
    if rows.empty:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(row.get('factor', '')))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('factor_score'), digits=2)}</td>"
        f"<td class=\"num\">{_format_percent(row.get('weight'))}</td>"
        f"<td class=\"num\">{_format_metric(row.get('contribution'), digits=2)}</td>"
        "</tr>"
        for _, row in rows.sort_values("contribution", ascending=False).iterrows()
    )
    return f"""
    <section class="section">
      <h2>因子贡献分解</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>因子</th><th class="num">因子得分</th><th class="num">权重</th><th class="num">贡献</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _fund_peer_section(peers: pd.DataFrame, fund: str) -> str:
    row = _find_fund_row(peers, fund)
    if row is None:
        return ""
    items = [
        ("基金池排名", f"{_format_metric(row.get('pool_rank'), digits=0)} / {len(peers)}"),
        ("基金池百分位", _format_percent(row.get("pool_percentile"))),
        ("同类排名", f"{_format_metric(row.get('type_rank'), digits=0)} / {_format_metric(row.get('type_count'), digits=0)}"),
        ("同类百分位", _format_percent(row.get("type_percentile"))),
        ("风险等级", str(row.get("risk_level", ""))),
        ("决策标签", str(row.get("decision_label", ""))),
    ]
    body = "\n".join(f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>" for label, value in items)
    return f"""
    <section class="section">
      <h2>同类/基金池对比</h2>
      <div class="table-wrap"><table><tbody>{body}</tbody></table></div>
    </section>
    """


def _matching_rows(frame: pd.DataFrame, fund: str) -> pd.DataFrame:
    if frame.empty or "fund" not in frame.columns:
        return pd.DataFrame()
    selected = _normalize_fund_key(fund)
    return frame[frame["fund"].map(_normalize_fund_key) == selected].copy()


def _download_section(profile: str, run_id: int | None) -> str:
    report_base = f"/runs/{run_id}/reports" if run_id else "/reports"
    processed_base = f"/runs/{run_id}/processed" if run_id else "/processed"
    primary_files = [
        ("Word 综合报告", f"{report_base}/analysis_reports.docx", "reports", "analysis_reports.docx"),
        ("PDF 综合报告", f"{report_base}/analysis_reports.pdf", "reports", "analysis_reports.pdf"),
        ("Excel 数据汇总", f"{report_base}/analysis_data.xlsx", "reports", "analysis_data.xlsx"),
        ("主分析报告", f"{report_base}/fund_analysis_report.md", "reports", "fund_analysis_report.md"),
        ("模型效果评估", f"{report_base}/ml_evaluation.md", "reports", "ml_evaluation.md"),
        ("数据质量诊断", f"{report_base}/data_quality_diagnostics.md", "reports", "data_quality_diagnostics.md"),
        ("组合建议说明书", f"{report_base}/portfolio_recommendation.md", "reports", "portfolio_recommendation.md"),
    ]
    report_files = [
        ("基金池准入报告", f"{report_base}/fund_universe.md", "reports", "fund_universe.md"),
        ("基准与同类对比报告", f"{report_base}/benchmark_comparison.md", "reports", "benchmark_comparison.md"),
        ("组合构建报告", f"{report_base}/portfolio_construction.md", "reports", "portfolio_construction.md"),
        ("组合再平衡报告", f"{report_base}/portfolio_rebalance_report.md", "reports", "portfolio_rebalance_report.md"),
        ("Walk-Forward 验证报告", f"{report_base}/backtest_summary.md", "reports", "backtest_summary.md"),
        ("动态权重验证报告", f"{report_base}/adaptive_backtest_summary.md", "reports", "adaptive_backtest_summary.md"),
        ("因子贡献解释", f"{report_base}/factor_contributions.md", "reports", "factor_contributions.md"),
        ("LIME 局部解释", f"{report_base}/lime_explanations.md", "reports", "lime_explanations.md"),
        ("基金级动态权重报告", f"{report_base}/adaptive_weight_report.md", "reports", "adaptive_weight_report.md"),
        ("ML 辅助评分报告", f"{report_base}/ml_model_report.md", "reports", "ml_model_report.md"),
        ("模型效果评估报告", f"{report_base}/ml_evaluation.md", "reports", "ml_evaluation.md"),
        ("原始/ML 排名对比", f"{report_base}/ranking_comparison.md", "reports", "ranking_comparison.md"),
        ("策略回测基准报告", f"{report_base}/strategy_benchmark.md", "reports", "strategy_benchmark.md"),
        ("数据质量诊断报告", f"{report_base}/data_quality_diagnostics.md", "reports", "data_quality_diagnostics.md"),
        ("因子相关性诊断", f"{report_base}/factor_diagnostics.md", "reports", "factor_diagnostics.md"),
        ("权重敏感性报告", f"{report_base}/weight_sensitivity.md", "reports", "weight_sensitivity.md"),
        ("权重扰动稳健性报告", f"{report_base}/weight_robustness.md", "reports", "weight_robustness.md"),
        ("研究附录", f"{report_base}/research_enhancement.md", "reports", "research_enhancement.md"),
        ("P3 研究报告", f"{report_base}/p3_research_enhancement.md", "reports", "p3_research_enhancement.md"),
    ]
    portfolio_files = [
        ("组合构建摘要 CSV", f"{report_base}/portfolio_summary.csv", "reports", "portfolio_summary.csv"),
        ("组合持仓权重 CSV", f"{report_base}/portfolio_weights_{profile}.csv", "reports", f"portfolio_weights_{profile}.csv"),
        ("组合约束配置 CSV", f"{report_base}/portfolio_constraints.csv", "reports", "portfolio_constraints.csv"),
        ("组合建议明细 CSV", f"{report_base}/portfolio_recommendations.csv", "reports", "portfolio_recommendations.csv"),
        ("组合风险控制 CSV", f"{report_base}/portfolio_risk_controls.csv", "reports", "portfolio_risk_controls.csv"),
        ("优化组合权重图", f"{report_base}/portfolio_optimized_weights.png", "reports", "portfolio_optimized_weights.png"),
        ("组合再平衡结果 CSV", f"{report_base}/portfolio_rebalance_results.csv", "reports", "portfolio_rebalance_results.csv"),
        ("组合再平衡窗口 CSV", f"{report_base}/portfolio_rebalance_periods.csv", "reports", "portfolio_rebalance_periods.csv"),
        ("组合再平衡图", f"{report_base}/portfolio_rebalance_cumulative_return.png", "reports", "portfolio_rebalance_cumulative_return.png"),
        ("策略回测基准 CSV", f"{report_base}/strategy_benchmark.csv", "reports", "strategy_benchmark.csv"),
        ("Walk-Forward 结果 CSV", f"{report_base}/walk_forward_results.csv", "reports", "walk_forward_results.csv"),
        ("动态权重验证 CSV", f"{report_base}/adaptive_walk_forward_results.csv", "reports", "adaptive_walk_forward_results.csv"),
        ("动态权重验证窗口 CSV", f"{report_base}/adaptive_walk_forward_periods.csv", "reports", "adaptive_walk_forward_periods.csv"),
        ("动态权重验证图", f"{report_base}/adaptive_walk_forward_cumulative_return.png", "reports", "adaptive_walk_forward_cumulative_return.png"),
    ]
    model_files = [
        ("动态权重解释图", f"{report_base}/dynamic_weight_top_factors.png", "reports", "dynamic_weight_top_factors.png"),
        ("LIME 局部解释图", f"{report_base}/lime_local_weight_bars.png", "reports", "lime_local_weight_bars.png"),
        ("排名变化解释图", f"{report_base}/rank_comparison_changes.png", "reports", "rank_comparison_changes.png"),
        ("因子贡献 CSV", f"{report_base}/factor_contributions.csv", "reports", "factor_contributions.csv"),
        ("LIME 局部解释 CSV", f"{report_base}/lime_explanations.csv", "reports", "lime_explanations.csv"),
        ("基金级动态权重 CSV", f"{report_base}/adaptive_factor_weights.csv", "reports", "adaptive_factor_weights.csv"),
        ("动态权重排名 CSV", f"{report_base}/ranking_adaptive_{profile}.csv", "reports", f"ranking_adaptive_{profile}.csv"),
        ("ML 学习权重 CSV", f"{report_base}/ml_learned_weights.csv", "reports", "ml_learned_weights.csv"),
        ("模型效果评估 CSV", f"{report_base}/ml_evaluation.csv", "reports", "ml_evaluation.csv"),
        ("ML 辅助排名 CSV", f"{report_base}/ranking_ml_{profile}.csv", "reports", f"ranking_ml_{profile}.csv"),
        ("原始/ML 排名对比 CSV", f"{report_base}/ranking_comparison_{profile}.csv", "reports", f"ranking_comparison_{profile}.csv"),
        ("ML 训练样本 CSV", f"{report_base}/ml_training_samples.csv", "reports", "ml_training_samples.csv"),
    ]
    detail_files = [
        ("当前画像排名 CSV", f"{report_base}/ranking_{profile}.csv", "reports", f"ranking_{profile}.csv"),
        ("基准组合对比 CSV", f"{report_base}/benchmark_comparison.csv", "reports", "benchmark_comparison.csv"),
        ("同类基金对比 CSV", f"{report_base}/peer_comparison_{profile}.csv", "reports", f"peer_comparison_{profile}.csv"),
        ("数据质量诊断 CSV", f"{report_base}/data_quality_diagnostics.csv", "reports", "data_quality_diagnostics.csv"),
        ("全部画像排名 CSV", f"{processed_base}/ranking_all_profiles.csv", "processed", "ranking_all_profiles.csv"),
        ("指标明细 CSV", f"{processed_base}/fund_metrics.csv", "processed", "fund_metrics.csv"),
    ]
    primary_links = _render_download_links(_available_downloads(primary_files, run_id))
    groups = "\n".join(
        group
        for group in [
            _download_group("报告文档", report_files, run_id),
            _download_group("组合与回测数据", portfolio_files, run_id),
            _download_group("模型解释与排名数据", model_files, run_id),
            _download_group("基础明细数据", detail_files, run_id),
        ]
        if group
    )
    if not primary_links and not groups:
        return ""

    primary_html = f'<div class="toolbar download-primary" aria-label="常用下载">{primary_links}</div>' if primary_links else ""
    hint = '<p class="download-hint">常用文件已放在上方，其余明细按类型展开下载。</p>' if groups else ""
    group_html = f'<div class="download-groups">{groups}</div>' if groups else ""
    return f"""
    <section class="section">
      <h2>下载结果</h2>
      {primary_html}
      {hint}
      {group_html}
    </section>
    """


def _figure_section(profile: str, run_id: int | None) -> str:
    report_base = f"/runs/{run_id}/reports" if run_id else "/reports"
    figure_files = [
        ("核心概览", "风险收益分布", f"{report_base}/risk_return_{profile}.png", "reports", f"risk_return_{profile}.png"),
        ("核心概览", "Top 10 多因子评分", f"{report_base}/top_scores_{profile}.png", "reports", f"top_scores_{profile}.png"),
        ("走势分析", "Top 基金净值走势", f"{report_base}/nav_top_{profile}.png", "reports", f"nav_top_{profile}.png"),
        ("走势分析", "Top 基金回撤走势", f"{report_base}/drawdown_top_{profile}.png", "reports", f"drawdown_top_{profile}.png"),
        ("组合分析", "优化组合权重", f"{report_base}/portfolio_optimized_weights.png", "reports", "portfolio_optimized_weights.png"),
        ("组合分析", "Adaptive Walk-Forward 累计收益", f"{report_base}/adaptive_walk_forward_cumulative_return.png", "reports", "adaptive_walk_forward_cumulative_return.png"),
        ("组合分析", "组合再平衡累计收益", f"{report_base}/portfolio_rebalance_cumulative_return.png", "reports", "portfolio_rebalance_cumulative_return.png"),
        ("解释诊断", "Top 基金动态因子权重", f"{report_base}/dynamic_weight_top_factors.png", "reports", "dynamic_weight_top_factors.png"),
        ("解释诊断", "LIME 局部解释", f"{report_base}/lime_local_weight_bars.png", "reports", "lime_local_weight_bars.png"),
        ("解释诊断", "排名变化解释", f"{report_base}/rank_comparison_changes.png", "reports", "rank_comparison_changes.png"),
    ]
    figures = _available_figures(figure_files, run_id)
    if not figures:
        return ""

    first_group, first_label, first_href = figures[0]
    buttons = "\n".join(
        f"""<button type="button" class="chart-option {'is-active' if index == 0 else ''}" aria-pressed="{'true' if index == 0 else 'false'}" data-chart-src="{html.escape(href, quote=True)}" data-chart-label="{html.escape(label, quote=True)}" data-chart-group="{html.escape(group, quote=True)}">
          <span class="chart-option-group">{html.escape(group)}</span>
          {html.escape(label)}
        </button>"""
        for index, (group, label, href) in enumerate(figures)
    )
    return f"""
    <section class="section">
      <h2>图表结果</h2>
      <p class="section-lede">默认只展示一张大图。左侧选择想看的图表，点击图片可打开原图查看细节。</p>
      <div class="chart-viewer">
        <div class="chart-picker" aria-label="选择图表">
          {buttons}
        </div>
        <figure class="chart-stage">
          <a id="chart-open-link" href="{html.escape(first_href, quote=True)}" target="_blank" rel="noopener">
            <img id="chart-main-image" src="{html.escape(first_href, quote=True)}" alt="{html.escape(first_label, quote=True)}" loading="eager" onerror="this.closest('figure').remove()">
          </a>
          <figcaption class="chart-caption">
            <span class="chart-caption-title">
              <strong id="chart-main-label">{html.escape(first_label)}</strong>
              <span id="chart-main-group">{html.escape(first_group)}</span>
            </span>
            <a id="chart-open-text" class="chart-open" href="{html.escape(first_href, quote=True)}" target="_blank" rel="noopener">打开原图</a>
          </figcaption>
        </figure>
      </div>
    </section>
    """


def _available_figures(
    files: list[tuple[str, str, str, str, str]],
    run_id: int | None,
) -> list[tuple[str, str, str]]:
    if run_id is None:
        roots = {"reports": WEB_REPORTS_DIR, "processed": WEB_PROCESSED_DIR}
        available = []
        seen_labels = set()
        for group, label, href, root_name, filename in files:
            path = roots[root_name] / filename
            chart_href = _versioned_href(href, path) if path.exists() else href
            if label not in seen_labels:
                available.append((group, label, chart_href))
                seen_labels.add(label)
        return available
    else:
        run = FundDatabase().get_run(run_id)
        if run is None:
            return []
        roots = {
            "reports": Path(str(run["reports_dir"])),
            "processed": Path(str(run["processed_dir"])),
        }
    available = []
    seen_labels = set()
    for group, label, href, root_name, filename in files:
        path = roots[root_name] / filename
        if path.exists() and label not in seen_labels:
            available.append((group, label, _versioned_href(href, path)))
            seen_labels.add(label)
    return available


def _versioned_href(href: str, path: Path) -> str:
    separator = "&" if "?" in href else "?"
    return f"{href}{separator}v={int(path.stat().st_mtime)}"


def _download_group(title: str, files: list[tuple[str, str, str, str]], run_id: int | None) -> str:
    links = _render_download_links(_available_downloads(files, run_id))
    if not links:
        return ""
    return f"""
    <details class="download-group">
      <summary>{html.escape(title)}</summary>
      <div class="toolbar">{links}</div>
    </details>
    """


def _render_download_links(files: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<a href="{html.escape(href, quote=True)}" download>{html.escape(label)}</a>'
        for label, href in files
    )


def _run_status_section(run_status: str) -> str:
    if not run_status:
        return ""

    labels = {
        "running": ("分析任务运行中", "正在抓取数据、计算排名并生成 Word/PDF/Excel 报告。本页面会自动刷新。"),
        "success": ("分析任务已完成", "结果、图表和下载文件已生成。"),
        "failed": ("分析任务失败", "请查看下方错误信息，修正参数或稍后重试。"),
    }
    title, message = labels.get(run_status, ("分析任务状态", run_status))
    return f"""
    <div class="run-status {html.escape(run_status)}">
      <strong>{html.escape(title)}</strong>
      <span>{html.escape(message)}</span>
    </div>
    """


def _standalone_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #176b87;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 17px;
    }}
    main {{ padding: 24px 32px 48px; }}
    h1 {{ margin: 12px 0 18px; font-size: 30px; letter-spacing: 0; }}
    a {{ color: var(--accent); font-weight: 600; text-decoration: none; }}
    .section {{
      margin-top: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .section h2 {{ margin: 0; padding: 16px 18px; font-size: 22px; border-bottom: 1px solid var(--line); }}
    .table-wrap {{ width: 100%; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 15px; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); background: #fbfcfd; font-weight: 600; }}
    th.num, td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    td.reason-cell {{ min-width: 280px; line-height: 1.55; }}
    .report-body {{ padding: 4px 18px 20px; line-height: 1.75; }}
    @media (max-width: 900px) {{
      main {{ padding-left: 16px; padding-right: 16px; }}
    }}
  </style>
</head>
<body><main>{body}</main></body>
</html>"""


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


def _preset_manager_section(presets: list[dict[str, object]]) -> str:
    if not presets:
        return ""
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(item['name']))}</td>"
        f"<td>{html.escape(str(item.get('profile', '')))}</td>"
        f"<td>{_preset_weight_summary(item.get('factor_weights', {}))}</td>"
        f"<td>{html.escape(str(item.get('updated_at', '')))}</td>"
        f"<td><form method=\"post\" action=\"/presets/delete\" style=\"display:block;padding:0;border:0;background:transparent;\"><input type=\"hidden\" name=\"preset_name\" value=\"{html.escape(str(item['name']))}\"><button class=\"secondary\" type=\"submit\">删除</button></form></td>"
        "</tr>"
        for item in presets
    )
    return f"""
    <section class="section">
      <h2>分析方案</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>方案名称</th><th>画像</th><th>主要权重</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    """


def _preset_weight_summary(weights: object) -> str:
    normalized = _normalize_factor_weights(weights)
    top = sorted(normalized.items(), key=lambda item: item[1], reverse=True)[:3]
    return html.escape("；".join(f"{FACTOR_LABELS.get(metric, metric)} {weight:.0%}" for metric, weight in top))


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
          <thead><tr><th>时间</th><th>状态</th><th>基金代码</th><th>起始日期</th><th>画像</th><th class="num">Top N</th><th>操作</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def _history_row(run: dict[str, object]) -> str:
    constraints = normalize_portfolio_constraints(run.get("portfolio_constraints"))
    factor_weights = _normalize_factor_weights(run.get("factor_weights"), str(run.get("profile", "balanced")))
    use_custom = bool(run.get("factor_weights"))
    params = urlencode(
        {
            "codes": " ".join(run["codes"]),
            "start_date": run["start_date"],
            "profile": run["profile"],
            "top_n": run["top_n"],
            "fund_pool": "custom",
            "use_custom_weights": "1" if use_custom else "",
            **{f"weight_{metric}": f"{factor_weights.get(metric, 0.0):.4f}" for metric in SCORE_METRICS},
            "portfolio_objective": constraints.objective,
            "portfolio_min_funds": constraints.min_funds,
            "portfolio_max_funds": constraints.max_funds,
            "max_position_weight": constraints.max_position_weight,
            "max_type_weight": constraints.max_type_weight,
            "max_pair_correlation": constraints.max_pair_correlation,
            "portfolio_max_drawdown": constraints.max_drawdown_floor,
            "portfolio_min_sharpe": constraints.min_sharpe,
            "rebalance_days": constraints.rebalance_days,
            "max_turnover": constraints.max_turnover,
            "transaction_cost_bps": constraints.transaction_cost_bps,
        }
    )
    return (
        "<tr>"
        f"<td>{html.escape(str(run['created_at']))}</td>"
        f"<td>{_status_badge(str(run.get('status', 'success')))}</td>"
        f"<td>{html.escape(' '.join(run['codes']))}</td>"
        f"<td>{html.escape(str(run['start_date']))}</td>"
        f"<td>{html.escape(str(run['profile']))}</td>"
        f"<td class=\"num\">{run['top_n']}</td>"
        f"<td><a href=\"/runs/{run['id']}\">打开</a> · <a href=\"/?{params}\">复用</a></td>"
        "</tr>"
    )


def _status_badge(status: str) -> str:
    labels = {"running": "运行中", "success": "已完成", "failed": "失败"}
    safe_status = html.escape(status)
    return f'<span class="status-badge {safe_status}">{html.escape(labels.get(status, status))}</span>'


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
        elif line.startswith("### "):
            if in_list:
                output.append("</ul>")
                in_list = False
            output.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
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


def _format_optional_number(value: object, digits: int = 0) -> str:
    if value in {None, ""} or pd.isna(value):
        return ""
    numeric = float(value)
    if digits <= 0:
        return str(int(numeric))
    return f"{numeric:.{digits}f}"


def _format_metric(value: object, digits: int = 2) -> str:
    if value in {None, ""} or pd.isna(value):
        return ""
    numeric = float(value)
    if digits <= 0:
        return str(int(numeric))
    return f"{numeric:.{digits}f}"


def _format_percent(value: object) -> str:
    if value in {None, ""} or pd.isna(value):
        return ""
    return f"{float(value):.2%}"


def _format_signed_percent(value: object) -> str:
    if value in {None, ""} or pd.isna(value):
        return ""
    return f"{float(value):+.2%}"
