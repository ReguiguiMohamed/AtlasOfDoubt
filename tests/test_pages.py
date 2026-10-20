from deploy.pages import filename


def test_filename_sorts_the_query_and_drops_the_latest_year():
    """atlas/static/lib.js sampleFile() builds the same names, checked in frontend.test.mjs."""
    assert filename("/snapshots", 2024) == "api/snapshots.json"
    assert filename("/countries/842?snapshot=S%401&reporter=392&year=2024", 2024) == "api/countries/842/reporter=392&snapshot=S@1.json"
    assert filename("/movers?to=2024&from=2012&reporter=392", 2024) == "api/movers/from=2012&reporter=392&to=2024.json"
    assert filename("/overview?year=2023&reporter=392", 2024) == "api/overview/reporter=392&year=2023.json"
