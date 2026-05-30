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
from datetime import date, datetime, timedelta, timezone
from html import unescape
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_LOGIN_URL = "https://www.cyberhome.ne.jp/app/sslLogin.do"
OUT_JSON = "/share/enecoq_electricity.json"
TOKYO_TZ = timezone(timedelta(hours=9), "Asia/Tokyo")
FIRST_HISTORY_YEAR = 2023
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
JPY_FIELDS = ("low_jpy", "mid_jpy", "high_jpy", "cost_jpy")


def log(message: str) -> None:
    print(f"[enecoq] {message}", flush=True)


def _ensure_share() -> None:
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)


def _debug_enabled() -> bool:
    return str(os.environ.get("ENECOQ_DEBUG", "")).lower() in ("1", "true", "yes", "on")


def _debug_dump(content: str, tag: str) -> None:
    if not _debug_enabled():
        return
    try:
        Path(f"/share/enecoq_{tag}.html").write_text(content, encoding="utf-8")
    except Exception:
        pass


class HttpClient:
    def __init__(self) -> None:
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, url: str, data: Dict[str, str] | None = None, referer: str | None = None) -> Tuple[str, str, int]:
        body = urlencode(data).encode("utf-8") if data is not None else None
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
        with self._opener.open(request, timeout=45) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), response.geturl(), response.status


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _round_jpy_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    for field in JPY_FIELDS:
        if row.get(field) is not None:
            row[field] = round(float(row[field]))
    return row


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


def _html_to_text(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)</(tr|p|div|li|br|th|td)>", "\n", fragment)
    text = re.sub(r"(?s)<[^>]+>", " ", fragment)
    text = unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _fetch_metric_page(client: HttpClient, kind: str, year: int, month: int, session: Dict[str, str]) -> Dict[str, Dict[int, Dict[str, float]]]:
    unit = "kWh" if kind == "usage" else "円"
    url = _history_url(kind, year, month, session)
    html, _, status = client.request(url)
    if status >= 400:
        raise RuntimeError(f"{kind} page failed for {year}-{month:02d}: HTTP {status}")
    body_text = _html_to_text(html)
    if "有効期限切れ" in body_text or "エラーが発生しました" in body_text:
        _debug_dump(html, f"{kind}_{year}_{month:02d}_error")
        raise RuntimeError(f"{kind} page session expired for {year}-{month:02d}")

    tables = re.findall(r"(?is)<table\b.*?</table>", html)
    if len(tables) < 2:
        _debug_dump(html, f"{kind}_{year}_{month:02d}_no_tables")
        raise RuntimeError(f"{kind} page missing expected tables for {year}-{month:02d}")

    return {
        "daily": _parse_daily_table(_html_to_text(tables[0]), unit),
        "monthly": _parse_monthly_table(_html_to_text(tables[1]), unit),
    }


def _open_detail_session(client: HttpClient, login_url: str) -> Dict[str, str]:
    mini_url = urljoin(login_url, "/app/ses_mini.do")
    mini_html, _, status = client.request(mini_url, referer=login_url)
    if status >= 400:
        raise RuntimeError(f"enecoQ mini iframe failed: HTTP {status}")
    token_match = re.search(r'name=["\']token["\']\s+value=["\']([^"\']+)["\']', mini_html)
    if not token_match:
        _debug_dump(mini_html, "mini_missing_token")
        raise RuntimeError("enecoQ mini token not found")

    detail_html, detail_url, status = client.request(
        "https://ses.me-eco.jp/mini/",
        data={"token": token_match.group(1), "GO": "GO"},
        referer=mini_url,
    )
    if status >= 400:
        raise RuntimeError(f"enecoQ mini session failed: HTTP {status}")
    return _session_from_detail_html(detail_url, detail_html)


def _session_from_detail_html(detail_url: str, detail_html: str) -> Dict[str, str]:
    query = parse_qs(urlparse(detail_url).query)
    session = {key: values[0] for key, values in query.items() if key in ("PHPSESSID", "svr_id") and values}
    for key in ("PHPSESSID", "svr_id"):
        if key not in session:
            match = re.search(rf'name=["\']{key}["\']\s+value=["\']([^"\']+)["\']', detail_html)
            if match:
                session[key] = match.group(1)
    if "PHPSESSID" not in session or "svr_id" not in session:
        _debug_dump(detail_html, "detail_missing_session")
        raise RuntimeError("enecoQ detail session parameters not found")
    return session


def _login(client: HttpClient, username: str, password: str, login_url: str) -> None:
    client.request(login_url)
    html, _, status = client.request(
        urljoin(login_url, "/app/xLogin.do"),
        data={"user_id": username, "password": password},
        referer=login_url,
    )
    if status >= 400 or "ログアウト" not in html:
        _debug_dump(html, "login_failed")
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
                    "low_jpy": round(cost["low"]),
                    "mid_jpy": round(cost["mid"]),
                    "high_jpy": round(cost["high"]),
                    "cost_jpy": round(cost["total"]),
                }
            )


def _merge_monthly(history: Dict[str, Dict[str, Any]], year: int, usage_rows: Dict[int, Dict[str, float]], cost_rows: Dict[int, Dict[str, float]]) -> None:
    for month, usage in usage_rows.items():
        key = f"{year:04d}-{month:02d}"
        row = history.setdefault("monthly", {}).setdefault(key, {"month": key})
        row["usage_kwh"] = usage["total"]
        cost = cost_rows.get(month)
        if cost:
            row["cost_jpy"] = round(cost["total"])


def _history_years() -> List[int]:
    now = datetime.now(TOKYO_TZ)
    return list(range(FIRST_HISTORY_YEAR, now.year + 1))


def _load_existing_history() -> Dict[str, Dict[str, Any]]:
    try:
        with open(OUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"daily": {}, "monthly": {}}
    except Exception as exc:
        log(f"existing history load failed, starting full refresh: {exc}")
        return {"daily": {}, "monthly": {}}

    daily = data.get("daily") if isinstance(data, dict) else None
    monthly = data.get("monthly") if isinstance(data, dict) else None
    if not isinstance(daily, list) or not isinstance(monthly, list):
        return {"daily": {}, "monthly": {}}
    return {
        "daily": {row["date"]: row for row in daily if isinstance(row, dict) and row.get("date")},
        "monthly": {row["month"]: row for row in monthly if isinstance(row, dict) and row.get("month")},
    }


def _months_to_fetch(has_history: bool, now: datetime) -> List[Tuple[int, int]]:
    if not has_history:
        months: List[Tuple[int, int]] = []
        for year in _history_years():
            last_month = now.month if year == now.year else 12
            months.extend((year, month) for month in range(1, last_month + 1))
        return months

    months_set: Set[Tuple[int, int]] = {(now.year, now.month)}
    previous_month = now.month - 1
    previous_year = now.year
    if previous_month < 1:
        previous_month = 12
        previous_year -= 1
    if previous_year >= FIRST_HISTORY_YEAR:
        months_set.add((previous_year, previous_month))
    return sorted(months_set)


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
    history = _load_existing_history()
    months_to_fetch = _months_to_fetch(bool(history["daily"] and history["monthly"]), now)

    client = HttpClient()
    log(f"open login page {login_url}")
    _login(client, username, password, login_url)
    log("login ok")
    session = _open_detail_session(client, login_url)
    log("enecoQ detail session ok")

    for year in sorted({year for year, _ in months_to_fetch}):
        months = [month for fetch_year, month in months_to_fetch if fetch_year == year]
        log(f"fetch year {year}")
        yearly_usage_rows: Dict[int, Dict[str, float]] = {}
        yearly_cost_rows: Dict[int, Dict[str, float]] = {}

        for month in months:
            log(f"fetch month {year}-{month:02d}")
            usage = _fetch_metric_page(client, "usage", year, month, session)
            cost = _fetch_metric_page(client, "cost", year, month, session)
            _merge_daily(history, year, month, usage["daily"], cost["daily"])
            yearly_usage_rows.update(usage["monthly"])
            yearly_cost_rows.update(cost["monthly"])

        _merge_monthly(history, year, yearly_usage_rows, yearly_cost_rows)

    daily_rows = [
        _round_jpy_fields(row)
        for _, row in sorted(history["daily"].items())
        if row.get("usage_kwh") is not None and row.get("cost_jpy") is not None
    ]
    monthly_rows = [
        _round_jpy_fields(row)
        for _, row in sorted(history["monthly"].items())
        if row.get("usage_kwh") is not None and row.get("cost_jpy") is not None
    ]

    total_usage = round(_combined_total(daily_rows, monthly_rows, "usage_kwh"), 6)
    total_cost = round(_combined_total(daily_rows, monthly_rows, "cost_jpy"))
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
