# Tokyo Water Monthly Scraper

Home Assistant add-on that logs in to the Tokyo Waterworks app API and writes water usage and charge history to:

```text
/share/tokyo_water_monthly.json
```

## Configuration

```yaml
username: "your-email@example.com"
password: "your-password"
interval_hours: 12
api_url: "https://api.suidoapp.waterworks.metro.tokyo.lg.jp/user"
debug: false
```

## Output

The JSON includes:

- `total_usage_m3`: monotonic total built from newly seen billing periods
- `total_charge_jpy`: monotonic total charge built from newly seen billing periods
- `latest`: latest billing period usage and charges
- `history`: all billing periods returned by the service
- `claim`: outstanding claim summary from the service
- `meter_detail`: latest meter-reading detail when available

## Example Home Assistant Sensors

```yaml
command_line:
  - sensor:
      name: Tokyo Water Total Usage
      unique_id: tokyo_water_total_usage
      command: "cat /share/tokyo_water_monthly.json"
      value_template: "{{ value_json.total_usage_m3 }}"
      unit_of_measurement: "m³"
      device_class: water
      state_class: total_increasing

  - sensor:
      name: Tokyo Water Total Charge
      unique_id: tokyo_water_total_charge
      command: "cat /share/tokyo_water_monthly.json"
      value_template: "{{ value_json.total_charge_jpy }}"
      unit_of_measurement: "JPY"
      state_class: total_increasing

  - sensor:
      name: Tokyo Water Latest Usage
      unique_id: tokyo_water_latest_usage
      command: "cat /share/tokyo_water_monthly.json"
      value_template: "{{ value_json.latest.usage_m3 }}"
      unit_of_measurement: "m³"
      device_class: water

  - sensor:
      name: Tokyo Water Latest Charge
      unique_id: tokyo_water_latest_charge
      command: "cat /share/tokyo_water_monthly.json"
      value_template: "{{ value_json.latest.total_charge_jpy }}"
      unit_of_measurement: "JPY"
```
