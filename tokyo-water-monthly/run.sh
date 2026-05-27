#!/usr/bin/env sh
set -eu

echo "[tokyo-water] Tokyo Water Monthly Scraper starting..."

opt() {
  python -c "import json,sys; data=json.load(open('/data/options.json')); print(data.get(sys.argv[1], sys.argv[2]))" "$1" "$2"
}

USERNAME="$(opt username '')"
PASSWORD="$(opt password '')"
INTERVAL_HOURS="$(opt interval_hours 12)"
API_URL="$(opt api_url 'https://api.suidoapp.waterworks.metro.tokyo.lg.jp/user')"
DEBUG="$(opt debug false)"

if [ -z "${USERNAME}" ] || [ -z "${PASSWORD}" ]; then
  echo "[tokyo-water] ERROR: username/password not set in add-on config"
  exit 1
fi

case "${INTERVAL_HOURS}" in
  ''|*[!0-9]*) INTERVAL_HOURS=12 ;;
esac

export TW_USERNAME="${USERNAME}"
export TW_PASSWORD="${PASSWORD}"
export TW_API_URL="${API_URL}"
export TW_DEBUG="${DEBUG}"

SLEEP_SEC=$(( INTERVAL_HOURS * 3600 ))

run_scrape() {
  python /app/tw_scrape.py
}

while true; do
  echo "[tokyo-water] scraping..."
  run_scrape && echo "[tokyo-water] scrape ok" || echo "[tokyo-water] scrape failed"
  echo "[tokyo-water] sleep ${INTERVAL_HOURS}h"
  sleep "${SLEEP_SEC}"
done
