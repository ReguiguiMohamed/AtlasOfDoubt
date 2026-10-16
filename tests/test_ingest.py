from decimal import Decimal

import pytest

from atlas.ingest import ImportFailed, ingest

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


def suppliers(db, code, year):
    doc = db.product_years.find_one({"productCode": code, "year": year})
    return {s["countryCode"]: s for s in doc["suppliers"]}


def test_importing_twice_creates_no_duplicates(db, make_archive):
    path = make_archive(FLOWS)
    first = ingest(path, db)
    second = ingest(path, db)
    assert first["status"] == second["status"] == "ready"
    assert db.product_years.count_documents({}) == 3
    assert db.products.count_documents({}) == 3
    assert db.snapshots.count_documents({}) == 1


def test_leading_zeros_survive(db, make_archive):
    ingest(make_archive(FLOWS), db)
    assert db.product_years.find_one({"year": 2012, "productCode": "010121"})
    assert db.products.find_one({"productCode": "010121"})["chapter"] == "01"


def test_values_are_converted_from_thousands_of_usd_exactly(db, make_archive):
    ingest(make_archive(FLOWS), db)
    assert suppliers(db, "010121", 2012)[251]["valueUsd"] == Decimal(60000)
    assert suppliers(db, "310230", 2012)[251]["valueUsd"] == Decimal(2734)
    assert suppliers(db, "310230", 2012)[251]["quantityTonnes"] == Decimal("0.044")


def test_missing_quantity_stays_missing(db, make_archive):
    ingest(make_archive(FLOWS), db)
    horses = suppliers(db, "010121", 2012)
    assert horses[380]["quantityTonnes"] is None
    assert horses[842]["quantityTonnes"] is None
    assert horses[380]["valueUsd"] == Decimal(30000)


def test_untrusted_rows_go_to_the_error_report(db, make_archive):
    snapshot = ingest(make_archive(FLOWS), db)
    assert snapshot["errors"]["byKind"] == {
        "duplicate flow key": 2,
        "unknown country code": 1,
        "unknown product code": 1,
    }
    assert db.product_years.find_one({"year": 2012, "productCode": "100119"}) is None


def test_metrics_and_world_comparison_are_stored(db, make_archive):
    ingest(make_archive(FLOWS), db)
    doc = db.product_years.find_one({"year": 2012, "productCode": "010121"})
    assert doc["metrics"]["hhi"] == Decimal("0.46")
    assert doc["world"]["totalUsd"] == Decimal(200000)
    assert doc["world"]["topSupplier"]["countryName"] == "France"
    assert 788 not in [e["countryCode"] for e in doc["world"]["topExporters"]]


def test_snapshot_records_provenance_and_counts(db, make_archive):
    snapshot = ingest(make_archive(FLOWS), db)
    assert len(snapshot["archive"]["sha256"]) == 64
    assert snapshot["reporter"] == {"countryCode": 788, "countryName": "Tunisia", "isoCode": "TUN"}
    assert snapshot["countries"][1] == {"countryCode": 251, "countryName": "France", "isoCode": "FRA", "iso2": "FR"}
    assert snapshot["counts"] == {
        "rows": 11,
        "tunisiaRows": 5,
        "productYears": 3,
        "products": 3,
        "dictionaryProducts": 3,
        "suppliers": 3,
    }
    assert db.products.find_one({"productCode": "100119"})["importYears"] == [2015]


def test_missing_year_fails_the_snapshot(db, make_archive):
    with pytest.raises(ImportFailed, match="Y2020"):
        ingest(make_archive(FLOWS, skip_year=2020), db)
    assert db.snapshots.find_one()["status"] == "failed"


def test_a_release_cannot_be_replaced_by_another_archive(db, make_archive):
    ingest(make_archive(FLOWS), db)
    with pytest.raises(ImportFailed, match="different archive"):
        ingest(make_archive({2012: ["2012,251,788,010121,1,1"]}), db)
