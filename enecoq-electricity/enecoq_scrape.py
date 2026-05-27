# -*- coding: utf-8 -*-
"""
enecoQ electricity usage scraper.

Outputs:
  /share/enecoq_electricity.json

Env:
  ENECOQ_USERNAME
  ENECOQ_PASSWORD
  ENECOQ_LOGIN_URL
  ENECOQ_DEBUG
"""

import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, sync_playwright


DEFAULT_LOGIN_URL = "https://www.cyberhome.ne.jp/app/sslLogin.do"
OUT_JSON = "/share/enecoq_electricity.json"
TOKYO_TZ = ZoneInfo("Asia/Tokyo")
FIRST_HISTORY_YEAR = 2023


def log(message: str) -> None:
    print(f"[enecoq] {message}", flush=True)


def _ensure_share() -> None:
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)


def _debug_enabled() -> bool:
    return str(os.environ.get("ENECOQ_DEBUG", "")).lower() in ("1", "true", "yes", "on")


def _debug_dump(page: Page, tag: str) -> None:
    if not _debug_enabled():
        return
    try:
        Path(f"/share/enecoq_{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=f"/share/enecoq_{tag}.png", full_page=True)
    except Exception:
        pass


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _history_url(kind: str, year: int, month: int, session: Dict[str, str]) -> str:
    path = "ryg_usage/" if kind == "usage" else "ryg_yen/"
    query = {
        "year": str(year),
        "month": f"{month:02d}",
        "cal": "m",
        **session,
    }
    return f"https://ses.me-eco.jp/pc/room/electric/cat/{path}?{urlencode(query)}"


def _parse_daily_table(text: str, unit: str) -> Dict[int, Dict[str, float]]:
    pattern = re.compile(
        rf"(\d{{1,2}})日\s+([\d,]+\.\d+)\s+{unit}\s+"
        rf"([\d,]+\.\d+)\s+{unit}\s+([\d,]+\.\d+)\s+{unit}\s+"
        rf"([\d,]+\.\d+)\s+{unit}"
    )
    rows: Dict[int, Dict[str, float]] = {}
    for match in pattern.finditer(text):
        day = int(match.group(1))
        rows[day] = {
            "low": _num(match.group(2)),
            "mid": _num(match.group(3)),
            "high": _num(match.group(4)),
            "total": _num(match.group(5)),
        }
    return rows


def _parse_monthly_table(text: str, unit: str) -> Dict[int, Dict[str, float]]:
    pattern = re.compile(
        rf"(\d{{1,2}})月\s+([\d,]+\.\d+)\s+{unit}\s+"
        rf"([\d,]+\.\d+)\s+{unit}\s+([\d,]+\.\d+)\s+{unit}\s+"
        rf"([\d,]+\.\d+)\s+{unit}"
    )
    rows: Dict[int, Dict[str, float]] = {}
    for match in pattern.finditer(text):
        month = int(match.group(1))
        rows[month] = {
            "low": _num(match.group(2)),
            "mid": _num(match.group(3)),
            "high": _num(match.group(4)),
            "total": _num(match.group(5)),
        }
    return rows


def _fetch_metric_page(page: Page, kind: str, year: int, month: int, session: Dict[str, str]) -> Dict[str, Dict[int, Dict[str, float]]]:
    unit = "kWh" if kind == "usage" else "円"
    url = _history_url(kind, year, month, session)
    response = page.goto(url, wait_until="networkidle")
    if response is None or response.status >= 400:
        raise RuntimeError(f"{kind} page failed for {year}-{month:02d}: HTTP {response.status if response else 'none'}")
    body_text = page.locator("body").inner_text(timeout=10000)
    if "有効期限切れ" in body_text or "エラーが発生しました" in body_text:
        _debug_dump(page, f"{kind}_{year}_{month:02d}_error")
        raise RuntimeError(f"{kind} page session expired for {year}-{month:02d}")

    tables = page.locator("table")
    if tables.count() < 2:
        _debug_dump(page, f"{kind}_{year}_{month:02d}_no_tables")
        raise RuntimeError(f"{kind} page missing expected tables for {year}-{month:02d}")

    return {
        "daily": _parse_daily_table(tables.nth(0).inner_text(), unit),
        "monthly": _parse_monthly_table(tables.nth(1).inner_text(), unit),
    }


def _open_detail_page(page: Page) -> Page:
    page.wait_for_load_state("networkidle")
    mini_frames = [frame for frame in page.frames if "ses.me-eco.jp/mini" in frame.url]
    if not mini_frames:
        raise RuntimeError("enecoQ mini iframe not found")
    mini = mini_frames[0]
    with page.context.expect_page(timeout=15000) as popup:
        mini.locator("input[type='image']").click()
    detail = popup.value
    detail.wait_for_load_state("networkidle")
    return detail


def _session_from_detail_url(detail_url: str) -> Dict[str, str]:
    query = parse_qs(urlparse(detail_url).query)
    session = {key: values[0] for key, values in query.items() if key in ("PHPSESSID", "svr_id") and values}
    if "PHPSESSID" not in session or "svr_id" not in session:
        raise RuntimeError("enecoQ detail session parameters not found")
    return session


def _login(page: Page, username: str, password: str, login_url: str) -> None:
    page.goto(login_url, wait_until="networkidle")
    page.locator("input[name='user_id']").fill(username)
    page.locator("input[name='password']").fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    if page.locator('a:has-text("ログアウト")').count() == 0:
        _debug_dump(page, "login_failed")
        raise RuntimeError("CYBERHOME login failed")


def _merge_daily(history: Dict[str, Dict[str, Any]], year: int, month: int, usage_rows: Dict[int, Dict[str, float]], cost_rows: Dict[int, Dict[str, float]]) -> None:
    for day, usage in usage_rows.items():
        key = f"{year:04d}-{month:02d}-{day:02d}"
        row = history.setdefault("daily", {}).setdefault(key, {"date": key})
        row.update(
            {
                "low_kwh": usage["low"],
                "mid_kwh": usage["mid"],
                "high_kwh": usage["high"],
                "usage_kwh": usage["total"],
            }
        )
        cost = cost_rows.get(day)
        if cost:
            row.update(
                {
                    "low_jpy": cost["low"],
                    "mid_jpy": cost["mid"],
                    "high_jpy": cost["high"],
                    "cost_jpy": cost["total"],
                }
            )


def _merge_monthly(history: Dict[str, Dict[str, Any]], year: int, usage_rows: Dict[int, Dict[str, float]], cost_rows: Dict[int, Dict[str, float]]) -> None:
    for month, usage in usage_rows.items():
        key = f"{year:04d}-{month:02d}"
        row = history.setdefault("monthly", {}).setdefault(key, {"month": key})
        row["usage_kwh"] = usage["total"]
        cost = cost_rows.get(month)
        if cost:
            row["cost_jpy"] = cost["total"]


def _history_years() -> List[int]:
    now = datetime.now(TOKYO_TZ)
    return list(range(FIRST_HISTORY_YEAR, now.year + 1))


def _combined_total(daily_rows: List[Dict[str, Any]], monthly_rows: List[Dict[str, Any]], field: str) -> float:
    if not daily_rows:
        return sum(float(row[field]) for row in monthly_rows)

    first_daily = date.fromisoformat(daily_rows[0]["date"])
    total = sum(
        float(row[field])
        for row in monthly_rows
        if date.fromisoformat(f"{row['month']}-01") < first_daily.replace(day=1)
    )
    total += sum(float(row[field]) for row in daily_rows)
    return total


def scrape(username: str, password: str, login_url: str) -> Dict[str, Any]:
    now = datetime.now(TOKYO_TZ)
    history: Dict[str, Dict[str, Any]] = {"daily": {}, "monthly": {}}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            log(f"open login page {login_url}")
            _login(page, username, password, login_url)
            log("login ok")
            detail = _open_detail_page(page)
            session = _session_from_detail_url(detail.url)
            log("enecoQ detail session ok")

            for year in _history_years():
                months = range(1, 13)
                if year == now.year:
                    months = range(1, now.month + 1)
                log(f"fetch year {year}")
                yearly_usage_rows: Dict[int, Dict[str, float]] = {}
                yearly_cost_rows: Dict[int, Dict[str, float]] = {}

                for month in months:
                    usage = _fetch_metric_page(detail, "usage", year, month, session)
                    cost = _fetch_metric_page(detail, "cost", year, month, session)
                    _merge_daily(history, year, month, usage["daily"], cost["daily"])
                    yearly_usage_rows.update(usage["monthly"])
                    yearly_cost_rows.update(cost["monthly"])

                _merge_monthly(history, year, yearly_usage_rows, yearly_cost_rows)
        finally:
            browser.close()

    daily_rows = [
        row
        for _, row in sorted(history["daily"].items())
        if row.get("usage_kwh") is not None and row.get("cost_jpy") is not None
    ]
    monthly_rows = [
        row
        for _, row in sorted(history["monthly"].items())
        if row.get("usage_kwh") is not None and row.get("cost_jpy") is not None
    ]

    total_usage = round(_combined_total(daily_rows, monthly_rows, "usage_kwh"), 6)
    total_cost = round(_combined_total(daily_rows, monthly_rows, "cost_jpy"), 2)
    latest_daily = daily_rows[-1] if daily_rows else None
    latest_monthly = monthly_rows[-1] if monthly_rows else None
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "enecoq",
        "fetched_at": fetched_at,
        "timezone": "Asia/Tokyo",
        "history_start": daily_rows[0]["date"] if daily_rows else None,
        "history_end": daily_rows[-1]["date"] if daily_rows else None,
        "daily_count": len(daily_rows),
        "monthly_count": len(monthly_rows),
        "total_usage_kwh": total_usage,
        "total_cost_jpy": total_cost,
        "latest_daily": latest_daily,
        "latest_monthly": latest_monthly,
        "daily": daily_rows,
        "monthly": monthly_rows,
    }


def atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def main() -> None:
    username = os.environ["ENECOQ_USERNAME"]
    password = os.environ["ENECOQ_PASSWORD"]
    login_url = os.environ.get("ENECOQ_LOGIN_URL") or DEFAULT_LOGIN_URL

    _ensure_share()
    payload = scrape(username, password, login_url)
    atomic_write_json(OUT_JSON, payload)
    log(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
