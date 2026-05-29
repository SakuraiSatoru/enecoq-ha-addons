# enecoQ Home Assistant Add-ons

Home Assistant add-on repository for scraping utility usage and exposing it to Home Assistant.

## Add to Home Assistant

Add this repository URL in Home Assistant:

```text
https://github.com/SakuraiSatoru/enecoq-ha-addons
```

Home Assistant path:

```text
Settings -> Add-ons -> Add-on Store -> ... -> Repositories
```

After adding the repository, refresh the Add-on Store and install the scraper add-on you need.

## Home Assistant Access

This Codex project can access the Home Assistant host over SSH:

```text
ssh root@10.10.10.24
```

## Add-ons

### enecoQ Electricity Scraper

Logs in to CYBERHOME/enecoQ, fetches the current monthly usage and cost, then maintains monotonic totals for Home Assistant:

- `enecoQ Total Usage`
- `enecoQ Total Cost`

The add-on uses a lightweight HTTP session for login and scraping, without a bundled browser.

For configuration and Energy Dashboard setup, see [the add-on README](enecoq-electricity/README.md).

### Tokyo Water Monthly Scraper

Logs in to the Tokyo Waterworks app API, fetches billing-period water usage and charges, then writes:

```text
/share/tokyo_water_monthly.json
```

For configuration and sensor examples, see [the add-on README](tokyo-water-monthly/README.md).
