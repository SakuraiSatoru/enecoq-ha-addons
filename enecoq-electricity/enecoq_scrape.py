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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

from enecoq_data_fetcher import config as config_module
from enecoq_data_fetcher import controller
from enecoq_data_fetcher import logger


DEFAULT_LOGIN_URL = "https://www.cyberhome.ne.jp/app/sslLogin.do"
OUT_JSON = "/share/enecoq_electricity.json"
STATE_JSON = "/data/enecoq_electricity_state.json"
TOKYO_TZ = ZoneInfo("Asia/Tokyo")


def log(message: str) -> None:
    print(f"[enecoq] {message}", flush=True)


def _ensure_share() -> None:
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)


def _debug_enabled() -> bool:
    return str(os.environ.get("ENECOQ_DEBUG", "")).lower() in ("1", "true", "yes", "on")


def _normalize_period(raw: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(TOKYO_TZ)
    return {
        "period": str(raw["period"]),
        "month": now.strftime("%Y-%m"),
        "timestamp": raw["timestamp"],
        "usage_kwh": raw["usage"],
        "cost_jpy": raw["cost"],
        "co2_kg": raw["co2"],
    }


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


def _update_total(month: Dict[str, Any]) -> Dict[str, Any]:
    state = _load_state()
    month_key = str(month["month"])
    month_usage = float(month["usage_kwh"])
    month_cost = float(month["cost_jpy"])

    total_usage = float(state.get("total_usage_kwh") or 0.0)
    total_cost = float(state.get("total_cost_jpy") or 0.0)
    last_month_key = state.get("last_month")
    last_month_usage = state.get("last_month_usage_kwh")
    last_month_cost = state.get("last_month_cost_jpy")

    if last_month_usage is None:
        usage_delta = month_usage
        reason = "initial"
    elif last_month_key == month_key:
        usage_delta = month_usage - float(last_month_usage)
        reason = "same_month"
    else:
        usage_delta = month_usage
        reason = "new_month"

    if last_month_cost is None:
        cost_delta = month_cost
    elif last_month_key == month_key:
        cost_delta = month_cost - float(last_month_cost)
    else:
        cost_delta = month_cost

    if usage_delta < 0:
        log(f"negative monthly usage delta ignored: {usage_delta}")
        usage_delta = 0.0
        reason = "ignored_negative_delta"
    if cost_delta < 0:
        log(f"negative monthly cost delta ignored: {cost_delta}")
        cost_delta = 0.0
        reason = "ignored_negative_delta"

    total_usage += usage_delta
    total_cost += cost_delta
    new_state = {
        "total_usage_kwh": round(total_usage, 6),
        "total_cost_jpy": round(total_cost, 2),
        "last_month": month_key,
        "last_month_usage_kwh": month_usage,
        "last_month_cost_jpy": month_cost,
        "last_update_reason": reason,
        "last_delta_kwh": round(usage_delta, 6),
        "last_cost_delta_jpy": round(cost_delta, 2),
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_json(STATE_JSON, new_state)
    return new_state


def scrape(username: str, password: str, login_url: str) -> Dict[str, Any]:
    # The upstream package hard-codes the CYBERHOME login URL. Keep the add-on
    # option for future compatibility, but use the verified repo method by default.
    if login_url != DEFAULT_LOGIN_URL:
        log(f"custom login_url is ignored by upstream fetcher: {login_url}")

    config = config_module.Config(
        log_level="DEBUG" if _debug_enabled() else "INFO",
        timeout=45,
        max_retries=3,
    )
    logger.setup_logger(log_level=config.log_level)
    client = controller.EnecoQController(username, password, config=config)

    month_raw = client.fetch_power_data(
        period="month",
        output_format="json",
        output_path="/tmp/enecoq_month.json",
    ).to_dict()
    month = _normalize_period(month_raw)
    total_state = _update_total(month)
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "enecoq",
        "fetched_at": fetched_at,
        "timezone": "Asia/Tokyo",
        "total_usage_kwh": total_state["total_usage_kwh"],
        "total_cost_jpy": total_state["total_cost_jpy"],
        "last_delta_kwh": total_state["last_delta_kwh"],
        "last_cost_delta_jpy": total_state["last_cost_delta_jpy"],
        "month_usage_kwh": month["usage_kwh"],
        "month_cost_jpy": month["cost_jpy"],
        "month_co2_kg": month["co2_kg"],
        "month": month["month"],
        "last_update_reason": total_state["last_update_reason"],
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
