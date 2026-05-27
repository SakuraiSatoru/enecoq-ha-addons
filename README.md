# enecoQ Home Assistant Add-ons

Home Assistant add-on repository for enecoQ electricity usage scraping.

## Add to Home Assistant

After this repository is pushed to GitHub, add this URL in Home Assistant:

```text
https://github.com/SakuraiSatoru/enecoq-ha-addons
```

Home Assistant path:

```text
Settings -> Add-ons -> Add-on Store -> ... -> Repositories
```

## Add-ons

### enecoQ Electricity Scraper

Scrapes enecoQ daily and monthly electricity usage and writes:

```text
/share/enecoq_electricity.json
```

The add-on uses the upstream `enecoq-data-fetcher` Python package for login and scraping.
