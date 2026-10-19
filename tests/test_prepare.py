import io
import json
import zipfile
from decimal import Decimal

import pytest

from atlas import materialize
from atlas.prepare import DATA, PrepareFailed, prepare, read_categories, read_dictionary, read_gdp, read_geography
from tests.test_coverage import STATA_MISSING, write_dta

FLOWS = {
    2012: [
        "2012,251,788,010121,60,1.5",
        "2012,380,788,010121,30,",
        "2012,842,788,010121,10,NA",
        "2012,251,380,010121,100,4",
        "2012,788,251,010121,5,0.1",
        "2012,842,788,100119,1,1",
        "2012,842,788,100119,2,2",
        "2012,999,788,100119,7,1",
        "2012,251,788,999999,7,1",
        "2012,251,788,310230,2.734,0.044",
    ],
    2015: ["2015,251,788,100119,1.5,3"],
}
# In 2024 France and the USA sell Tunisia wheat. Italy buys from both and from China, and France buys from Afghanistan.
NETWORK = {
    2024: [
        "2024,251,788,100119,50,1",
        "2024,251,788,100199,4,1",
        "2024,842,788,100119,20,1",
        "2024,251,380,100119,30,1",
        "2024,842,380,100119,5,1",
        "2024,156,380,100119,40,1",
        "2024,4,251,100119,3,1",
        "2024,251,788,310230,9,1",
    ],
}


def cached(db, snapshot, country, code, year):
    generation = materialize.ensure(db, snapshot, country)
    return db.country_product_years.find_one({"generationId": generation, "productCode": code, "year": year})


def suppliers(db, snapshot, code, year):
    return {s["countryCode"]: s for s in cached(db, snapshot, 788, code, year)["imports"]["suppliers"]}


def test_preparing_twice_creates_no_duplicates(db, make_archive):
    path = make_archive(FLOWS)
    first = prepare(path, db)
    second = prepare(path, db)
    assert first["_id"] == second["_id"]
    assert first["_id"].startswith("BACI_HS12_V202601@")
    assert second["status"] == "ready"
    assert db.world_product_years.count_documents({}) == 3
    assert db.products.count_documents({}) == 4
    assert db.snapshots.count_documents({}) == 1


def test_leading_zeros_survive(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    assert cached(db, snapshot, 788, "010121", 2012)
    assert db.products.find_one({"productCode": "010121"})["chapter"] == "01"


def test_values_are_converted_from_thousands_of_usd_exactly(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    assert suppliers(db, snapshot, "010121", 2012)[251]["valueUsd"] == Decimal(60000)
    assert suppliers(db, snapshot, "310230", 2012)[251]["valueUsd"] == Decimal(2734)
    assert suppliers(db, snapshot, "310230", 2012)[251]["quantityTonnes"] == Decimal("0.044")


def test_missing_quantity_stays_missing(db, make_archive):
    horses = suppliers(db, prepare(make_archive(FLOWS), db), "010121", 2012)
    assert horses[380]["quantityTonnes"] is None
    assert horses[842]["quantityTonnes"] is None
    assert horses[380]["valueUsd"] == Decimal(30000)


def test_untrusted_rows_go_to_the_error_report(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    assert snapshot["errors"]["byKind"] == {
        "duplicate flow key": 2,
        "unknown country code": 1,
        "unknown product code": 1,
    }
    assert cached(db, snapshot, 788, "100119", 2012) is None


def test_each_broken_row_is_named_with_its_line(db, make_archive):
    rows = [
        "2012,251,788,010121,60,1.5",
        "2012,251",
        "2012,380,788,010121,lots,1",
        "2013,842,788,010121,1,1",
        "2012,842,788,100119,0,1",
        "2012,842,788,310230,1.0005,x",
    ]
    snapshot = prepare(make_archive({2012: rows}), db)
    assert snapshot["errors"]["byKind"] == {
        "malformed row": 1,
        "malformed number": 1,
        "year does not match file": 1,
        "non-positive value": 1,
    }
    assert [(s["line"], s["kind"]) for s in snapshot["errors"]["samples"]] == [
        (3, "malformed row"),
        (4, "malformed number"),
        (5, "year does not match file"),
        (6, "non-positive value"),
    ]
    [year] = [f for f in snapshot["files"] if f["name"].startswith("BACI_HS12_Y2012")]
    assert (year["rows"], year["flows"], year["roundedValues"], year["unreadableQuantities"]) == (6, 2, 1, 1)
    assert suppliers(db, snapshot, "310230", 2012)[842]["valueUsd"] == Decimal(1001)


def test_metrics_and_world_comparison_leave_the_reporter_out(db, make_archive):
    doc = cached(db, prepare(make_archive(FLOWS), db), 788, "010121", 2012)
    assert doc["imports"]["metrics"]["hhi"] == Decimal("0.46")
    world = doc["imports"]["world"]
    assert world["totalUsd"] == Decimal(200000)
    assert world["hhi"] == Decimal(160**2 + 30**2 + 10**2) / 200**2
    assert world["topSupplier"]["countryName"] == "France"
    assert 788 not in [e["countryCode"] for e in world["topExporters"]]


def test_exports_carry_rca_unit_value_and_coverage(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    horses = cached(db, snapshot, 251, "010121", 2012)["exports"]
    assert horses["totalUsd"] == Decimal(160000)
    assert horses["quantityValidValueUsd"] == Decimal(160000)
    assert horses["unitValueUsdPerTonne"] == Decimal(160000) / Decimal("5.5")
    assert float(horses["rca"]) == pytest.approx((160000 / 162734) / (205000 / 207734))
    usa = cached(db, snapshot, 842, "010121", 2012)["exports"]
    assert (usa["quantityCoverage"], usa["unitValueUsdPerTonne"]) == (0, None)
    assert "partial quantities" in usa["qualityFlags"]
    france = db.country_years.find_one({"countryCode": 251, "year": 2012})
    assert france["exportsUsd"] == Decimal(162734)
    assert [d["countryCode"] for d in france["destinations"]] == [380, 788]


def test_snapshot_records_provenance_counts_and_files(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    assert len(snapshot["archive"]["sha256"]) == 64
    assert snapshot["countries"][1] == {"countryCode": 380, "countryName": "Italy", "isoCode": "ITA", "iso2": "IT"}
    assert snapshot["counts"] == {
        "rows": 11,
        "flows": 7,
        "roundedValues": 0,
        "unreadableQuantities": 0,
        "dictionaryProducts": 4,
        "countries": 4,
    }
    manifest = json.loads((DATA / snapshot["storage"]["path"] / "manifest.json").read_text())
    assert sum(f["rows"] for f in manifest if f["path"].startswith("flows/")) == 7
    assert snapshot["storage"]["files"] == len(manifest)
    assert not list(DATA.glob("*.partial"))


def test_countries_that_never_trade_stay_out_of_the_snapshot(db, make_archive):
    snapshot = prepare(make_archive(FLOWS), db)
    assert [c["countryCode"] for c in snapshot["countries"]] == [251, 380, 788, 842]


def test_graph_holds_the_last_year_once_per_exporter_importer_and_heading(db, make_archive):
    snapshot = prepare(make_archive(NETWORK), db)
    assert {k: snapshot["graph"][k] for k in ("path", "year", "edges", "valueUsd")} == {
        "path": "graph.lbug", "year": 2024, "edges": 7, "valueUsd": 161000,
    }
    assert snapshot["graph"]["valueUsd"] == snapshot["worldTotals"]["2024"]
    assert (DATA / snapshot["storage"]["path"] / "graph.lbug").stat().st_size == snapshot["graph"]["bytes"]


def test_missing_year_fails_the_snapshot(db, make_archive):
    with pytest.raises(PrepareFailed, match="Y2020"):
        prepare(make_archive(FLOWS, skip_year=2020), db)
    assert db.snapshots.find_one()["status"] == "failed"
    assert not list(DATA.glob("*.partial"))


def test_another_archive_of_the_same_release_is_another_snapshot(db, make_archive):
    first = prepare(make_archive(FLOWS), db)
    second = prepare(make_archive({2012: ["2012,251,788,010121,1,1"]}), db)
    assert first["_id"] != second["_id"]
    assert db.snapshots.count_documents({"status": "ready"}) == 2


def gdp_file(tmp_path, values):
    meta = {"page": 1, "pages": 1, "per_page": 20000, "total": len(values), "lastupdated": "2026-10-08"}
    rows = [
        {"indicator": {"id": "NY.GDP.PCAP.PP.KD", "value": "GDP per capita, PPP"}, "countryiso3code": iso, "date": str(year), "value": value}
        for iso, year, value in values
    ]
    path = tmp_path / "wdi-gdp.json"
    path.write_text(json.dumps([meta, rows]))
    return path


def test_gdp_maps_iso3_codes_and_lists_what_it_left_out(tmp_path):
    path = gdp_file(tmp_path, [("FRA", 2012, 40000.5), ("USA", 2012, None), ("AFE", 2012, 3000), ("ITA", 2013, -1)])
    country_rows = [{"country_code": "251", "country_iso3": "FRA"}, {"country_code": "842", "country_iso3": "USA"}]
    gdp, provenance = read_gdp(path, country_rows)
    assert gdp == {251: {2012: Decimal("40000.5")}}
    assert provenance["leftOut"] == ["AFE"]
    assert provenance["countries"] == 1


def test_prody_and_expy_use_same_year_income(db, make_archive, tmp_path):
    incomes = {"FRA": 40000, "ITA": 30000, "USA": 60000, "TUN": 10000}
    years = [(iso, year, gdp) for iso, gdp in incomes.items() for year in range(2012, 2025)]
    snapshot = prepare(make_archive(FLOWS), db, gdp_file(tmp_path, years))
    horses = db.world_product_years.find_one({"productCode": "010121", "year": 2012})
    # Horses are 160/162.734 of France's exports and all of what Italy, the USA and Tunisia export.
    france = Decimal(160000) / Decimal(162734)
    expected = (france * 40000 + 30000 + 60000 + 10000) / (france + 3)
    assert horses["prody"] == expected
    assert horses["prodyCoverage"] == 1
    italy = db.country_years.find_one({"countryCode": 380, "year": 2012})
    assert italy["expy"]["value"] == expected
    assert italy["expyFixed2012"]["value"] == expected
    assert snapshot["gdp"]["countries"] == 4


GEO_COLUMNS = [("iso3", 3), ("landlocked", 251)]
DIST_COLUMNS = [("iso_o", 3), ("iso_d", 3), ("dist", 255), ("contig", 251), ("comlang_off", 251)]


def geo_files(tmp_path, geo_rows, dist_rows):
    paths = tmp_path / "geo_cepii.dta", tmp_path / "dist_cepii.dta"
    write_dta(paths[0], GEO_COLUMNS, geo_rows)
    write_dta(paths[1], DIST_COLUMNS, dist_rows)
    return paths


def fixture_geography(tmp_path):
    """France and Italy at their GeoDist distances from Tunisia, and Afghanistan landlocked."""
    return geo_files(
        tmp_path,
        [("FRA", 0), ("ITA", 0), ("TUN", 0), ("AFG", 1)],
        [("TUN", "FRA", 1500.6, 0, 1), ("FRA", "TUN", 1500.6, 0, 1), ("TUN", "ITA", 594.2, 0, 0), ("ITA", "TUN", 594.2, 0, 0)],
    )


def test_geography_maps_aliases_and_skips_pairs_inside_one_entity(tmp_path):
    paths = geo_files(
        tmp_path,
        [("FRA", 0), ("FRA", 0), ("YUG", 1), ("TUN", 0)],
        [("FRA", "YUG", 1400.4, 0, 0), ("YUG", "YUG", 300.0, 0, 1), ("FRA", "FRA", 100.0, 0, 1),
         ("FRA", "TUN", 1500.6, 0, 1), ("TUN", "YUG", STATA_MISSING, 0, 0), ("FRA", "ITA", 1100.0, 1, 0)],
    )
    country_rows = [{"country_code": c, "country_iso3": i} for c, i in [("251", "FRA"), ("688", "SRB"), ("499", "MNE"), ("788", "TUN"), ("842", "USA")]]
    pairs, landlocked, provenance = read_geography(*paths, country_rows)
    assert pairs[251, 688] == pairs[251, 499] == {"distanceKm": 1400, "contiguous": False, "commonLanguage": False}
    assert pairs[251, 788] == {"distanceKm": 1501, "contiguous": False, "commonLanguage": True}
    assert set(pairs) == {(251, 688), (251, 499), (251, 788)}
    assert landlocked == {251: False, 688: True, 499: True, 788: False}
    assert (provenance["countries"], provenance["unmatched"]) == (4, [842])


def test_geography_changes_the_snapshot_id_and_is_stored_per_pair(db, make_archive, tmp_path):
    flows = {**FLOWS, 2024: ["2024,4,251,100119,3,1"]}
    without = prepare(make_archive(flows), db)
    snapshot = prepare(make_archive(flows), db, geo_paths=fixture_geography(tmp_path))
    assert snapshot["_id"] != without["_id"]
    assert db.geo_pairs.count_documents({"snapshotId": without["_id"]}) == 0
    assert db.geo_pairs.count_documents({"snapshotId": snapshot["_id"]}) == 4
    pair = db.geo_pairs.find_one({"snapshotId": snapshot["_id"], "countryCode": 788, "partnerCode": 251}, {"_id": 0, "distanceKm": 1})
    assert pair == {"distanceKm": 1501}
    assert {c["isoCode"]: c.get("landlocked") for c in snapshot["countries"]} == {
        "AFG": True, "FRA": False, "ITA": False, "TUN": False, "USA": None,
    }
    assert snapshot["geography"]["unmatched"] == [156, 842]
    assert snapshot["manifest"]["geodistSha256"] == [f["sha256"] for f in snapshot["geography"]["files"]]


def test_names_encoded_twice_are_repaired_and_clean_names_kept():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("c.csv", "country_name\nCÃ´te d'Ivoire\nTÃ¼rkiye\nCôte d'Ivoire\n\"Korea, Rep.\"\n".encode("utf-8"))
    with zipfile.ZipFile(buffer) as archive:
        rows = read_dictionary(archive, "c.csv", ["country_name"])
    assert [r["country_name"] for r in rows] == ["Côte d'Ivoire", "Türkiye", "Côte d'Ivoire", "Korea, Rep."]


def hs_files(tmp_path):
    """DataHub-shaped HS files with heading 3102 left out, as headings HS 2022 dropped are."""
    hs, sections = tmp_path / "harmonized-system.csv", tmp_path / "sections.csv"
    hs.write_text(
        "section,hscode,description,parent,level\n"
        'I,01,"Animals; live",TOTAL,2\n'
        'I,0101,"Live horses, asses, mules and hinnies",01,4\n'
        'I,010121,"Horses; live, pure-bred breeding animals",0101,6\n'
        "II,10,Cereals,TOTAL,2\n"
        "II,1001,Wheat and meslin,10,4\n"
        "VI,31,Fertilizers,TOTAL,2\n",
        encoding="utf-8",
    )
    # The real file opens with a byte order mark, writes section I in lower case and pads section II.
    sections.write_text(
        "﻿section,name\nI,live animals; animal products\nII,Vegetable products \nVI,Products of the chemical or allied industries\n",
        encoding="utf-8",
    )
    return hs, sections


def test_categories_name_every_level_and_fall_back_to_the_description(tmp_path, products):
    fields, provenance = read_categories(*hs_files(tmp_path), products)
    assert fields["100199"] == {"section": "II", "sectionName": "Vegetable products", "chapterName": "Cereals", "headingName": "Wheat and meslin"}
    assert fields["010121"]["sectionName"] == "Live animals; animal products"
    assert fields["310230"]["headingName"] == "Fertilizers"
    assert (provenance["named"], provenance["fallback"]) == (5, ["3102"])


def test_hs_names_change_the_snapshot_id_and_join_each_product(db, make_archive, tmp_path):
    without = prepare(make_archive(FLOWS), db)
    snapshot = prepare(make_archive(FLOWS), db, hs_paths=hs_files(tmp_path))
    assert snapshot["_id"] != without["_id"]
    assert "chapterName" not in db.products.find_one({"snapshotId": without["_id"]})
    wheat = db.products.find_one({"snapshotId": snapshot["_id"], "productCode": "100119"}, {"_id": 0, "headingName": 1, "section": 1})
    assert wheat == {"section": "II", "headingName": "Wheat and meslin"}
    assert snapshot["manifest"]["hsSha256"] == [f["sha256"] for f in snapshot["categories"]["files"]]
