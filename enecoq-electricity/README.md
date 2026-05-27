# enecoQ Electricity Scraper

Home Assistant add-on that logs in to CYBERHOME/enecoQ, reads daily electricity usage/cost history, and exposes cumulative energy and cost totals suitable for Home Assistant Energy.

It is intended for CYBERHOME/enecoQ accounts where the logged-in page contains the enecoQ usage iframe.

## Install

Add this add-on repository in Home Assistant:

```text
https://github.com/SakuraiSatoru/enecoq-ha-addons
```

Home Assistant path:

```text
Settings -> Add-ons -> Add-on Store -> ... -> Repositories
```

Refresh the Add-on Store, open `enecoQ Electricity Scraper`, and install it.

## Configure

Set the add-on options:

```yaml
username: your-cyberhome-email@example.cyberhome.ne.jp
password: your-cyberhome-mail-password
interval_hours: 1
login_url: https://www.cyberhome.ne.jp/app/sslLogin.do
debug: false
```

Then start the add-on and enable `Start on boot`.

## Output

The JSON contains:

- `total_usage_kwh`
- `total_cost_jpy`
- `history_start`, `history_end`
- `daily`: daily usage/cost rows
- `monthly`: monthly usage/cost rows

The add-on writes the latest output to:

```text
/share/enecoq_electricity.json
```

The totals are calculated from scraped history. The first run performs a full history refresh; later runs reuse the saved history and refresh the current and previous month. If the account has monthly rows before daily rows are available, the add-on uses monthly rows for the older period and daily rows from the first available daily date onward.

## Home Assistant Sensors

Add these sensors to `configuration.yaml`:

```yaml
command_line:
  - sensor:
      name: enecoQ Total Usage
      unique_id: enecoq_total_usage
      command: "cat /share/enecoq_electricity.json"
      value_template: "{{ value_json.total_usage_kwh }}"
      unit_of_measurement: kWh
      device_class: energy
      state_class: total_increasing
      scan_interval: 300
  - sensor:
      name: enecoQ Total Cost
      unique_id: enecoq_total_cost
      command: "cat /share/enecoq_electricity.json"
      value_template: "{{ value_json.total_cost_jpy }}"
      unit_of_measurement: JPY
      device_class: monetary
      state_class: total
      scan_interval: 300
```

Restart Home Assistant Core after changing `configuration.yaml`.

## Energy Dashboard

In Home Assistant Energy:

- Electricity grid consumption: `enecoQ Total Usage`
- Return to grid: leave empty unless you have a separate export sensor
- Cost tracking: choose `Use an entity tracking total costs`
- Cost entity: `enecoQ Total Cost`
- Power measurement type: `No power sensor`

## Why Total Instead of Today or Month

enecoQ exposes daily and monthly usage pages. This add-on turns the scraped daily history into cumulative totals:

- `total_usage_kwh` is the cumulative scraped kWh total.
- `total_cost_jpy` is the cumulative scraped JPY total.
- The `daily` array can also be used to backfill Home Assistant recorder statistics.

This makes the sensor behave like a normal electricity meter, which is the cleanest shape for Home Assistant Energy.

## Troubleshooting

Check the add-on log first. A successful run should include:

```text
login ok
enecoQ detail session ok
fetch year 2026
wrote /share/enecoq_electricity.json
```

If Home Assistant Energy does not show the sensors immediately, wait a few minutes or restart Home Assistant Core after adding the `command_line` sensors.

If the add-on fails to parse the page, enable `debug: true` and restart the add-on. Then inspect the add-on logs and generated debug artifacts.
