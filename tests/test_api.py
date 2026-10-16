from decimal import Decimal

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


def preview(api, **spec):
    response = api.post("/api/scenarios/preview", json={"snapshot": SNAPSHOT, "year": 2012, **spec})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_product_scenario_follows_the_blueprint_rule(api):
    result = preview(api, mode="product", productCode="010121", suppliers=[251], reduction=0.5)
    assert result["affectedUsd"] == 30000
    assert result["exposureShare"] == pytest.approx(0.3)
    assert result["remainingUsd"] == 70000
    assert [s["selected"] for s in result["suppliers"]] == [True, False, False]


def test_country_scenario_ranks_products_and_never_adds_tonnes(api):
    result = preview(api, mode="country", suppliers=[251], reduction=1)
    assert [p["productCode"] for p in result["products"]] == ["010121", "310230"]
    assert result["affectedUsd"] == 60000 + 2734
    assert result["totalImportsUsd"] == 100000 + 2734
    assert result["suppliers"] == [{"countryCode": 251, "countryName": "France", "valueUsd": 62734}]
    assert "quantityTonnes" not in str(result)


@pytest.mark.parametrize(
    "spec",
    [
        {"mode": "product", "suppliers": [251], "reduction": 0.5},
        {"mode": "product", "productCode": "010121", "suppliers": [251], "reduction": 1.5},
        {"mode": "country", "suppliers": [], "reduction": 0.5},
        {"mode": "country", "suppliers": [999], "reduction": 0.5},
    ],
)
def test_scenario_rejects_bad_specs(api, spec):
    response = api.post("/api/scenarios/preview", json={"snapshot": SNAPSHOT, "year": 2012, **spec})
    assert response.status_code == 422


def test_report_ignores_numbers_sent_by_the_browser(api):
    body = {"snapshot": SNAPSHOT, "year": 2012, "mode": "product", "productCode": "010121",
            "suppliers": [251], "reduction": 0.5, "title": "France halves", "affectedUsd": 1}
    report_id = api.post("/api/reports", json=body).json()["id"]
    report = api.get(f"/api/reports/{report_id}").json()
    assert report["result"]["affectedUsd"] == 30000
    assert report["snapshot"]["archive"]["filename"] == "BACI_HS12_V202601.zip"
    assert report["calculationVersion"] == "1"


def test_report_is_unchanged_after_another_snapshot_is_added(api, db, make_archive):
    body = {"snapshot": SNAPSHOT, "year": 2012, "mode": "country", "suppliers": [251, 380],
            "reduction": 0.25, "title": "EU quarter cut"}
    report_id = api.post("/api/reports", json=body).json()["id"]
    before = api.get(f"/api/reports/{report_id}").json()
    ingest(make_archive({2012: ["2012,251,788,010121,999,1"]}, release="209901"), db)
    assert len(api.get("/api/snapshots").json()) == 2
    assert api.get(f"/api/reports/{report_id}").json() == before


def test_report_csv_exports_the_result_table(api):
    body = {"snapshot": SNAPSHOT, "year": 2012, "mode": "product", "productCode": "010121",
            "suppliers": [251], "reduction": 0.5, "title": "France halves"}
    report_id = api.post("/api/reports", json=body).json()["id"]
    response = api.get(f"/api/reports/{report_id}.csv")
    lines = response.text.splitlines()
    assert response.headers["content-type"].startswith("text/csv")
    assert lines[0] == "countryCode,countryName,isoCode,selected,baselineUsd,baselineShare,remainingUsd,remainingShare"
    assert lines[1].startswith("251,France,FRA,True,60000,0.6,30000.0,")
    assert len(lines) == 4


def test_unknown_report_is_not_found(api):
    assert api.get("/api/reports/not-an-id").status_code == 404
    assert api.get("/api/reports/0123456789abcdef01234567").status_code == 404


def test_static_files_are_revalidated(api):
    assert api.get("/").headers["cache-control"] == "no-cache"
    assert api.get("/app.js").headers["cache-control"] == "no-cache"


def test_responses_are_compressed(api):
    assert api.get("/app.js", headers={"accept-encoding": "gzip"}).headers["content-encoding"] == "gzip"


def test_country_profile_sums_supplies_across_products(api):
    profile = api.get("/api/countries/251", params={"snapshot": SNAPSHOT, "year": 2012}).json()
    assert profile["country"]["countryName"] == "France"
    assert [(p["productCode"], p["valueUsd"], p["share"], p["rank"]) for p in profile["products"]] == [
        ("010121", 60000, 0.6, 1),
        ("310230", 2734, 1, 1),
    ]
    years = {y["year"]: y for y in profile["years"]}
    assert years[2012]["valueUsd"] == 62734
    assert years[2012]["shareOfImports"] == pytest.approx(62734 / 102734)
    assert years[2012]["productCount"] == 2
    assert years[2013]["valueUsd"] is None
    assert years[2015]["shareOfImports"] == 1


def test_country_profile_ranks_a_minor_supplier(api):
    [horses] = api.get("/api/countries/380", params={"snapshot": SNAPSHOT, "year": 2012}).json()["products"]
    assert (horses["rank"], horses["share"], horses["supplierCount"]) == (2, 0.3, 3)


def test_unknown_country_is_not_found(api):
    assert api.get("/api/countries/999", params={"snapshot": SNAPSHOT}).status_code == 404


def later_year(db, code, totalUsd, hhi):
    doc = db.product_years.find_one({"productCode": code, "year": 2012}, {"_id": 0})
    doc["year"] = 2015
    doc["metrics"] = {**doc["metrics"], "totalUsd": Decimal(totalUsd), "hhi": Decimal(hhi)}
    db.product_years.insert_one(doc)


def test_movers_split_rising_and_falling_concentration(api, db):
    later_year(db, "010121", 120000, "0.9")
    later_year(db, "310230", 3000, "0.5")
    moved = api.get("/api/movers", params={"snapshot": SNAPSHOT, "from": 2012, "to": 2015}).json()
    assert moved["compared"] == 2
    assert [(r["productCode"], r["change"]) for r in moved["rising"]] == [("010121", pytest.approx(0.44))]
    assert [(r["productCode"], r["change"]) for r in moved["falling"]] == [("310230", -0.5)]


def test_movers_need_the_minimum_value_in_both_years(api, db):
    later_year(db, "010121", 120000, "0.9")
    later_year(db, "310230", 3000, "0.5")
    moved = api.get("/api/movers", params={"snapshot": SNAPSHOT, "from": 2012, "to": 2015, "minValue": 2900}).json()
    assert moved["compared"] == 1
    assert moved["falling"] == []
