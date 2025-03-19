# Google Analytics Extractor

[![PyPI version](https://badge.fury.io/py/ga-extractor.svg)](https://badge.fury.io/py/ga-extractor)

A CLI tool for extracting Google Analytics 4 data using Google Analytics Data API. Can be also used to transform data to various formats suitable for migration to other analytics platforms.

Also see - [Goodbye, Google Analytics - Why and How You Should Leave The Platform](https://martinheinz.dev/blog/71) for more context.

-----

If you find this useful, you can support me on Ko-Fi (Donations are always appreciated, but never required):

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K3K6F4XN6)

## Setup

You will need Google Cloud API access to run the CLI:

- Navigate to [Cloud Resource Manager](https://console.cloud.google.com/cloud-resource-manager) and click _Create Project_
    - alternatively create project with `gcloud projects create $PROJECT_ID`
- Navigate to [Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com) and click _Enable_
- Create credentials:
    - Go to [credentials page](https://console.cloud.google.com/apis/credentials)
    - Click _Create credentials_, select _Service account_
    - Give it a name and make note of service account email. Click _Create and Continue_

    - Open [Service account page](https://console.cloud.google.com/iam-admin/serviceaccounts)
    - Select previously created service account, Open _Keys_ tab
    - Click _Add Key_ and _Create New Key_. Choose JSON format and download it. (store this **securely**)

- Give SA permissions to GA - [guide](https://support.google.com/analytics/answer/1009702#Add)
    - email: SA email from earlier
    - role: _Viewer_
  
Alternatively see following [setup](https://martinheinz.dev/blog/62).

To install and run:

```bash
pip install ga-extractor
ga-extractor --help
```
  
## Running

```bash
ga-extractor --help
# Usage: ga-extractor [OPTIONS] COMMAND [ARGS]...
# ...

# Create config file:
ga-extractor setup \
  --sa-key-path="analytics-api-24102021-4edf0b7270c0.json" \
  --property-id="123456789" \
  --preset="FULL" \
  --start-date="2024-01-01" \
  --end-date="2024-01-31"
  
cat ~/.config/ga-extractor/config.yaml  # Optionally, check config

ga-extractor auth  # Test authentication
# Successfully authenticated with user: ...

ga-extractor setup --help  # For options and flags
```

- Value for `--property-id` can be found in GA4 web console under Admin > Property > Property Settings > Property ID
- All configurations and generated extracts/reports are stored in `~/.config/ga-extractor/...`
- You can use metrics and dimensions presets using `--preset` with `FULL` or `BASIC`, if you're not sure which data to extract
- Alternatively, specify custom metrics and dimensions using `--metrics` and `--dimensions`

### Extract

```bash
ga-extractor extract
# Report written to /home/some-user/.config/ga-extractor/report.json
```

`extract` perform raw extraction of dimensions and metrics using the provided configs

### Migrate

You can directly extract and transform data to various formats. Available options are:

- JSON (Default option; Default API output)
- CSV
- SQL (compatible with _Umami_ Analytics PostgreSQL backend)

```bash
ga-extractor migrate --format=CSV
# Report written to /home/user/.config/ga-extractor/02c2db1a-1ff0-47af-bad3-9c8bc51c1d13_extract.csv

head /home/user/.config/ga-extractor/02c2db1a-1ff0-47af-bad3-9c8bc51c1d13_extract.csv
# path,browser,os,device,screen,language,country,referral_path,count,date
# /,Chrome,Android,mobile,1370x1370,zh-cn,China,(direct),1,2024-01-01
# /,Chrome,Android,mobile,340x620,en-gb,United Kingdom,t.co/,1,2024-01-01

# For Umami migration, you need to provide website ID and hostname:
ga-extractor migrate \
  --format=UMAMI \
  --umami-website-id="123e4567-e89b-12d3-a456-426614174000" \
  --umami-hostname="example.com"
# Report written to /home/user/.config/ga-extractor/cee9e1d0-3b87-4052-a295-1b7224c5ba78_extract.sql

# IMPORTANT: Verify the data and check test database before inserting into production instance 
# To insert into DB:
cat cee9e1d0-3b87-4052-a295-1b7224c5ba78_extract.sql | mysql -u username -p database_name
```

You can verify the data is correct in Umami web console and GA web console:

- [Umami extract](./assets/umami-migration.png)
- [GA Pageviews](./assets/ga-pageviews.png)

_Note: Some data in GA and Umami web console might be little off, because GA displays many metrics based on sessions (e.g. Sessions by device), but data is extracted/migrated based on page views. You can however confirm that percentage breakdown of browser or OS usage does match._

## Development

### Setup

Requirements:

- Poetry (+ virtual environment)

```bash
poetry install
python -m ga_extractor --help
```

### Testing

```bash
poetry run pytest
```

### Installation and Usage

```bash
poetry install
poetry run ga-extractor --help

# Usage: ga-extractor [OPTIONS] COMMAND [ARGS]...
# ...
```
