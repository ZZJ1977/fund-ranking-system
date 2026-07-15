from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_DB_PATH = Path(os.environ.get("FUND_RANKING_DB", "data/fund_ranking.db"))


class FundDatabase:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def save_metadata(self, metadata: pd.DataFrame) -> None:
        if metadata.empty:
            return

        rows = [
            (
                str(row["fund_code"]).zfill(6),
                str(row["fund_name"]),
                str(row.get("fund_type", "未分类") or "未分类"),
            )
            for _, row in metadata.iterrows()
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                insert into funds (fund_code, fund_name, fund_type, updated_at)
                values (?, ?, ?, ?)
                on conflict(fund_code) do update set
                    fund_name = excluded.fund_name,
                    fund_type = excluded.fund_type,
                    updated_at = excluded.updated_at
                """,
                [(code, name, fund_type, _now()) for code, name, fund_type in rows],
            )

    def save_nav(self, nav: pd.DataFrame) -> None:
        if nav.empty:
            return

        rows: list[tuple[str, str, float]] = []
        for date, values in nav.iterrows():
            date_text = pd.Timestamp(date).strftime("%Y-%m-%d")
            for fund_code, nav_value in values.dropna().items():
                rows.append((str(fund_code).zfill(6), date_text, float(nav_value)))

        with self._connect() as conn:
            conn.executemany(
                """
                insert into fund_nav (fund_code, nav_date, nav)
                values (?, ?, ?)
                on conflict(fund_code, nav_date) do update set nav = excluded.nav
                """,
                rows,
            )

    def load_nav(self, codes: list[str], start_date: str) -> pd.DataFrame:
        normalized_codes = [code.zfill(6) for code in codes]
        placeholders = ",".join("?" for _ in normalized_codes)
        query = f"""
            select fund_code, nav_date, nav
            from fund_nav
            where fund_code in ({placeholders}) and nav_date >= ?
            order by nav_date
        """

        with self._connect() as conn:
            rows = conn.execute(query, [*normalized_codes, start_date]).fetchall()

        if not rows:
            return pd.DataFrame()

        frame = pd.DataFrame(rows, columns=["fund_code", "nav_date", "nav"])
        frame["nav_date"] = pd.to_datetime(frame["nav_date"])
        nav = frame.pivot(index="nav_date", columns="fund_code", values="nav")
        return nav.reindex(columns=normalized_codes).dropna(how="all").ffill()

    def load_metadata(self, codes: list[str]) -> pd.DataFrame:
        normalized_codes = [code.zfill(6) for code in codes]
        placeholders = ",".join("?" for _ in normalized_codes)
        query = f"""
            select fund_code, fund_name, fund_type
            from funds
            where fund_code in ({placeholders})
            order by fund_code
        """

        with self._connect() as conn:
            rows = conn.execute(query, normalized_codes).fetchall()

        return pd.DataFrame(rows, columns=["fund_code", "fund_name", "fund_type"])

    def cached_codes(self, codes: list[str], start_date: str, min_rows: int = 30) -> set[str]:
        normalized_codes = [code.zfill(6) for code in codes]
        placeholders = ",".join("?" for _ in normalized_codes)
        query = f"""
            select fund_code, count(*) as row_count
            from fund_nav
            where fund_code in ({placeholders}) and nav_date >= ?
            group by fund_code
        """

        with self._connect() as conn:
            rows = conn.execute(query, [*normalized_codes, start_date]).fetchall()

        return {code for code, row_count in rows if row_count >= min_rows}

    def record_analysis(
        self,
        codes: list[str],
        start_date: str,
        profile: str,
        top_n: int,
        report_path: str | Path,
        reports_dir: str | Path | None = None,
        processed_dir: str | Path | None = None,
        status: str = "success",
        error_message: str = "",
        completed_at: str = "",
        portfolio_constraints: dict[str, object] | str | None = None,
        factor_weights: dict[str, float] | str | None = None,
    ) -> int:
        finished_at = completed_at or (_now() if status != "running" else "")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                insert into analysis_runs
                    (
                        created_at, codes, start_date, profile, top_n,
                        report_path, reports_dir, processed_dir,
                        status, error_message, completed_at, portfolio_constraints, factor_weights
                    )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    json.dumps(codes, ensure_ascii=False),
                    start_date,
                    profile,
                    top_n,
                    str(report_path),
                    str(reports_dir or Path(report_path).parent),
                    str(processed_dir or ""),
                    status,
                    error_message,
                    finished_at,
                    _encode_constraints(portfolio_constraints),
                    _encode_constraints(factor_weights),
                ),
            )
            return int(cursor.lastrowid)

    def update_analysis_status(
        self,
        run_id: int,
        status: str,
        report_path: str | Path | None = None,
        reports_dir: str | Path | None = None,
        processed_dir: str | Path | None = None,
        error_message: str = "",
        completed_at: str | None = None,
    ) -> None:
        completed = completed_at if completed_at is not None else _now()
        with self._connect() as conn:
            conn.execute(
                """
                update analysis_runs
                set status = ?,
                    report_path = coalesce(?, report_path),
                    reports_dir = coalesce(?, reports_dir),
                    processed_dir = coalesce(?, processed_dir),
                    error_message = ?,
                    completed_at = ?
                where id = ?
                """,
                (
                    status,
                    str(report_path) if report_path is not None else None,
                    str(reports_dir) if reports_dir is not None else None,
                    str(processed_dir) if processed_dir is not None else None,
                    error_message,
                    completed,
                    run_id,
                ),
            )

    def recent_runs(self, limit: int = 8) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                    id, created_at, codes, start_date, profile, top_n,
                    report_path, reports_dir, processed_dir,
                    status, error_message, completed_at, portfolio_constraints, factor_weights
                from analysis_runs
                order by id desc
                limit ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "created_at": created_at,
                "id": run_id,
                "codes": json.loads(codes),
                "start_date": start_date,
                "profile": profile,
                "top_n": top_n,
                "report_path": report_path,
                "reports_dir": reports_dir,
                "processed_dir": processed_dir,
                "status": status,
                "error_message": error_message,
                "completed_at": completed_at,
                "portfolio_constraints": json.loads(portfolio_constraints or "{}"),
                "factor_weights": json.loads(factor_weights or "{}"),
            }
            for (
                run_id,
                created_at,
                codes,
                start_date,
                profile,
                top_n,
                report_path,
                reports_dir,
                processed_dir,
                status,
                error_message,
                completed_at,
                portfolio_constraints,
                factor_weights,
            ) in rows
        ]

    def fund_codes(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("select fund_code from funds order by fund_code").fetchall()
        return [row[0] for row in rows]

    def get_run(self, run_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                    id, created_at, codes, start_date, profile, top_n,
                    report_path, reports_dir, processed_dir,
                    status, error_message, completed_at, portfolio_constraints, factor_weights
                from analysis_runs
                where id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row[0],
            "created_at": row[1],
            "codes": json.loads(row[2]),
            "start_date": row[3],
            "profile": row[4],
            "top_n": row[5],
            "report_path": row[6],
            "reports_dir": row[7],
            "processed_dir": row[8],
            "status": row[9],
            "error_message": row[10],
            "completed_at": row[11],
            "portfolio_constraints": json.loads(row[12] or "{}"),
            "factor_weights": json.loads(row[13] or "{}"),
        }

    def nav_stats(self, codes: list[str] | None = None) -> list[dict[str, object]]:
        params: list[str] = []
        where = ""
        if codes:
            normalized = [code.zfill(6) for code in codes]
            where = "where n.fund_code in (" + ",".join("?" for _ in normalized) + ")"
            params = normalized

        query = f"""
            select n.fund_code, coalesce(f.fund_name, ''), coalesce(f.fund_type, '未分类'), min(n.nav_date), max(n.nav_date), count(*)
            from fund_nav n
            left join funds f on f.fund_code = n.fund_code
            {where}
            group by n.fund_code, f.fund_name, f.fund_type
            order by n.fund_code
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "fund_code": code,
                "fund_name": name,
                "fund_type": fund_type,
                "start_date": start,
                "end_date": end,
                "row_count": row_count,
            }
            for code, name, fund_type, start, end, row_count in rows
        ]

    def save_pool(self, name: str, codes: list[str]) -> None:
        normalized = [code.zfill(6) for code in codes]
        with self._connect() as conn:
            conn.execute(
                """
                insert into fund_pools (name, codes, updated_at)
                values (?, ?, ?)
                on conflict(name) do update set
                    codes = excluded.codes,
                    updated_at = excluded.updated_at
                """,
                (name.strip(), json.dumps(normalized, ensure_ascii=False), _now()),
            )

    def delete_pool(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from fund_pools where name = ?", (name,))

    def list_pools(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select name, codes, updated_at from fund_pools order by updated_at desc"
            ).fetchall()
        return [
            {"name": name, "codes": json.loads(codes), "updated_at": updated_at}
            for name, codes, updated_at in rows
        ]

    def save_preset(
        self,
        name: str,
        profile: str,
        factor_weights: dict[str, float],
        portfolio_constraints: dict[str, object] | str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into analysis_presets (name, profile, factor_weights, portfolio_constraints, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(name) do update set
                    profile = excluded.profile,
                    factor_weights = excluded.factor_weights,
                    portfolio_constraints = excluded.portfolio_constraints,
                    updated_at = excluded.updated_at
                """,
                (
                    name.strip(),
                    profile,
                    json.dumps(factor_weights, ensure_ascii=False),
                    _encode_constraints(portfolio_constraints),
                    _now(),
                ),
            )

    def delete_preset(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from analysis_presets where name = ?", (name,))

    def list_presets(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select name, profile, factor_weights, portfolio_constraints, updated_at
                from analysis_presets
                order by updated_at desc
                """
            ).fetchall()
        return [
            {
                "name": name,
                "profile": profile,
                "factor_weights": json.loads(factor_weights or "{}"),
                "portfolio_constraints": json.loads(portfolio_constraints or "{}"),
                "updated_at": updated_at,
            }
            for name, profile, factor_weights, portfolio_constraints, updated_at in rows
        ]

    def get_preset(self, name: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select name, profile, factor_weights, portfolio_constraints, updated_at
                from analysis_presets
                where name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            return None
        return {
            "name": row[0],
            "profile": row[1],
            "factor_weights": json.loads(row[2] or "{}"),
            "portfolio_constraints": json.loads(row[3] or "{}"),
            "updated_at": row[4],
        }

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists funds (
                    fund_code text primary key,
                    fund_name text not null,
                    fund_type text not null default '未分类',
                    updated_at text not null
                );

                create table if not exists fund_nav (
                    fund_code text not null,
                    nav_date text not null,
                    nav real not null,
                    primary key (fund_code, nav_date)
                );

                create table if not exists analysis_runs (
                    id integer primary key autoincrement,
                    created_at text not null,
                    codes text not null,
                    start_date text not null,
                    profile text not null,
                    top_n integer not null,
                    report_path text not null,
                    reports_dir text not null default '',
                    processed_dir text not null default '',
                    status text not null default 'success',
                    error_message text not null default '',
                    completed_at text not null default '',
                    portfolio_constraints text not null default '{}',
                    factor_weights text not null default '{}'
                );

                create table if not exists fund_pools (
                    name text primary key,
                    codes text not null,
                    updated_at text not null
                );

                create table if not exists analysis_presets (
                    name text primary key,
                    profile text not null,
                    factor_weights text not null default '{}',
                    portfolio_constraints text not null default '{}',
                    updated_at text not null
                );
                """
            )
            self._ensure_column(conn, "funds", "fund_type", "text not null default '未分类'")
            self._ensure_column(conn, "analysis_runs", "reports_dir", "text not null default ''")
            self._ensure_column(conn, "analysis_runs", "processed_dir", "text not null default ''")
            self._ensure_column(conn, "analysis_runs", "status", "text not null default 'success'")
            self._ensure_column(conn, "analysis_runs", "error_message", "text not null default ''")
            self._ensure_column(conn, "analysis_runs", "completed_at", "text not null default ''")
            self._ensure_column(conn, "analysis_runs", "portfolio_constraints", "text not null default '{}'")
            self._ensure_column(conn, "analysis_runs", "factor_weights", "text not null default '{}'")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"alter table {table} add column {column} {definition}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _encode_constraints(value: dict[str, object] | str | None) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value or "{}"
    return json.dumps(value, ensure_ascii=False)
