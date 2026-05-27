#!/usr/bin/env sh
set -eu

echo "[enecoq] enecoQ Electricity Scraper starting..."

opt() {
  python -c "import json,sys; data=json.load(open('/data/options.json')); print(data.get(sys.argv[1], sys.argv[2]))" "$1" "$2"
}

USERNAME="$(opt username '')"
PASSWORD="$(opt password '')"
INTERVAL_HOURS="$(opt interval_hours 6)"
LOGIN_URL="$(opt login_url 'https://www.cyberhome.ne.jp/app/sslLogin.do')"
DEBUG="$(opt debug false)"

if [ -z "${USERNAME}" ] || [ -z "${PASSWORD}" ]; then
  echo "[enecoq] ERROR: username/password not set in add-on config"
  exit 1
fi

case "${INTERVAL_HOURS}" in
  ''|*[!0-9]*) INTERVAL_HOURS=6 ;;
esac

export ENECOQ_USERNAME="${USERNAME}"
export ENECOQ_PASSWORD="${PASSWORD}"
export ENECOQ_LOGIN_URL="${LOGIN_URL}"
export ENECOQ_DEBUG="${DEBUG}"

SLEEP_SEC=$(( INTERVAL_HOURS * 3600 ))

run_scrape() {
  python /app/enecoq_scrape.py
}

while true; do
  echo "[enecoq] scraping..."
  run_scrape && echo "[enecoq] scrape ok" || echo "[enecoq] scrape failed"
  echo "[enecoq] sleep ${INTERVAL_HOURS}h"
  sleep "${SLEEP_SEC}"
done
