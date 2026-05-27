# enecoQ Electricity Scraper

Home Assistant add-on that logs in to CYBERHOME/enecoQ, reads today's and this month's electricity data, and writes:

```text
/share/enecoq_electricity.json
```

The JSON contains:

- `today.usage_kwh`, `today.cost_jpy`, `today.co2_kg`
- `month.usage_kwh`, `month.cost_jpy`, `month.co2_kg`
- Flat aliases such as `latest_today_usage_kwh` and `current_month_usage_kwh`

Example Home Assistant sensors:

```yaml
command_line:
  - sensor:
      name: enecoQ Today Usage
      command: "cat /share/enecoq_electricity.json"
      value_template: "{{ value_json.today.usage_kwh }}"
      unit_of_measurement: kWh
      device_class: energy
      state_class: total_increasing
      scan_interval: 300

  - sensor:
      name: enecoQ Month Usage
      command: "cat /share/enecoq_electricity.json"
      value_template: "{{ value_json.month.usage_kwh }}"
      unit_of_measurement: kWh
      device_class: energy
      state_class: total_increasing
      scan_interval: 300

  - sensor:
      name: enecoQ Today Cost
      command: "cat /share/enecoq_electricity.json"
      value_template: "{{ value_json.today.cost_jpy }}"
      unit_of_measurement: JPY
      device_class: monetary
      state_class: total_increasing
      scan_interval: 300
```

Enable `debug` in the add-on options to write failure HTML and screenshots to `/share/enecoq_*.html` and `/share/enecoq_*.png`.
