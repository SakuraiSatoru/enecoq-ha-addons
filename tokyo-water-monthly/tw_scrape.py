# -*- coding: utf-8 -*-
"""
Tokyo Waterworks app usage and charge scraper.

Outputs:
  /share/tokyo_water_monthly.json

Env:
  TW_USERNAME
  TW_PASSWORD
  TW_API_URL
  TW_DEBUG
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://api.suidoapp.waterworks.metro.tokyo.lg.jp/user"
OUT_JSON = "/share/tokyo_water_monthly.json"
STATE_JSON = "/data/tokyo_water_monthly_state.json"

MAX_RETRY = 4
RETRY_SLEEP_SEC = 2
REQUEST_TIMEOUT = 45


class TokyoWaterError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[tokyo-water] {message}", flush=True)


def _debug_enabled() -> bool:
    return str(os.environ.get("TW_DEBUG", "")).lower() in ("1", "true", "yes", "on")


def _ensure_share() -> None:
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)


def _to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _period_id(row: Dict[str, Any]) -> str:
    jisseki_id = str(row.get("remark2") or "").strip()
    if jisseki_id:
        return jisseki_id
    return f"{row.get('seiDateStart') or ''}-{row.get('seiDateEnd') or ''}"


def _normalize_used_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "period_id": _period_id(row),
        "period_start": row.get("seiDateStart"),
        "period_end": row.get("seiDateEnd"),
        "usage_start_label": row.get("usageStartDate"),
        "usage_end_label": row.get("usageEndDate"),
        "usage_m3": _to_int(row.get("sryo")),
        "water_charge_jpy": _to_int(row.get("jysChAm")),
        "sewer_charge_jpy": _to_int(row.get("gesChAm")),
        "total_charge_jpy": _to_int(row.get("toChAm")),
        "payment_status_amount_jpy": _to_int(row.get("remark1")),
        "meter_detail_id": row.get("remark2"),
        "raw": row,
    }


def _sort_key(row: Dict[str, Any]) -> str:
    return f"{row.get('period_start') or ''}-{row.get('period_end') or ''}-{row.get('period_id') or ''}"


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


def _load_state() -> Dict[str, Any]:
    try:
        with open(STATE_JSON, "r", encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            return state
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"state load failed, starting fresh: {exc}")
    return {}


def _update_total(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = _load_state()
    seen = set(str(item) for item in state.get("seen_period_ids") or [])
    total_usage = float(state.get("total_usage_m3") or 0.0)
    total_charge = float(state.get("total_charge_jpy") or 0.0)
    added_periods: List[str] = []

    for row in sorted(rows, key=_sort_key):
        period_id = str(row.get("period_id") or "")
        if not period_id or period_id in seen:
            continue
        usage = row.get("usage_m3")
        charge = row.get("total_charge_jpy")
        if usage is not None:
            total_usage += float(usage)
        if charge is not None:
            total_charge += float(charge)
        seen.add(period_id)
        added_periods.append(period_id)

    new_state = {
        "total_usage_m3": round(total_usage, 6),
        "total_charge_jpy": round(total_charge, 2),
        "seen_period_ids": sorted(seen),
        "last_added_period_ids": added_periods,
        "last_delta_m3": round(
            sum(float(row["usage_m3"]) for row in rows if row.get("period_id") in added_periods and row.get("usage_m3") is not None),
            6,
        ),
        "last_charge_delta_jpy": round(
            sum(float(row["total_charge_jpy"]) for row in rows if row.get("period_id") in added_periods and row.get("total_charge_jpy") is not None),
            2,
        ),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_json(STATE_JSON, new_state)
    return new_state


class TokyoWaterClient:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")
        self.token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.api_url + path
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})

        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = self.token

        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TokyoWaterError(f"HTTP {exc.code} {path}: {body[:500]}") from exc
        except URLError as exc:
            raise TokyoWaterError(f"network error {path}: {exc}") from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TokyoWaterError(f"non-JSON response {path}: {body[:500]}") from exc

        if not isinstance(result, dict):
            raise TokyoWaterError(f"unexpected response {path}: {type(result).__name__}")

        if result.get("token"):
            self.token = str(result["token"])
        if result.get("refreshToken"):
            self.refresh_token = str(result["refreshToken"])

        code = result.get("result") or result.get("errorCode")
        if code and code != "00000":
            raise TokyoWaterError(f"API {path} returned result {code}")
        return result

    def login(self, username: str, password: str) -> Dict[str, Any]:
        result = self._request("POST", "/auth/login", {"loginId": username, "password": password})
        if not self.token:
            raise TokyoWaterError("login response did not include token")
        return result

    def get_user(self) -> Dict[str, Any]:
        return self._request("GET", "/userdata").get("data") or {}

    def get_usage_data(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/usagedata").get("data") or []
        if not isinstance(data, list):
            raise TokyoWaterError(f"unexpected /usagedata shape: {type(data).__name__}")
        return data

    def get_used_data(self, w_key: str) -> List[Dict[str, Any]]:
        data = self._request("GET", f"/useddata/{w_key}").get("data") or []
        if not isinstance(data, list):
            raise TokyoWaterError(f"unexpected /useddata shape: {type(data).__name__}")
        return data

    def get_claim(self, w_key: str) -> Dict[str, Any]:
        return self._request("GET", f"/claim/{w_key}").get("data") or {}

    def get_meter_detail(self, w_key: str, jisseki_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not jisseki_id:
            return None
        try:
            return self._request("GET", f"/meterdata/{w_key}", params={"jisseki_id": jisseki_id}).get("data") or {}
        except TokyoWaterError as exc:
            log(f"meter detail fetch failed for {jisseki_id}: {exc}")
            return None


def _selected_contract(user: Dict[str, Any], usage_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not usage_data:
        raise TokyoWaterError("no water contracts returned by /usagedata")
    default_w_key = user.get("dwKey")
    for item in usage_data:
        if default_w_key and item.get("wKey") == default_w_key:
            return item
    return usage_data[0]


def scrape(username: str, password: str, api_url: str) -> Dict[str, Any]:
    client = TokyoWaterClient(api_url)
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            log(f"login attempt {attempt}")
            login_data = client.login(username, password).get("data") or {}
            user = client.get_user()
            usage_data = client.get_usage_data()
            contract = _selected_contract(user, usage_data)
            w_key = contract.get("wKey")
            if not w_key:
                raise TokyoWaterError("selected contract has no wKey")

            used_rows = [_normalize_used_row(row) for row in client.get_used_data(str(w_key))]
            used_rows.sort(key=_sort_key, reverse=True)
            latest = used_rows[0] if used_rows else None
            claim = client.get_claim(str(w_key))
            meter_detail = client.get_meter_detail(str(w_key), latest.get("meter_detail_id") if latest else None)
            total_state = _update_total(used_rows)

            payload: Dict[str, Any] = {
                "source": "tokyo_water",
                "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "api_url": api_url,
                "account_status": login_data.get("userStatus") or user.get("userStatus"),
                "contract": {
                    "w_key": w_key,
                    "w_number": contract.get("wNumber"),
                    "b_number": contract.get("bNumber"),
                    "status": contract.get("wStatus"),
                    "meter_kind": contract.get("meterKbn"),
                    "contractor": contract.get("wContractor"),
                    "address": "".join(
                        str(contract.get(key) or "")
                        for key in ("address1", "address2", "address3", "address4", "address5", "address6", "address7", "address8")
                    ),
                },
                "total_usage_m3": total_state["total_usage_m3"],
                "total_charge_jpy": total_state["total_charge_jpy"],
                "last_delta_m3": total_state["last_delta_m3"],
                "last_charge_delta_jpy": total_state["last_charge_delta_jpy"],
                "latest": latest,
                "claim": claim,
                "meter_detail": meter_detail,
                "history": used_rows,
            }
            if not _debug_enabled():
                payload.pop("api_url", None)
            return payload
        except Exception as exc:
            last_err = exc
            log(f"scrape attempt {attempt} failed: {exc}")
            time.sleep(RETRY_SLEEP_SEC * attempt)
    raise TokyoWaterError(f"scrape failed after retries: {last_err}")


def main() -> None:
    username = os.environ["TW_USERNAME"]
    password = os.environ["TW_PASSWORD"]
    api_url = os.environ.get("TW_API_URL") or DEFAULT_API_URL

    _ensure_share()
    payload = scrape(username, password, api_url)
    atomic_write_json(OUT_JSON, payload)
    log(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
