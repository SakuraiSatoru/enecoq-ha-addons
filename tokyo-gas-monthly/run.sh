#!/usr/bin/env sh
set -eu

echo "[tokyo-gas] Tokyo Gas Monthly Scraper starting..."

USERNAME="$(python -c "import json; print(json.load(open('/data/options.json')).get('username',''))")"
PASSWORD="$(python -c "import json; print(json.load(open('/data/options.json')).get('password',''))")"
INTERVAL_HOURS="$(python -c "import json; print(json.load(open('/data/options.json')).get('interval_hours',12))")"

if [ -z "${USERNAME}" ] || [ -z "${PASSWORD}" ]; then
  echo "[tokyo-gas] ERROR: username/password not set in add-on config"
  exit 1
fi

export TG_USERNAME="${USERNAME}"
export TG_PASSWORD="${PASSWORD}"

case "${INTERVAL_HOURS}" in
  ''|*[!0-9]*) INTERVAL_HOURS=12 ;;
esac

SLEEP_SEC=$(( INTERVAL_HOURS * 3600 ))

run_scrape() {
  Xvfb :99 -screen 0 1365x900x24 >/tmp/tokyo-gas-xvfb.log 2>&1 &
  XVFB_PID="$!"
  export DISPLAY=:99

  trap 'kill "${XVFB_PID}" 2>/dev/null || true' EXIT INT TERM
  python /app/tg_scrape.py
  RESULT="$?"
  kill "${XVFB_PID}" 2>/dev/null || true
  trap - EXIT INT TERM
  return "${RESULT}"
}

while true; do
  echo "[tokyo-gas] scraping..."
  run_scrape && echo "[tokyo-gas] scrape ok" || echo "[tokyo-gas] scrape failed"
  echo "[tokyo-gas] sleep ${INTERVAL_HOURS}h"
  sleep "${SLEEP_SEC}"
done
