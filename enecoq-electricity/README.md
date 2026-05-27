# enecoQ Electricity Scraper

Home Assistant add-on that logs in to CYBERHOME/enecoQ, reads this month's electricity data, and maintains a monotonic total suitable for Home Assistant Energy.

```text
/share/enecoq_electricity.json
```

The JSON contains:

- `total_usage_kwh`
- `last_delta_kwh`
- `month_usage_kwh`, `month_cost_jpy`, `month_co2_kg`

Example Home Assistant sensors:

```yaml
command_line:
  - sensor:
      name: enecoQ Total Usage
      command: "cat /share/enecoq_electricity.json"
      value_template: "{{ value_json.total_usage_kwh }}"
      unit_of_measurement: kWh
      device_class: energy
      state_class: total_increasing
      scan_interval: 300
```

The add-on stores its persistent total state in `/data/enecoq_electricity_state.json`.
