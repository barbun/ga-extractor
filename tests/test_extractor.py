from typer.testing import CliRunner
import uuid

from ga_extractor.extractor import _migrate_transform_umami, _migrate_transform_csv, _migrate_date_ranges, PAGEVIEW_EVENT_TYPE

runner = CliRunner()


def test__migrate_transform_umami(sample_extract):
    sql = _migrate_transform_umami(sample_extract, uuid.UUID('123e4567-e89b-12d3-a456-426614174000'), "localhost")
    
    # Check total number of SQL statements
    assert len(sql) == 23
    
    # Check correct number of session and event inserts
    session_inserts = [row for row in sql if row.startswith("INSERT INTO session")]
    event_inserts = [row for row in sql if row.startswith("INSERT INTO website_event")]
    assert len(session_inserts) == 10
    assert len(event_inserts) == 13
    
    # Check blog/68 appears in the expected number of statements
    blog68_statements = [row for row in sql if "/blog/68" in row]
    assert len(blog68_statements) == 3
    
    # Check all events are page views
    pageview_statements = [row for row in sql if f", {PAGEVIEW_EVENT_TYPE});" in row]
    assert len(pageview_statements) == 13
    
    # Check country codes are correctly converted
    assert any("'VE'" in row for row in sql)  # Venezuela
    assert any("'MY'" in row for row in sql)  # Malaysia
    assert any("'US'" in row for row in sql)  # United States
    assert any("'CO'" in row for row in sql)  # Colombia


def test__migrate_transform_csv(sample_extract):
    expected = ['path,browser,os,device,screen,language,country,referral_path,count,date',
                '/blog/69,Chrome,Linux,desktop,1850x950,es-us,Venezuela,t.co/,5,2022-03-19',
                '/,Chrome,Android,mobile,420x800,en-us,Malaysia,google,1,2022-03-19',
                '/blog/51,Chrome,Macintosh,desktop,1540x850,en-us,United States,(direct),4,2022-03-19',
                '/blog/68,Firefox,Android,mobile,410x780,es-us,Colombia,betterprogramming.pub/building-github-apps-with-golang-43b27f3e9621,3,2022-03-19']

    csv_rows = _migrate_transform_csv(sample_extract)

    assert csv_rows == expected


def test__migrate_date_ranges():
    expected = [{'endDate': '2022-03-17', 'startDate': '2022-03-17'},
                {'endDate': '2022-03-18', 'startDate': '2022-03-18'},
                {'endDate': '2022-03-19', 'startDate': '2022-03-19'}]

    date_ranges = _migrate_date_ranges("2022-03-17", "2022-03-19")

    assert date_ranges == expected
