# -*- coding: utf-8 -*-
"""
Tokyo Gas (myTOKYOGAS) monthly gas usage scraper.

Outputs:
  /share/tokyo_gas_monthly.json

Env:
  TG_USERNAME
  TG_PASSWORD
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_URL = "https://members.tokyo-gas.co.jp"
URL_LOGIN = f"{BASE_URL}/login.html"
URL_USAGE = f"{BASE_URL}/usage"
URL_GRAPHQL = f"{BASE_URL}/graphql"

OUT_JSON = "/share/tokyo_gas_monthly.json"

MAX_RETRY = 4
RETRY_SLEEP_SEC = 2
PAGELOAD_TIMEOUT = 90
WAIT_TIMEOUT = 45


USAGE_CONTRACT_QUERY = """
query UsageContract($contractIndexNumber: Int!) {
  electricityContracts(contractIndexNumber: $contractIndexNumber) {
    electricityContractNumber
    electricitySupplyNumber
    endDate
  }
}
"""

MONTHLY_GAS_USAGE_QUERY = """
query MonthlyGasUsage($contractIndexNumber: Int!) {
  monthlyGasUsage(contractIndexNumber: $contractIndexNumber) {
    averageUsageForSameContract
    charge
    date
    startDate
    endDate
    usage
  }
}
"""


def _ensure_share() -> None:
    os.makedirs("/share", exist_ok=True)


def dump_debug(driver: webdriver.Chrome, tag: str) -> None:
    _ensure_share()
    try:
        with open(f"/share/tokyogas_{tag}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
    except Exception:
        pass
    try:
        driver.save_screenshot(f"/share/tokyogas_{tag}.png")
    except Exception:
        pass


def log(message: str) -> None:
    print(f"[tokyo-gas] {message}", flush=True)


def make_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1365,900")
    options.add_argument("--lang=ja-JP")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.binary_location = "/usr/bin/chromium-browser"

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGELOAD_TIMEOUT)

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
    except Exception:
        pass

    return driver


def _wait_dom_ready(driver: webdriver.Chrome, timeout: int = WAIT_TIMEOUT) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )


def _click_first(driver: webdriver.Chrome, selectors: List[str], timeout: int = 8) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed() and el.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        return True
            except Exception:
                pass
        time.sleep(0.25)
    return False


def _click_button_by_text(driver: webdriver.Chrome, texts: List[str], timeout: int = 8) -> bool:
    end = time.time() + timeout
    xpath = " | ".join(
        [
            f"//button[contains(normalize-space(.), '{text}')]"
            f" | //input[(contains(@value, '{text}') or contains(@aria-label, '{text}'))]"
            f" | //a[contains(normalize-space(.), '{text}')]"
            for text in texts
        ]
    )
    while time.time() < end:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def _find_text_input(driver: webdriver.Chrome, password: bool = False):
    css = "input[type='password']" if password else (
        "input[type='email'], input[type='text'], input:not([type]), "
        "input[name*='login' i], input[name*='mail' i], input[name*='user' i], "
        "input[id*='login' i], input[id*='mail' i], input[id*='user' i]"
    )
    return WebDriverWait(driver, WAIT_TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))


def _describe_login_dom(driver: webdriver.Chrome) -> None:
    try:
        items = driver.execute_script(
            """
            const vis = (e) => {
              const r = e.getBoundingClientRect();
              const s = getComputedStyle(e);
              return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
            };
            return Array.from(document.querySelectorAll('input, button, a')).filter(vis).slice(0, 30).map((e) => ({
              tag: e.tagName.toLowerCase(),
              type: e.getAttribute('type'),
              name: e.getAttribute('name'),
              id: e.id,
              placeholder: e.getAttribute('placeholder'),
              autocomplete: e.getAttribute('autocomplete'),
              text: (e.innerText || e.value || '').trim().slice(0, 40),
            }));
            """
        )
        log("visible login controls: " + json.dumps(items, ensure_ascii=False))
    except Exception as exc:
        log(f"visible login controls unavailable: {exc}")


def _extract_contract_index(driver: webdriver.Chrome) -> int:
    candidates: List[str] = []

    for storage in ("localStorage", "sessionStorage"):
        try:
            data = driver.execute_script(
                """
                const out = [];
                for (let i = 0; i < window[arguments[0]].length; i++) {
                  const k = window[arguments[0]].key(i);
                  out.push(k + "=" + window[arguments[0]].getItem(k));
                }
                return out;
                """,
                storage,
            )
            candidates.extend(str(item) for item in data)
        except Exception:
            pass

    candidates.append(driver.current_url)
    candidates.append(driver.page_source[:500000])

    patterns = [
        r"contractIndexNumber[\"'=:\s]+(\d+)",
        r"contract_index_number[\"'=:\s]+(\d+)",
        r"contractIndexNumber=(\d+)",
    ]
    for text in candidates:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))

    return 0


def _graphql(driver: webdriver.Chrome, operation_name: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    result = driver.execute_async_script(
        """
        const [url, operationName, query, variables, done] = arguments;
        fetch(url, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'content-type': 'application/json',
            'accept': 'application/json'
          },
          body: JSON.stringify({operationName, query, variables})
        }).then(async (response) => {
          const text = await response.text();
          done({status: response.status, text});
        }).catch((error) => done({status: 0, text: String(error)}));
        """,
        URL_GRAPHQL,
        operation_name,
        query,
        variables,
    )
    status = int(result.get("status") or 0)
    text = result.get("text") or ""
    if status < 200 or status >= 300:
        raise RuntimeError(f"GraphQL {operation_name} failed: HTTP {status}: {text[:500]}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GraphQL {operation_name} returned non-JSON: {text[:500]}") from exc
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL {operation_name} errors: {payload['errors']}")
    return payload.get("data") or {}


def _first_number(item: Dict[str, Any], keys: List[str]) -> Optional[float]:
    for key in keys:
        value = item.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def _month_from_item(item: Dict[str, Any]) -> Optional[str]:
    for key in ("targetDate", "targetMonth", "month", "date", "yearMonth", "startDate", "endDate"):
        value = item.get(key)
        if not value:
            continue
        text = str(value)
        match = re.search(r"(\d{4})[-/年](\d{1,2})", text)
        if match:
            return f"{int(match.group(1)):04d}/{int(match.group(2)):02d}"
    return None


def _normalize_monthly(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        for key in ("items", "usages", "monthly", "nodes", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise RuntimeError(f"Unexpected monthlyGasUsage shape: {type(raw).__name__}")

    monthly = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        month = _month_from_item(item)
        if not month:
            continue
        usage = _first_number(item, ["usage", "gasUsage", "amount", "gasAmount", "value"])
        payment = _first_number(item, ["payment", "charge", "gasCharge", "fee", "price"])
        row: Dict[str, Any] = {"month": month}
        if usage is not None:
            row["usage_m3"] = usage
        if payment is not None:
            row["payment"] = int(payment) if payment.is_integer() else payment
        row["raw"] = item
        monthly.append(row)

    monthly.sort(key=lambda row: row["month"])
    if not monthly:
        raise RuntimeError(f"No usable monthly gas rows in response: {json.dumps(raw, ensure_ascii=False)[:1000]}")
    return monthly


class MyTokyoGas:
    def __init__(self, username: str, password: str):
        self._driver = make_driver()
        last_err = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                log(f"login attempt {attempt}")
                self._login(username, password)
                return
            except Exception as exc:
                last_err = exc
                log(f"login attempt {attempt} failed at {self._driver.current_url}: {exc}")
                dump_debug(self._driver, f"login_fail_try{attempt}")
                time.sleep(RETRY_SLEEP_SEC * attempt)
        raise RuntimeError(f"Login failed after retries: {last_err}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.quit()
        return False

    def quit(self) -> None:
        try:
            self._driver.quit()
        except Exception:
            pass

    def _login(self, username: str, password: str) -> None:
        d = self._driver
        log(f"open login page {URL_LOGIN}")
        d.get(URL_LOGIN)
        _wait_dom_ready(d)
        log(f"login page loaded: {d.current_url}")

        log("waiting for login inputs")
        _describe_login_dom(d)
        user_el = _find_text_input(d)
        pass_el = _find_text_input(d, password=True)
        user_el.clear()
        user_el.send_keys(username)
        pass_el.clear()
        pass_el.send_keys(password)

        for checkbox in d.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"):
            if checkbox.is_displayed() and checkbox.is_enabled() and not checkbox.is_selected():
                driver_click = "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();"
                d.execute_script(driver_click, checkbox)
                break

        if not (_click_first(d, ["#submit-btn"], timeout=3) or _click_button_by_text(d, ["ログイン"], timeout=5) or _click_first(d, [
            "button[type='submit']",
            "input[type='submit']",
            "button",
        ], timeout=10)):
            raise RuntimeError("Login button not found")

        log("submitted login form")
        WebDriverWait(d, WAIT_TIMEOUT).until(lambda x: "login.tokyo-gas.co.jp" not in x.current_url)
        _wait_dom_ready(d)
        log(f"after login redirect: {d.current_url}")

        if "/2fa/" in d.current_url or "認証コード" in d.page_source:
            raise RuntimeError("Two-factor authentication is required; cannot continue unattended")
        if "/errors/" in d.current_url:
            raise RuntimeError(f"Login redirected to error page: {d.current_url}")

        d.get(URL_USAGE)
        _wait_dom_ready(d)
        WebDriverWait(d, WAIT_TIMEOUT).until(lambda x: "/login" not in x.current_url)
        log(f"usage page loaded: {d.current_url}")
        if "/login" in d.current_url:
            raise RuntimeError("Login did not persist; redirected back to login")

    def fetch_usage_monthly(self) -> Dict[str, Any]:
        d = self._driver
        last_err = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                d.get(URL_USAGE)
                _wait_dom_ready(d)

                contract_index = _extract_contract_index(d)
                if not contract_index:
                    contract_index = 0

                if contract_index:
                    try:
                        _graphql(d, "UsageContract", USAGE_CONTRACT_QUERY, {"contractIndexNumber": contract_index})
                    except Exception:
                        pass

                data = _graphql(
                    d,
                    "MonthlyGasUsage",
                    MONTHLY_GAS_USAGE_QUERY,
                    {"contractIndexNumber": contract_index},
                )
                monthly = _normalize_monthly(data.get("monthlyGasUsage"))
                latest = monthly[-1]
                return {
                    "contract_index_number": contract_index,
                    "latest_month": latest.get("month"),
                    "latest_usage_m3": latest.get("usage_m3"),
                    "latest_payment": latest.get("payment"),
                    "monthly": monthly,
                }
            except Exception as exc:
                last_err = exc
                dump_debug(d, f"usage_fail_try{attempt}")
                time.sleep(RETRY_SLEEP_SEC * attempt)
        raise RuntimeError(f"Usage fetch failed after retries: {last_err}")


def main() -> None:
    username = os.environ["TG_USERNAME"]
    password = os.environ["TG_PASSWORD"]

    _ensure_share()
    with MyTokyoGas(username, password) as tg:
        data = tg.fetch_usage_monthly()

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": data,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[tokyo-gas] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
