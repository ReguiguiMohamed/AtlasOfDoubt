import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas import materialize, routes
from atlas.api import app
from atlas.prepare import prepare
from tests.test_prepare import FLOWS, NETWORK, fixture_geography, hs_files

TUNISIA, USA, CHINA = 788, 842, 156


@pytest.fixture
def api(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    with TestClient(app) as client:
        client.snapshot = snapshot["_id"]
        client.params = {"snapshot": snapshot["_id"], "reporter": TUNISIA}
        yield client


def settled(client, path, **params):
    """A page of every year once the background fill has built them all."""
    for _ in range(100):
        body = client.get(path, params=params).json()
        if not body["filling"]:
            return body
        time.sleep(0.1)
    raise AssertionError(f"{path} still filling")


def test_unknown_snapshot_is_not_found(api):
    assert api.get("/api/overview", params={"snapshot": "BACI_HS12_V190001@000000000000"}).status_code == 404


def test_unknown_reporter_is_rejected(api):
    assert api.get("/api/overview", params={"reporter": 999}).status_code == 422
    assert api.get("/api/overview", params={"reporter": ""}).status_code == 422


def test_snapshot_lists_provenance(api):
    [snapshot] = api.get("/api/snapshots").json()
    assert snapshot["_id"] == api.snapshot
    assert snapshot["source"]["release"] == "202601"
    assert "countries" not in snapshot


def test_product_search_by_code_prefix_and_text(api):
    by_code = api.get("/api/products", params={"q": "01"}).json()
    by_text = api.get("/api/products", params={"q": "AMMONIUM"}).json()
    assert [p["productCode"] for p in by_code] == ["010121"]
    assert [p["productCode"] for p in by_text] == ["310230"]


def test_product_search_matches_words_in_any_order_and_half_typed_words(api):
    search = lambda q: [p["productCode"] for p in api.get("/api/products", params={"q": q}).json()]
    assert search("nitrates ammonium") == ["310230"]
    assert search("seed durum") == ["100119"]
    assert search("fertil") == ["310230"]
    assert search("Wheat: dur") == ["100119"]


def test_overview_defaults_to_latest_year_and_filters_by_value(api):
    latest = api.get("/api/overview").json()
    assert latest["year"] == 2024
    assert latest["rows"] == []
    rows = api.get("/api/overview", params={"year": 2012, "minValue": 10000}).json()["rows"]
    assert [r["productCode"] for r in rows] == ["010121"]
    assert rows[0]["metrics"]["hhi"] == pytest.approx(0.46)


def test_overview_rejects_a_year_outside_the_snapshot(api):
    assert api.get("/api/overview", params={"year": 2030}).status_code == 422


def test_history_shows_missing_years_as_gaps(api):
    history = settled(api, "/api/products/100119/history")
    by_year = {y["year"]: y for y in history["years"]}
    assert len(by_year) == 13
    assert by_year[2012]["metrics"] is None
    assert by_year[2015]["metrics"]["totalUsd"] == 1500


def test_history_of_a_group_sums_suppliers_before_shares(api):
    history = api.get("/api/products/31/history").json()
    year = next(y for y in history["years"] if y["year"] == 2012)
    assert year["metrics"]["hhi"] == 1
    assert year["world"] is None
    assert "quantityTonnes" not in year["suppliers"][0]


def test_history_carries_the_reporters_exports(api):
    one = {y["year"]: y for y in settled(api, "/api/products/010121/history")["years"]}
    group = {y["year"]: y for y in settled(api, "/api/products/01/history")["years"]}
    assert one[2012]["exports"]["totalUsd"] == group[2012]["exports"]["totalUsd"] == 5000
    assert group[2012]["exports"]["rca"] == pytest.approx(one[2012]["exports"]["rca"])
    assert group[2012]["exports"]["rca"] == pytest.approx(1 / (205000 / 207734))
    assert one[2015]["exports"] is None


def test_history_lists_world_exporters_without_the_reporter(api):
    one = {y["year"]: y for y in api.get("/api/products/010121/history").json()["years"]}
    group = {y["year"]: y for y in api.get("/api/products/01/history").json()["years"]}
    assert [(e["isoCode"], e["valueUsd"]) for e in one[2012]["exporters"]] == [("FRA", 160000), ("ITA", 30000), ("USA", 10000)]
    assert one[2012]["exporters"][0]["share"] == pytest.approx(160 / 205)
    assert group[2012]["exporters"] == []


def test_history_rejects_odd_length_codes(api):
    assert api.get("/api/products/100/history").status_code == 422


def preview(api, **spec):
    body = {"snapshot": api.snapshot, "reporter": TUNISIA, "year": 2012, **spec}
    response = api.post("/api/scenarios/preview", json=body)
    assert response.status_code == 200, response.text
    return response.json()["result"]


# World exports of horses in 2012: France 160, Italy 30, the USA 10 and Tunisia 5 thousand USD, 205 in all.
def test_an_embargo_strands_its_imports_and_untouched_exporters_fill_their_share(api):
    result = preview(api, suppliers=[251], reduction=1)
    horses, fertilizer = result["products"]
    assert (horses["productCode"], fertilizer["productCode"]) == ("010121", "310230")
    assert result["affectedUsd"] == result["strandedUsd"] == 60000 + 2734
    assert horses["replacedUsd"] == pytest.approx(0.1 * (30000 + 10000) * 100000 / 205000)
    assert horses["alternatives"] == ["ITA", "USA"]
    assert fertilizer["gapUsd"] == 2734
    assert result["totalImportsUsd"] == 100000 + 2734
    assert result["suppliers"] == [
        {"countryCode": 251, "countryName": "France", "isoCode": "FRA", "cause": "embargo", "valueUsd": 62734, "affectedUsd": 62734}
    ]
    assert "quantityTonnes" not in str(result)


def test_a_closed_strait_reroutes_what_has_another_lane_and_strands_the_rest(api):
    late = preview(api, chokepoints=["gibraltar"], reduction=1)
    assert (late["affectedUsd"], late["reroutedUsd"], late["gapUsd"]) == (10000, 10000, 0)
    americas = {r["id"]: r for r in late["routes"]}["americas"]
    assert americas["state"] == "rerouted"
    assert "gibraltar" not in americas["detour"]["via"]
    assert late["delayDays"] == americas["detour"]["extraDays"] > 0
    assert late["closed"] == [{"id": "gibraltar", "name": "Strait of Gibraltar", "at": [-5.6, 35.88]}]
    shut = preview(api, chokepoints=["gibraltar", "suez"], reduction=1)
    assert shut["strandedUsd"] == 10000
    assert {r["id"]: r["state"] for r in shut["routes"]}["americas"] == "cutOff"


def test_a_regional_shutdown_hits_every_supplier_there_for_the_weeks_it_lasts(api):
    result = preview(api, regions=["mediterranean"], reduction="0.5", weeks=13)
    assert result["affectedUsd"] == pytest.approx((60000 + 30000 + 2734) * 0.5 / 4)
    assert {s["isoCode"]: s["cause"] for s in result["suppliers"]} == {"FRA": "region", "ITA": "region"}
    assert result["timeline"][0] == {
        "year": 2012, "totalUsd": pytest.approx(102734 / 4),
        "affectedUsd": pytest.approx(92734 * 0.5 / 4), "strandedUsd": pytest.approx(92734 * 0.5 / 4),
    }


def test_presets_name_the_countries_this_snapshot_has(two):
    presets = {p["id"]: p for p in two.get("/api/scenarios/presets", params={"snapshot": two.snapshot}).json()}
    assert presets["gallium-germanium-2023"]["suppliers"] == [CHINA]
    assert presets["black-sea-grain-2022"]["suppliers"] == []
    assert all(p["url"] is None or p["url"].startswith("https://") for p in presets.values())


@pytest.mark.parametrize("reporter", [TUNISIA, USA, 251, 380])
def test_every_strait_preset_runs_for_every_country(api, reporter):
    for p in api.get("/api/scenarios/presets", params={"snapshot": api.snapshot}).json():
        if p.get("chokepoints"):
            spec = {k: p[k] for k in ("chokepoints", "reduction", "weeks")}
            assert api.post("/api/scenarios/preview", json={
                "snapshot": api.snapshot, "reporter": reporter, "year": 2012, "preset": p["id"], **spec,
            }).status_code == 200


@pytest.mark.parametrize(
    "spec",
    [
        {"reduction": 0.5},
        {"productCode": "010121", "suppliers": [251], "reduction": 1.5},
        {"suppliers": [999], "reduction": 0.5},
        {"suppliers": [251], "reduction": 0.5, "reporter": 999},
        {"chokepoints": ["nowhere"], "reduction": 0.5},
        {"regions": ["atlantis"], "reduction": 0.5},
        {"suppliers": [251], "reduction": 0.5, "weeks": 0},
        {"suppliers": [251], "reduction": 0.5, "preset": "made-up"},
    ],
)
def test_scenario_rejects_bad_specs(api, spec):
    body = {"snapshot": api.snapshot, "reporter": TUNISIA, "year": 2012, **spec}
    assert api.post("/api/scenarios/preview", json=body).status_code == 422


def test_a_scenario_on_a_missing_product_is_not_found(api):
    body = {"snapshot": api.snapshot, "reporter": TUNISIA, "year": 2012, "productCode": "8542", "suppliers": [251], "reduction": 1}
    assert api.post("/api/scenarios/preview", json=body).status_code == 404


def report(api, **spec):
    body = {"snapshot": api.snapshot, "reporter": TUNISIA, "year": 2012, "productCode": "010121",
            "suppliers": [251], "reduction": 0.5, "title": "France halves", **spec}
    return api.post("/api/reports", json=body).json()["id"]


def test_report_ignores_numbers_sent_by_the_browser(api):
    saved = api.get(f"/api/reports/{report(api, affectedUsd=1)}").json()
    assert saved["result"]["affectedUsd"] == 30000
    assert saved["snapshot"]["archive"]["filename"] == "BACI_HS12_V202601.zip"
    assert saved["snapshot"]["manifest"]["layoutVersion"] == "3"
    assert saved["reporter"] == {"countryCode": TUNISIA, "countryName": "Tunisia", "isoCode": "TUN"}
    assert saved["calculationVersion"] == "3"
    assert saved["spec"]["weeks"] == 52


def test_reports_are_listed_per_reporter_with_their_headline(api):
    report(api)
    [listed] = api.get("/api/reports").json()
    assert listed["result"] == {"affectedUsd": 30000, "gapUsd": pytest.approx(30000 - 0.1 * 40000 * 100000 / 205000), "delayDays": None}
    assert api.get("/api/reports", params={"reporter": USA}).json() == []


def test_report_is_unchanged_after_another_snapshot_is_added(api, db, make_archive):
    report_id = report(api, productCode=None, suppliers=[251, 380], reduction=0.25, title="EU quarter cut")
    before = api.get(f"/api/reports/{report_id}").json()
    prepare(make_archive({2012: ["2012,251,788,010121,999,1"]}, release="209901"), db)
    assert len(api.get("/api/snapshots").json()) == 2
    assert api.get(f"/api/reports/{report_id}").json() == before


def test_report_csv_exports_the_product_rows(api):
    response = api.get(f"/api/reports/{report(api, productCode=None, reduction=1)}.csv")
    lines = response.text.splitlines()
    assert response.headers["content-type"].startswith("text/csv")
    assert lines[0] == (
        "productCode,description,totalUsd,affectedUsd,reroutedUsd,strandedUsd,replacedUsd,gapUsd,exposureShare,baselineHhi,remainingHhi"
    )
    assert lines[1].startswith('010121,"Horses: live, pure-bred breeding animals",100000')
    assert len(lines) == 3


def test_a_client_saves_a_limited_number_of_reports_an_hour(api, monkeypatch):
    from atlas import api as server
    monkeypatch.setattr(server, "REPORTS_PER_HOUR", 2)
    body = {"snapshot": api.snapshot, "reporter": TUNISIA, "year": 2012, "productCode": "010121",
            "suppliers": [251], "reduction": 0.5, "title": "France halves"}
    assert [api.post("/api/reports", json=body).status_code for _ in range(3)] == [201, 201, 429]
    assert len(api.get("/api/reports").json()) == 2


def test_unknown_report_is_not_found(api):
    assert api.get("/api/reports/not-an-id").status_code == 404
    assert api.get("/api/reports/0123456789abcdef01234567").status_code == 404


def test_static_files_are_revalidated(api):
    assert api.get("/").headers["cache-control"] == "no-cache"
    assert api.get("/app.js").headers["cache-control"] == "no-cache"


# Tunisia and France export the same mix. China shares the fertilizer and Italy the wheat, and the USA shares nothing.
TWINS = {2024: [
    "2024,788,4,100119,64,1", "2024,788,4,310230,36,1",
    "2024,251,4,100119,64,1", "2024,251,4,310230,36,1",
    "2024,380,4,100119,36,1", "2024,380,4,010121,64,1",
    "2024,156,4,310230,100,1",
    "2024,842,4,010121,100,1",
]}


def test_twins_rank_countries_by_basket_overlap_and_name_what_they_share(db, make_archive):
    snapshot = prepare(make_archive(TWINS), db)
    assert snapshot["twins"]["vectors"] == {"imports": 1, "exports": 5}
    params = {"snapshot": snapshot["_id"], "reporter": TUNISIA}
    with TestClient(app) as client:
        found = client.get("/api/twins", params=params).json()
        assert client.get("/api/twins", params=params | {"flow": "imports"}).status_code == 404
    assert (found["flow"], found["year"]) == ("exports", 2024)
    assert [(s["isoCode"], round(s["similarity"], 4)) for s in found["similar"]] == [("FRA", 1.0), ("CHN", 0.6), ("ITA", 0.48)]
    france = found["closest"][0]["shared"]
    assert [(p["productCode"], round(p["contribution"], 4)) for p in france] == [("100119", 0.64), ("310230", 0.36)]
    assert france[0]["description"] == "Wheat: durum wheat, other than seed"


def test_responses_are_compressed(api):
    assert api.get("/app.js", headers={"accept-encoding": "gzip"}).headers["content-encoding"] == "gzip"


def test_network_finds_shared_suppliers_other_exporters_and_two_step_paths(db, make_archive):
    snapshot = prepare(make_archive(NETWORK), db)["_id"]
    params = {"snapshot": snapshot, "reporter": TUNISIA}
    with TestClient(app) as client:
        found = client.get("/api/products/100119/network", params=params).json()
        assert client.get("/api/products/10/network", params=params).status_code == 422
    assert (found["heading"], found["year"]) == ("1001", 2024)
    assert found["suppliers"] == [{"countryCode": 251, "valueUsd": 54000}, {"countryCode": USA, "valueUsd": 20000}]
    assert found["peers"] == [{"countryCode": 380, "sharedSuppliers": 2, "valueUsd": 35000}]
    assert found["alternatives"] == [
        {"countryCode": CHINA, "markets": 1, "valueUsd": 40000}, {"countryCode": 4, "markets": 1, "valueUsd": 3000},
    ]
    assert found["paths"] == [{"origin": 4, "via": 251, "valueUsd": 3000}]
    assert found["links"] == [
        {"from": CHINA, "to": 380, "valueUsd": 40000}, {"from": 251, "to": 380, "valueUsd": 30000},
        {"from": USA, "to": 380, "valueUsd": 5000},
    ]
    assert found["names"]["4"] == "Afghanistan"


def test_a_missing_graph_or_twins_fails_only_its_own_panel(db, make_archive):
    snapshot = prepare(make_archive(NETWORK), db)
    folder = Path(os.environ["ATLAS_DATA"]) / snapshot["storage"]["path"]
    for part in ("graph", "twins"):
        gone = folder / snapshot[part]["path"]
        shutil.rmtree(gone) if gone.is_dir() else gone.unlink()
    params = {"snapshot": snapshot["_id"], "reporter": TUNISIA}
    with TestClient(app) as client:
        network = client.get("/api/products/100119/network", params=params)
        trade_twins = client.get("/api/twins", params=params)
        kept = [client.get(f"/api/{path}", params=params).status_code for path in ("overview", "exports", "products/100119/history")]
    assert (network.status_code, trade_twins.status_code) == (503, 503)
    assert network.json()["detail"] == f"the Ladybug graph of {snapshot['_id']} is unavailable"
    assert kept == [200, 200, 200]
    assert not (folder / snapshot["twins"]["path"]).exists()


def test_country_profile_sums_supplies_across_products(api):
    profile = settled(api, "/api/countries/251", year=2012)
    assert profile["country"]["countryName"] == "France"
    assert [(p["productCode"], p["valueUsd"], p["share"], p["rank"]) for p in profile["products"]] == [
        ("010121", 60000, 0.6, 1),
        ("310230", 2734, 1, 1),
    ]
    years = {y["year"]: y for y in profile["years"]}
    assert years[2012]["valueUsd"] == 62734
    assert years[2012]["shareOfImports"] == pytest.approx(62734 / 102734)
    assert years[2012]["productCount"] == 2
    assert (years[2012]["exportsUsd"], years[2012]["shareOfExports"]) == (5000, 1)
    assert years[2013]["valueUsd"] is None
    assert years[2015]["shareOfImports"] == 1


def test_country_profile_ranks_a_minor_supplier(api):
    [horses] = api.get("/api/countries/380", params={"year": 2012}).json()["products"]
    assert (horses["rank"], horses["share"], horses["supplierCount"]) == (2, 0.3, 3)


def test_unknown_country_is_not_found(api):
    assert api.get("/api/countries/999").status_code == 404


def test_routes_sum_countries_into_routes_and_chokepoints(api):
    body = settled(api, "/api/routes", year=2012)
    route = {r["id"]: r for r in body["routes"]}
    strait = {c["id"]: c for c in body["chokepoints"]}
    assert body["totalUsd"] == 102734
    assert route["mediterranean"]["valueUsd"] == 92734
    assert [c["countryName"] for c in route["mediterranean"]["countries"]] == ["France", "Italy"]
    assert route["americas"]["valueUsd"] == strait["gibraltar"]["valueUsd"] == 10000
    assert strait["gibraltar"]["share"] == pytest.approx(10000 / 102734)
    assert strait["suez"]["valueUsd"] == 0
    assert body["unrouted"]["valueUsd"] == 0
    assert {y["year"]: y["share"] for y in route["mediterranean"]["years"]}[2015] == 1


def test_routes_of_one_product(api):
    body = api.get("/api/routes", params={"year": 2012, "code": "31"}).json()
    assert body["totalUsd"] == 2734
    assert {r["id"]: r["valueUsd"] for r in body["routes"]}["americas"] == 0


def test_routes_follow_the_reporter(api):
    body = api.get("/api/routes", params={"year": 2012, "reporter": 380}).json()
    route = {r["id"]: r for r in body["routes"]}
    assert route["mediterranean"]["path"] is None
    assert route["americas"]["valueUsd"] == 0
    assert route["mediterranean"]["valueUsd"] == 100000


def test_country_profile_names_its_route(api):
    usa = api.get("/api/countries/842").json()["route"]
    assert (usa["id"], usa["via"]) == ("americas", ["Strait of Gibraltar"])


def test_each_country_has_one_region_and_every_route_ends_at_the_reporter():
    countries = [iso for r in routes.REGIONS for iso in r["countries"].split()]
    assert len(countries) == len(set(countries))
    for iso, hub in (("TUN", [11.5, 37.4]), ("USA", [-73.5, 40.3]), ("CHN", [123, 30.5])):
        assert all(r["path"][-1] == hub for r in routes.plan(iso) if r["path"])


def test_the_route_depends_on_the_reporter():
    via = {iso: {r["id"]: r["via"] for r in routes.plan(iso)} for iso in ("TUN", "USA")}
    assert via["TUN"]["east-asia"] == ["malacca", "bab", "suez"]
    assert via["TUN"]["gulf"] == ["hormuz", "bab", "suez"]
    assert via["TUN"]["baltic"] == ["danish", "gibraltar"]
    assert via["TUN"]["pacific-south-america"] == ["panama", "gibraltar"]
    assert via["USA"]["east-asia"] == ["panama"]
    assert routes.plan("ATA") == []


def test_a_closed_strait_sends_each_route_round_the_next_lane_or_cuts_it_off():
    red_sea = routes.detours("FRA", ("bab", "suez"))
    assert "suez" not in red_sea["east-asia"]["via"]
    assert red_sea["east-asia"]["extraDays"] > 10
    assert red_sea["red-sea"] is None
    assert routes.detours("IND", ("hormuz",))["gulf"] is None
    assert routes.detours("USA", ("panama",))["pacific-south-america"]["extraKm"] > 5000
    assert routes.detours("FRA", ()) == {}


def later_year(db, snapshot_id, code, totalUsd, hhi):
    generation = materialize.ensure(db, db.snapshots.find_one({"_id": snapshot_id}), TUNISIA)
    doc = db.country_product_years.find_one({"generationId": generation, "productCode": code, "year": 2012}, {"_id": 0})
    doc["year"] = 2015
    doc["imports"]["metrics"] = {**doc["imports"]["metrics"], "totalUsd": Decimal(totalUsd), "hhi": Decimal(hhi)}
    db.country_product_years.insert_one(doc)


def test_movers_split_rising_and_falling_concentration(api, db):
    later_year(db, api.snapshot, "010121", 120000, "0.9")
    later_year(db, api.snapshot, "310230", 3000, "0.5")
    moved = api.get("/api/movers", params={"from": 2012, "to": 2015}).json()
    assert moved["compared"] == 2
    assert [(r["productCode"], r["change"]) for r in moved["rising"]] == [("010121", pytest.approx(0.44))]
    assert [(r["productCode"], r["change"]) for r in moved["falling"]] == [("310230", -0.5)]


def test_movers_need_the_minimum_value_in_both_years(api, db):
    later_year(db, api.snapshot, "010121", 120000, "0.9")
    later_year(db, api.snapshot, "310230", 3000, "0.5")
    moved = api.get("/api/movers", params={"from": 2012, "to": 2015, "minValue": 2900}).json()
    assert moved["compared"] == 1
    assert moved["falling"] == []


# Thousands of USD: Tunisia sells the USA 60 and buys 10 back, China sells Tunisia 30 and the USA 40.
TWO_REPORTERS = {2012: ["2012,788,842,010121,60,1", "2012,842,788,010121,10,1", "2012,156,788,010121,30,1", "2012,156,842,010121,40,1"]}
EXPECTED = {TUNISIA: (40000, 60000, 0.625, 15000), USA: (100000, 10000, 0.52, 20000)}


@pytest.fixture
def two(db, make_archive):
    snapshot = prepare(make_archive(TWO_REPORTERS), db)
    with TestClient(app) as client:
        client.snapshot = snapshot["_id"]
        client.params = {"snapshot": snapshot["_id"], "year": 2012}
        yield client


def figures(client, reporter):
    [row] = client.get("/api/overview", params={"reporter": reporter}).json()["rows"]
    exports = client.get("/api/exports", params={"reporter": reporter}).json()
    cut = client.post("/api/scenarios/preview", json={
        "snapshot": client.snapshot, "reporter": reporter, "year": 2012, "suppliers": [CHINA], "reduction": 0.5,
    }).json()["result"]
    return row["metrics"]["totalUsd"], exports["years"][0]["exportsUsd"], row["metrics"]["hhi"], cut["affectedUsd"]


@pytest.mark.parametrize("order", [(TUNISIA, USA), (USA, TUNISIA)])
def test_each_reporter_sees_only_its_own_flows_whatever_the_visit_order(two, order):
    seen = {reporter: figures(two, reporter) for reporter in order}
    for reporter, (imports, exported, hhi, affected) in EXPECTED.items():
        assert seen[reporter][0] == imports
        assert seen[reporter][1] == exported
        assert seen[reporter][2] == pytest.approx(hhi)
        assert seen[reporter][3] == affected


@pytest.mark.parametrize(("reporter", "partner", "value"), [(TUNISIA, "USA", 60000), (USA, "Tunisia", 10000)])
def test_exports_list_destinations_and_products(two, reporter, partner, value):
    body = two.get("/api/exports", params={"reporter": reporter}).json()
    assert [(d["countryName"], d["share"]) for d in body["destinations"]] == [(partner, 1)]
    [horses] = body["products"]
    assert (horses["productCode"], horses["totalUsd"], horses["rca"]) == ("010121", value, 1)
    assert "destinations" not in horses


def test_an_evicted_view_is_rebuilt_with_the_same_figures(db, two):
    snapshot = db.snapshots.find_one({"_id": two.snapshot})
    first = materialize.ensure(db, snapshot, TUNISIA, budget=1)
    materialize.ensure(db, snapshot, USA, budget=1)
    assert db.materializations.find_one({"countryCode": TUNISIA})["status"] == "evicted"
    assert db.country_product_years.count_documents({"generationId": first}) == 0
    assert figures(two, TUNISIA) == figures(two, TUNISIA)
    assert figures(two, TUNISIA)[0] == 40000


def stored(db, generation):
    return sorted(db.country_product_years.find({"generationId": generation}, {"_id": 0, "generationId": 0}),
                  key=lambda d: (d["productCode"], d["year"]))


def test_a_first_visit_opens_on_the_first_and_last_years_and_fills_in_the_rest(db, make_archive, monkeypatch):
    snapshot = db.snapshots.find_one({"_id": prepare(make_archive({**FLOWS, **NETWORK}), db)["_id"]})
    gate, fill = threading.Event(), materialize.fill
    monkeypatch.setattr(materialize, "fill", lambda *args: gate.wait() and fill(*args))
    generation = materialize.ensure(db, snapshot, TUNISIA, [2024])
    assert db.materializations.find_one({"countryCode": TUNISIA})["years"] == [2012, 2024]
    assert sorted(db.country_product_years.distinct("year", {"generationId": generation})) == [2012, 2024]
    gate.set()
    assert materialize.ensure(db, snapshot, TUNISIA) == generation
    assert "years" not in db.materializations.find_one({"countryCode": TUNISIA})
    materialize.build(db, snapshot, TUNISIA, "whole")
    assert stored(db, generation) == stored(db, "whole")



def test_a_cold_product_page_answers_with_the_first_and_last_years_while_the_rest_fill_in(api, monkeypatch):
    gate, filled, fill = threading.Event(), threading.Event(), materialize.fill
    monkeypatch.setattr(materialize, "fill", lambda *args: gate.wait() and (fill(*args), filled.set()))
    first = api.get("/api/products/010121/history").json()
    assert ([y["year"] for y in first["years"]], first["filling"]) == ([2012, 2024], True)
    gate.set()
    assert filled.wait(10)
    whole = api.get("/api/products/010121/history").json()
    assert (len(whole["years"]) > 2, whole["filling"]) == (True, False)


def test_first_visits_build_two_years_at_once_and_queue_the_rest(monkeypatch):
    running, peak, lock = 0, 0, threading.Lock()

    def year(*args):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        threading.Event().wait(0.05)
        with lock:
            running -= 1

    monkeypatch.setattr(materialize, "build_year", year)
    visits = [threading.Thread(target=materialize.build, args=(None, {"years": [2012, 2024]}, c, c)) for c in range(5)]
    for t in visits:
        t.start()
    for t in visits:
        t.join()
    assert peak == 2

def test_a_fill_that_stopped_is_taken_over_once_its_lease_expires(db, make_archive, monkeypatch):
    snapshot = db.snapshots.find_one({"_id": prepare(make_archive({**FLOWS, **NETWORK}), db)["_id"]})
    monkeypatch.setattr(materialize, "fill", lambda *args: None)
    partial = materialize.ensure(db, snapshot, TUNISIA, [2012])
    db.materializations.update_one({"countryCode": TUNISIA}, {"$set": {"leaseUntil": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    whole = materialize.ensure(db, snapshot, TUNISIA)
    assert whole != partial
    assert "years" not in db.materializations.find_one({"countryCode": TUNISIA})
    assert sorted(db.country_product_years.distinct("year", {"generationId": whole})) == [2012, 2015, 2024]
    assert not db.country_product_years.count_documents({"generationId": partial})


def test_a_restart_rebuilds_the_countries_visited_last_the_latest_last(db, two):
    snapshot = db.snapshots.find_one({"_id": two.snapshot})
    materialize.ensure(db, snapshot, USA, budget=1)
    materialize.ensure(db, snapshot, TUNISIA, budget=1)
    assert db.materializations.find_one({"countryCode": USA})["status"] == "evicted"
    assert materialize.rewarm(db, snapshot) == [TUNISIA, USA]
    jobs = list(db.materializations.find(sort=[("lastUsedAt", -1)]))
    assert [(j["countryCode"], j["status"]) for j in jobs] == [(TUNISIA, "ready"), (USA, "ready")]


def test_a_failed_build_leaves_nothing_readable(db, two, monkeypatch):
    snapshot = db.snapshots.find_one({"_id": two.snapshot})

    def broken(db, snapshot, country, generation, years):
        db.country_product_years.insert_one({"generationId": generation, "productCode": "010121", "year": 2012})
        raise RuntimeError("disk full")

    monkeypatch.setattr(materialize, "build", broken)
    with pytest.raises(RuntimeError):
        materialize.ensure(db, snapshot, TUNISIA)
    assert db.materializations.find_one({"countryCode": TUNISIA})["status"] == "failed"
    assert db.country_product_years.count_documents({}) == 0
    monkeypatch.undo()
    assert figures(two, TUNISIA)[0] == 40000


def test_a_build_whose_lease_expired_is_taken_over(db, two):
    snapshot = db.snapshots.find_one({"_id": two.snapshot})
    stale = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.materializations.insert_one({"snapshotId": snapshot["_id"], "countryCode": TUNISIA, "status": "building",
                                    "generationId": "stale", "leaseUntil": stale})
    db.country_product_years.insert_one({"generationId": "stale", "productCode": "010121", "year": 2012})
    assert materialize.ensure(db, snapshot, TUNISIA) != "stale"
    assert db.country_product_years.count_documents({"generationId": "stale"}) == 0


def test_partner_views_carry_geodist_distance_border_and_language(db, make_archive, tmp_path):
    snapshot = prepare(make_archive(FLOWS), db, geo_paths=fixture_geography(tmp_path))
    params = {"snapshot": snapshot["_id"], "reporter": TUNISIA, "year": 2012}
    with TestClient(app) as client:
        france = client.get("/api/countries/251", params=params).json()
        usa = client.get("/api/countries/842", params=params).json()
        destinations = client.get("/api/exports", params=params).json()["destinations"]
        history = client.get("/api/products/010121/history", params=params).json()
    assert france["geography"] == {"distanceKm": 1501, "contiguous": False, "commonLanguage": True}
    assert usa["geography"] is None
    assert [(d["isoCode"], d["distanceKm"], d["commonLanguage"]) for d in destinations] == [("FRA", 1501, True)]
    assert {k: v["distanceKm"] for k, v in history["geography"].items()} == {"251": 1501, "380": 594}


def fixture_tariffs(tmp_path):
    """France and Italy share an EU schedule, China's rate on durum wheat is a range, and Afghanistan has no schedule."""
    rates, schedules = tmp_path / "tariffs.csv", tmp_path / "tariff-schedules.csv"
    rates.write_text(
        "schedule,year,nomenclature,productCode,rate,minRate,maxRate,sourceCodes,nationalLines,naLines\n"
        "EUN,2021,H5,100119,12.8,0,25.6,1,2,0\n"
        "TUN,2019,H5,100119,36,36,36,1,1,0\n"
        "USA,2021,H5,100119,0,0,0,1,3,0\n"
        "CHN,2021,H5,100119,,1,65,2,4,1\n"
        "TUN,2019,H5,010121,0,0,0,1,1,0\n",
        encoding="utf-8",
    )
    schedules.write_text("countryCode,schedule,year\n251,EUN,2021\n380,EUN,2021\n788,TUN,2019\n842,USA,2021\n156,CHN,2021\n", encoding="utf-8")
    return rates, schedules


def test_tariffs_give_every_market_its_schedules_rate_and_keep_ranges(db, make_archive, tmp_path):
    sold = {2024: ["2024,788,251,100119,4,1", "2024,788,156,100119,6,1", "2024,788,4,100119,1,1"]}
    archive = make_archive(FLOWS | sold)
    plain = prepare(archive, db)
    snapshot = prepare(archive, db, tariff_paths=fixture_tariffs(tmp_path))
    assert snapshot["_id"] != plain["_id"]
    countries = {c["isoCode"]: c.get("tariffSchedule") for c in snapshot["countries"]}
    assert countries["ITA"] == {"schedule": "EUN", "year": 2021} and countries["AFG"] is None
    with TestClient(app) as client:
        found = client.get("/api/products/100119/tariffs", params={"snapshot": snapshot["_id"], "reporter": TUNISIA})
        heading = client.get("/api/products/1001/tariffs", params={"snapshot": snapshot["_id"], "reporter": TUNISIA})
        missing = client.get("/api/products/100119/tariffs", params={"snapshot": plain["_id"], "reporter": TUNISIA})
    body = found.json()
    assert [(m["isoCode"], m["rate"], m["minRate"], m["maxRate"]) for m in body["markets"]] == [
        ("CHN", None, 1.0, 65.0), ("TUN", 36.0, 36.0, 36.0), ("FRA", 12.8, 0.0, 25.6), ("ITA", 12.8, 0.0, 25.6), ("USA", 0.0, 0.0, 0.0),
    ]
    assert body["markets"][0]["sourceCodes"] == 2
    assert body["exportYear"] == 2024
    assert {m["isoCode"]: m["exportsUsd"] for m in body["markets"]} == {"CHN": 6000, "TUN": None, "FRA": 4000, "ITA": None, "USA": None}
    assert body["own"]["schedule"] == "TUN"
    assert body["source"]["disclaimer"].endswith("the user assumes all risk in their use.")
    assert heading.status_code == 422 and missing.status_code == 404


def test_a_market_charges_the_reporter_its_best_preference_and_a_customs_union_nothing(db, make_archive, tmp_path):
    preferences, partners = tmp_path / "preferences.csv", tmp_path / "tariff-partners.csv"
    preferences.write_text(
        "partner,schedule,year,nomenclature,productCode,rate,minRate,maxRate,sourceCodes,nationalLines,naLines,prefLines\n"
        "P01,EUN,2021,H5,100119,5,0,10,1,2,0,1\n"
        "156,EUN,2021,H5,100119,8,8,8,1,2,0,2\n"
        "156,USA,2021,H5,100119,0,0,0,1,3,0,3\n"
        "Q02,CHN,2021,H5,100119,0,0,0,1,4,0,4\n"
        "C99,CHN,2021,H5,100119,0,0,0,1,4,0,4\n",
        encoding="utf-8",
    )
    partners.write_text("partner,name,group,members\nP01,Invented pact,1,156;4\n156,China,0,156\nQ02,Invented scheme,1,251;380;156\nC99,C99,1,\n", encoding="utf-8")
    snapshot = prepare(make_archive({**FLOWS, 2024: ["2024,156,251,100119,1,1"]}), db, tariff_paths=(*fixture_tariffs(tmp_path), preferences, partners))
    assert snapshot["tariffs"]["unresolvedPartners"] == ["C99"]
    with TestClient(app) as client:
        china = client.get("/api/products/100119/tariffs", params={"snapshot": snapshot["_id"], "reporter": CHINA}).json()
        france = client.get("/api/products/100119/tariffs", params={"snapshot": snapshot["_id"], "reporter": 251}).json()
    markets = {m["isoCode"]: m for m in china["markets"]}
    assert (markets["FRA"]["rate"], markets["FRA"]["mfn"]["rate"], markets["FRA"]["preference"]) == (5.0, 12.8, {"partner": "P01", "name": "Invented pact"})
    assert markets["USA"]["preference"] is None and markets["TUN"]["rate"] == 36.0
    assert china["charged"] == {
        "251": {"rate": 0.0, "minRate": 0.0, "maxRate": 0.0, "partner": "Q02", "name": "Invented scheme"},
        "380": {"rate": 0.0, "minRate": 0.0, "maxRate": 0.0, "partner": "Q02", "name": "Invented scheme"},
    }
    markets = {m["isoCode"]: m for m in france["markets"]}
    assert (markets["ITA"]["rate"], markets["ITA"]["preference"]["name"]) == (0.0, "customs union")
    assert markets["FRA"]["rate"] == 12.8 and france["own"]["isoCode"] == "FRA"


@pytest.fixture
def named(db, make_archive, tmp_path):
    snapshot = prepare(make_archive(NETWORK), db, hs_paths=hs_files(tmp_path))
    with TestClient(app) as client:
        client.params = {"snapshot": snapshot["_id"], "reporter": TUNISIA}
        yield client


def test_categories_sum_each_level_exactly(named):
    tree = named.get("/api/categories").json()
    assert (tree["year"], tree["totalUsd"]) == (2024, 83000)
    [vegetable, chemical] = tree["sections"]
    assert (vegetable["code"], vegetable["name"], vegetable["valueUsd"]) == ("II", "Vegetable products", 74000)
    [cereals] = vegetable["children"]
    [wheat] = cereals["children"]
    assert (wheat["code"], wheat["name"]) == ("1001", "Wheat and meslin")
    assert [(p["code"], p["valueUsd"]) for p in wheat["children"]] == [("100119", 70000), ("100199", 4000)]
    assert (chemical["code"], chemical["valueUsd"]) == ("VI", 9000)


def test_categories_need_hs_names(api):
    assert api.get("/api/categories").status_code == 404


def test_search_puts_a_named_heading_before_its_products(named):
    search = lambda q: [p["productCode"] for p in named.get("/api/products", params={"q": q}).json()]
    assert search("wheat") == ["1001", "100119"]
    assert search("cereal") == ["10"]
    assert search("fertil") == ["31", "3102", "310230"]
    assert search("live")[:2] == ["0101", "01"]
