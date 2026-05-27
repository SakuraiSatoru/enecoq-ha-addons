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
TOKYO_TZ = ZoneInfo("Asia/Tokyo")


def log(message: str) -> None:
    print(f"[enecoq] {message}", flush=True)


def _ensure_share() -> None:
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)


def _debug_enabled() -> bool:
    return str(os.environ.get("ENECOQ_DEBUG", "")).lower() in ("1", "true", "yes", "on")


def _normalize_period(raw: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(TOKYO_TZ)
    period = str(raw["period"])
    return {
        "period": period,
        "date": now.date().isoformat() if period == "today" else now.strftime("%Y-%m"),
        "timestamp": raw["timestamp"],
        "usage_kwh": raw["usage"],
        "cost_jpy": raw["cost"],
        "co2_kg": raw["co2"],
    }


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

    today_raw = client.fetch_power_data(
        period="today",
        output_format="json",
        output_path="/tmp/enecoq_today.json",
    ).to_dict()
    month_raw = client.fetch_power_data(
        period="month",
        output_format="json",
        output_path="/tmp/enecoq_month.json",
    ).to_dict()
    today = _normalize_period(today_raw)
    month = _normalize_period(month_raw)
    fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "source": "enecoq",
        "fetched_at": fetched_at,
        "timezone": "Asia/Tokyo",
        "today": today,
        "month": month,
        "latest_today_usage_kwh": today["usage_kwh"],
        "latest_today_cost_jpy": today["cost_jpy"],
        "current_month_usage_kwh": month["usage_kwh"],
        "current_month_cost_jpy": month["cost_jpy"],
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
