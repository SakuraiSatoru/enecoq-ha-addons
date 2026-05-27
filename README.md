# enecoQ Home Assistant Add-ons

Home Assistant add-on repository for scraping enecoQ electricity usage and exposing it to Home Assistant Energy.

## Add to Home Assistant

Add this repository URL in Home Assistant:

```text
https://github.com/SakuraiSatoru/enecoq-ha-addons
```

Home Assistant path:

```text
Settings -> Add-ons -> Add-on Store -> ... -> Repositories
```

After adding the repository, refresh the Add-on Store and install `enecoQ Electricity Scraper`.

## Add-ons

### enecoQ Electricity Scraper

Logs in to CYBERHOME/enecoQ, fetches the current monthly usage and cost, then maintains monotonic totals for Home Assistant:

- `enecoQ Total Usage`
- `enecoQ Total Cost`

The add-on uses the upstream `enecoq-data-fetcher` Python package for login and scraping.

For configuration and Energy Dashboard setup, see [the add-on README](enecoq-electricity/README.md).
