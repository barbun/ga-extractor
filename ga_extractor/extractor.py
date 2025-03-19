# Standard libraries
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, NamedTuple

# Third-party lib
import typer
import validators
import yaml
import pycountry
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.oauth2 import service_account
from googleapiclient.discovery import build

extractor = typer.Typer()
APP_NAME = "ga-extractor"

# Constants
PAGEVIEW_EVENT_TYPE = 1
MAX_BROWSER_LENGTH = 20
DEFAULT_COUNTRY_CODE = 'XX'


def escape_sql_string(s: str) -> str:
    """Escape single quotes in strings for SQL."""
    if s is None:
        return ""
    return s.replace("'", "''")


class OutputFormat(str, Enum):
    JSON = "JSON"
    CSV = "CSV"
    UMAMI = "UMAMI"

    @staticmethod
    def file_suffix(f):
        format_mapping = {
            OutputFormat.JSON: "json",
            OutputFormat.CSV: "csv",
            OutputFormat.UMAMI: "sql",
        }
        return format_mapping[f]


class Preset(str, Enum):
    NONE = "NONE"
    FULL = "FULL"
    BASIC = "BASIC"

    @staticmethod
    def metrics(p):
        metrics_mapping = {
            Preset.NONE: [],
            Preset.FULL: ["screenPageViews", "sessions"],
            Preset.BASIC: ["screenPageViews"],
        }
        return metrics_mapping[p]

    @staticmethod
    def dims(p):
        dims_mapping = {
            Preset.NONE: [],
            Preset.FULL: ["pagePath", "browser", "operatingSystem", "deviceCategory", "screenResolution",
                          "language", "country", "sessionSource"],
            Preset.BASIC: ["pagePath"],
        }
        return dims_mapping[p]


@extractor.command()
def setup(
    metrics: str = typer.Option(None, "--metrics"),
    dimensions: str = typer.Option(None, "--dimensions"),
    sa_key_path: str = typer.Option(..., "--sa-key-path"),
    property_id: int = typer.Option(..., "--property-id", help="Google Analytics 4 property ID"),
    preset: Preset = typer.Option(Preset.NONE, "--preset",
                                help="Use metrics and dimension preset (can't be specified with '--dimensions' or '--metrics')"),
    start_date: datetime = typer.Option(..., formats=["%Y-%m-%d"]),
    end_date: datetime = typer.Option(..., formats=["%Y-%m-%d"]),
    dry_run: bool = typer.Option(False, "--dry-run", help="Outputs config to terminal instead of config file")
):
    """
    Generate configuration file from arguments
    """

    if (
            (preset is Preset.NONE and dimensions is None and metrics is None) or
            (dimensions is None and metrics is not None) or (dimensions is not None and metrics is None)
    ):
        typer.echo("Dimensions and Metrics or Preset must be specified.")
        typer.Exit(2)

    config = {
        "serviceAccountKeyPath": sa_key_path,
        "property": property_id,
        "metrics": "" if not metrics else metrics.split(","),
        "dimensions": "" if not dimensions else dimensions.split(","),
        "startDate": f"{start_date:%Y-%m-%d}",
        "endDate": f"{end_date:%Y-%m-%d}",
    }

    if preset is not Preset.NONE:
        config["metrics"] = Preset.metrics(preset)
        config["dimensions"] = Preset.dims(preset)

    output = yaml.dump(config)
    if dry_run:
        typer.echo(output)
    else:
        app_dir = typer.get_app_dir(APP_NAME)
        config_path: Path = Path(app_dir) / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as outfile:
            outfile.write(output)


@extractor.command()
def auth():
    """
    Test authentication using generated configuration
    """
    app_dir = typer.get_app_dir(APP_NAME)
    config_path: Path = Path(app_dir) / "config.yaml"
    if not config_path.is_file():
        typer.echo("Config file doesn't exist yet. Please run 'setup' command first.")
        return
    try:
        with config_path.open() as config:
            credentials = service_account.Credentials.from_service_account_file(yaml.safe_load(config)["serviceAccountKeyPath"])
            scoped_credentials = credentials.with_scopes(['openid'])
        with build('oauth2', 'v2', credentials=scoped_credentials) as service:
            user_info = service.userinfo().v2().me().get().execute()
            typer.echo(f"Successfully authenticated with user: {user_info['id']}")
    except BaseException as e:
        typer.echo(f"Authenticated failed with error: '{e}'")


@extractor.command()
def extract(report: Optional[Path] = typer.Option("report.json", dir_okay=True)):
    """
    Extracts data based on the config
    """
    app_dir = typer.get_app_dir(APP_NAME)
    config_path: Path = Path(app_dir) / "config.yaml"
    output_path: Path = Path(app_dir) / report
    if not config_path.is_file():
        typer.echo("Config file doesn't exist yet. Please run 'setup' command first.")
        typer.Exit(2)
    
    with config_path.open() as file:
        config = yaml.safe_load(file)
        credentials = service_account.Credentials.from_service_account_file(
            config["serviceAccountKeyPath"],
            scopes=['https://www.googleapis.com/auth/analytics.readonly']
        )

        dimensions = [Dimension(name=d) for d in config['dimensions']]
        metrics = [Metric(name=m) for m in config['metrics']]
        
        client = BetaAnalyticsDataClient(credentials=credentials)
        
        request = RunReportRequest(
            property=f"properties/{config['property']}",
            dimensions=dimensions,
            metrics=metrics,
            date_ranges=[DateRange(
                start_date=config['startDate'],
                end_date=config['endDate']
            )],
        )

        rows = []
        response = client.run_report(request)
        
        # Transform response to match expected format
        for row in response.rows:
            dimension_values = [dim_value.value for dim_value in row.dimension_values]
            metric_values = [{"values": [str(metric_value.value) for metric_value in row.metric_values]}]
            rows.append({
                "dimensions": dimension_values,
                "metrics": metric_values
            })

        output_path.write_text(json.dumps(rows))
        typer.echo(f"Report written to {output_path.absolute()}")


@extractor.command()
def migrate(
    output_format: OutputFormat = typer.Option(OutputFormat.JSON, "--format"),
    umami_website_id: Optional[uuid.UUID] = typer.Option(None, "--umami-website-id", help="Website ID from Umami (required for Umami format)"),
    umami_hostname: Optional[str] = typer.Option(None, "--umami-hostname", help="Hostname for the website in Umami (required for Umami format)")
):
    """Export necessary data and transform it to format for target environment."""
    try:
        app_dir = typer.get_app_dir(APP_NAME)
        config_path: Path = Path(app_dir) / "config.yaml"
        output_path: Path = Path(app_dir) / f"{uuid.uuid4()}_extract.{OutputFormat.file_suffix(output_format)}"
        
        if output_format == OutputFormat.UMAMI and (not umami_website_id or not umami_hostname):
            typer.echo("For Umami format, both --umami-website-id and --umami-hostname must be provided")
            raise typer.Exit(1)

        with config_path.open() as file:
            config = yaml.safe_load(file)
            credentials = service_account.Credentials.from_service_account_file(config["serviceAccountKeyPath"])
            scoped_credentials = credentials.with_scopes(['https://www.googleapis.com/auth/analytics.readonly'])

            date_ranges = _migrate_date_ranges(config['startDate'], config['endDate'])
            rows = _migrate_extract(scoped_credentials, config['property'], date_ranges)

            if output_format == OutputFormat.UMAMI:
                data = _migrate_transform_umami(rows, umami_website_id, umami_hostname)
                
                with output_path.open(mode="w") as f:
                    for insert in data:
                        f.write(f"{insert}\n")
            elif output_format == OutputFormat.JSON:
                output_path.write_text(json.dumps(rows))
            elif output_format == OutputFormat.CSV:
                data = _migrate_transform_csv(rows)
                with output_path.open(mode="w") as f:
                    for row in data:
                        f.write(f"{row}\n")

            typer.echo(f"Report written to {output_path.absolute()}")
    except FileNotFoundError:
        typer.echo("Config file doesn't exist yet. Please run 'setup' command first.")
        raise typer.Exit(2)
    except yaml.YAMLError:
        typer.echo("Invalid config file format")
        raise typer.Exit(3)


def _migrate_date_ranges(
    start_date: str,
    end_date: str
) -> list[dict[str, str]]:
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')
    date_ranges = [{"startDate": f"{start_date + timedelta(days=d):%Y-%m-%d}",
                    "endDate": f"{start_date + timedelta(days=d):%Y-%m-%d}"} for d in
                   range(((end_date.date() - start_date.date()).days + 1))]
    return date_ranges


def _migrate_extract(credentials, property_id, date_ranges):
    dimensions = ["pagePath", "browser", "operatingSystem", "deviceCategory", "screenResolution", 
                 "language", "country", "sessionSource"]
    metrics = ["screenPageViews", "sessions"]

    client = BetaAnalyticsDataClient(credentials=credentials)
    rows = {}

    for date_range in date_ranges:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(
                start_date=date_range["startDate"],
                end_date=date_range["endDate"]
            )],
        )

        response = client.run_report(request)
        
        # Transform response to match expected format
        daily_rows = []
        for row in response.rows:
            dimension_values = [dim_value.value for dim_value in row.dimension_values]
            metric_values = [{"values": [str(metric_value.value) for metric_value in row.metric_values]}]
            daily_rows.append({
                "dimensions": dimension_values,
                "metrics": metric_values
            })
        
        rows[date_range["startDate"]] = daily_rows

    return rows


class Session(NamedTuple):
    """Represents a user session in Umami analytics."""
    session_id: uuid.UUID
    website_id: uuid.UUID
    created_at: int
    hostname: str
    browser: str
    os: str
    device: str
    screen: str
    language: str
    country: str

    def sql(self):
        dt = datetime.fromtimestamp(self.created_at // 1000).strftime('%Y-%m-%d %H:%M:%S')
        
        # Get country code directly using pycountry
        try:
            if found := pycountry.countries.get(name=self.country):
                country_code = found.alpha_2
            elif found := pycountry.countries.search_fuzzy(self.country):
                country_code = found[0].alpha_2
            else:
                country_code = DEFAULT_COUNTRY_CODE
        except LookupError:
            country_code = DEFAULT_COUNTRY_CODE

        # Ensure country_code is always 2 characters
        country_code = country_code[:2]
        
        # Truncate OS field to 20 chars to fix SQL error and handle potential escaping
        safe_os = self.os[:20].replace("'", "''") if self.os else ""
        
        return (
            f"INSERT INTO session (session_id, website_id, created_at, hostname, browser, os, "
            f"device, screen, language, country) VALUES ('{self.session_id}', '{self.website_id}', '{dt}', "
            f"'{self.hostname}', '{self.browser[:MAX_BROWSER_LENGTH]}', '{safe_os}', "
            f"'{self.device}', '{self.screen}', "
            f"'{self.language}', '{country_code}');"
        )


class PageView(NamedTuple):
    event_id: uuid.UUID
    website_id: uuid.UUID
    session_id: uuid.UUID
    created_at: int  # timestamp in milliseconds
    url_path: str
    referrer_path: str

    def sql(self):
        dt = datetime.fromtimestamp(self.created_at // 1000).strftime('%Y-%m-%d %H:%M:%S')
        
        # Escape string values
        safe_url_path = escape_sql_string(self.url_path)
        safe_referrer_path = escape_sql_string(self.referrer_path)
        
        return (
            f"INSERT INTO website_event (event_id, website_id, session_id, visit_id, created_at, url_path, referrer_path, event_type) "
            f"VALUES ('{self.event_id}', '{self.website_id}', '{self.session_id}', '{self.session_id}', '{dt}', "
            f"'{safe_url_path}', '{safe_referrer_path}', {PAGEVIEW_EVENT_TYPE});"
        )


def _migrate_transform_umami(
    rows: dict,
    website_id: uuid.UUID,
    hostname: str
) -> list[str]:
    """Transform GA data into Umami-compatible SQL inserts"""
    
    sql_inserts = []
    for day, value in rows.items():
        for row in value:
            # Convert YYYY-MM-DD to millisecond timestamp
            timestamp_ms = int(datetime.strptime(f"{day} 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
            
            # Process referrer
            referrer = f"https://{row['dimensions'][7]}"
            if not validators.url(referrer):
                referrer = ""
            elif referrer == "google":
                referrer = "https://google.com"

            # Extract common data
            page_views, sessions = map(int, row["metrics"][0]["values"])
            sessions = max(sessions, 1)  # in case it's zero
            url_path = row["dimensions"][0]
            browser = row["dimensions"][1]
            os_name = row["dimensions"][2]
            device = row["dimensions"][3]
            screen = row["dimensions"][4]
            language = row["dimensions"][5][:2].lower()  # Ensure lowercase 2-letter code
            country = row["dimensions"][6]
            
            # Create session and page view objects based on distribution pattern
            if page_views == sessions:  # One page view for each session
                for _ in range(sessions):
                    session_id = uuid.uuid4()
                    
                    # Add one session with one page view
                    sql_inserts.append(Session(
                        session_id=session_id, website_id=website_id, created_at=timestamp_ms,
                        hostname=hostname, browser=browser, os=os_name, device=device,
                        screen=screen, language=language, country=country
                    ).sql())
                    
                    sql_inserts.append(PageView(
                        event_id=uuid.uuid4(), website_id=website_id, session_id=session_id,
                        created_at=timestamp_ms, url_path=url_path, referrer_path=referrer
                    ).sql())

            elif page_views % sessions == 0:  # Split equally
                views_per_session = page_views // sessions
                
                for _ in range(sessions):
                    session_id = uuid.uuid4()
                    
                    # Add one session
                    sql_inserts.append(Session(
                        session_id=session_id, website_id=website_id, created_at=timestamp_ms,
                        hostname=hostname, browser=browser, os=os_name, device=device,
                        screen=screen, language=language, country=country
                    ).sql())
                    
                    # Add multiple page views for this session
                    for _ in range(views_per_session):
                        sql_inserts.append(PageView(
                            event_id=uuid.uuid4(), website_id=website_id, session_id=session_id,
                            created_at=timestamp_ms, url_path=url_path, referrer_path=referrer
                        ).sql())

            else:  # One page view for each, rest for the last session
                last_session_id = None
                
                # Create sessions with one page view each
                for _ in range(sessions):
                    session_id = uuid.uuid4()
                    last_session_id = session_id
                    
                    sql_inserts.append(Session(
                        session_id=session_id, website_id=website_id, created_at=timestamp_ms,
                        hostname=hostname, browser=browser, os=os_name, device=device,
                        screen=screen, language=language, country=country
                    ).sql())
                    
                    sql_inserts.append(PageView(
                        event_id=uuid.uuid4(), website_id=website_id, session_id=session_id,
                        created_at=timestamp_ms, url_path=url_path, referrer_path=referrer
                    ).sql())

                # Add remaining page views to the last session
                for _ in range(page_views - sessions):
                    sql_inserts.append(PageView(
                        event_id=uuid.uuid4(), website_id=website_id, session_id=last_session_id,
                        created_at=timestamp_ms, url_path=url_path, referrer_path=referrer
                    ).sql())

    return sql_inserts


class CSVRow(NamedTuple):
    path: str
    browser: str
    os: str
    device: str
    screen: str
    language: str
    country: str
    referral_path: str
    count: str
    date: datetime.date

    @staticmethod
    def header():
        return f"path,browser,os,device,screen,language,country,referral_path,count,date"

    def csv(self):
        return f"{self.path},{self.browser},{self.os},{self.device},{self.screen},{self.language},{self.country},{self.referral_path},{self.count},{self.date}"


def _migrate_transform_csv(rows):
    csv_rows = [CSVRow.header()]
    for day, value in rows.items():
        for row in value:
            page_views, _ = map(int, row["metrics"][0]["values"])
            row = CSVRow(path=row["dimensions"][0],
                         browser=row["dimensions"][1],
                         os=row["dimensions"][2],
                         device=row["dimensions"][3],
                         screen=row["dimensions"][4],
                         language=row["dimensions"][5],
                         country=row["dimensions"][6],
                         referral_path=row["dimensions"][7],
                         count=page_views,
                         date=day)
            csv_rows.append(row.csv())
    return csv_rows


def _validate_config(config: dict) -> None:
    """Validate configuration dictionary.
    
    Args:
        config: Configuration dictionary
        
    Raises:
        ValueError: If required fields are missing or invalid
    """
    required_fields = ['serviceAccountKeyPath', 'property', 'startDate', 'endDate']
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required config field: {field}")
