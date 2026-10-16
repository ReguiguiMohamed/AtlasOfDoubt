import pytest
from fastapi.testclient import TestClient

from atlas.api import app
from atlas.ingest import ingest
from tests.test_ingest import FLOWS

SNAPSHOT = "BACI_HS12_V202601"


@pytest.fixture
def api(db, make_archive):
    ingest(make_archive(FLOWS), db)
    with TestClient(app) as client:
        yield client


def test_unknown_snapshot_is_not_found(api):
    assert api.get("/api/overview", params={"snapshot": "BACI_HS12_V190001"}).status_code == 404


def test_snapshot_lists_provenance(api):
    [snapshot] = api.get("/api/snapshots").json()
    assert snapshot["_id"] == SNAPSHOT
    assert snapshot["source"]["release"] == "202601"
    assert "countries" not in snapshot


def test_product_search_by_code_prefix_and_text(api):
    by_code = api.get("/api/products", params={"snapshot": SNAPSHOT, "q": "01"}).json()
    by_text = api.get("/api/products", params={"snapshot": SNAPSHOT, "q": "AMMONIUM"}).json()
    assert [p["productCode"] for p in by_code] == ["010121"]
    assert [p["productCode"] for p in by_text] == ["310230"]


def test_overview_defaults_to_latest_year_and_filters_by_value(api):
    latest = api.get("/api/overview", params={"snapshot": SNAPSHOT}).json()
    assert latest["year"] == 2024
    assert latest["rows"] == []
    rows = api.get("/api/overview", params={"snapshot": SNAPSHOT, "year": 2012, "minValue": 10000}).json()["rows"]
    assert [r["productCode"] for r in rows] == ["010121"]
    assert rows[0]["metrics"]["hhi"] == pytest.approx(0.46)


def test_overview_rejects_a_year_outside_the_snapshot(api):
    assert api.get("/api/overview", params={"snapshot": SNAPSHOT, "year": 2030}).status_code == 422


def test_history_shows_missing_years_as_gaps(api):
    history = api.get("/api/products/100119/history", params={"snapshot": SNAPSHOT}).json()
    by_year = {y["year"]: y for y in history["years"]}
    assert len(by_year) == 13
    assert by_year[2012]["metrics"] is None
    assert by_year[2015]["metrics"]["totalUsd"] == 1500


def test_history_of_a_group_sums_suppliers_before_shares(api):
    history = api.get("/api/products/31/history", params={"snapshot": SNAPSHOT}).json()
    year = next(y for y in history["years"] if y["year"] == 2012)
    assert year["metrics"]["hhi"] == 1
    assert year["world"] is None
    assert "quantityTonnes" not in year["suppliers"][0]


def test_history_rejects_odd_length_codes(api):
    assert api.get("/api/products/100/history", params={"snapshot": SNAPSHOT}).status_code == 422
