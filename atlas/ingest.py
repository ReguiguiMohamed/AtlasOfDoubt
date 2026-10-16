"""Import one BACI release into MongoDB, keeping the flows into Tunisia.

    python -m atlas.ingest data/raw/BACI_HS12_V202601.zip

Each annual file is streamed once. Rows into Tunisia become supplier lists
per product and year. Every row also feeds the world exporter totals per
product, which give the structural concentration a Tunisian figure is
compared against. Rows that cannot be trusted go to the snapshot's error
report instead of the data. The snapshot is marked ready only after all
thirteen years are written.
"""

import csv
import hashlib
import io
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from atlas import metrics
from atlas.db import connect

YEARS = range(2012, 2025)
REPORTER_ISO3 = "TUN"
HEADER = ["t", "i", "j", "k", "v", "q"]
SAMPLE_LIMIT = 100
WORLD_TOP = 5
CITATION = (
    "Gaulier, G. and Zignago, S. (2010). BACI: International Trade Database at the "
    "Product-Level. The 1994-2007 Version. CEPII Working Paper, N°2010-23."
)


class ImportFailed(Exception):
    pass


class ErrorReport:
    """Counts rejected rows by kind and keeps the first few as examples."""

    def __init__(self):
        self.counts = defaultdict(int)
        self.samples = []

    def reject(self, kind, file, line, row):
        self.counts[kind] += 1
        if len(self.samples) < SAMPLE_LIMIT:
            self.samples.append({"kind": kind, "file": file, "line": line, "row": row})

    def as_doc(self):
        return {"rejectedRows": sum(self.counts.values()), "byKind": dict(self.counts), "samples": self.samples}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def read_dictionary(archive, name, columns):
    if name not in archive.namelist():
        raise ImportFailed(f"{name} is missing from the archive")
    with archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, "utf-8-sig", newline=""))
        if not set(columns) <= set(reader.fieldnames or []):
            raise ImportFailed(f"{name} lacks columns {columns}")
        return [{c: row[c].strip() for c in columns} for row in reader]


def read_year(archive, name, year, countries, products, reporter, errors):
    """Supplier lists into the reporter and world exporter totals, per product.

    A Tunisian flow key seen twice is ambiguous, so every row sharing it is
    rejected. World totals skip that check because holding every key of a
    ten-million-row year in memory costs more than BACI's unique keys justify.
    """
    flows = defaultdict(list)
    world = defaultdict(lambda: defaultdict(Decimal))
    rows = 0
    with archive.open(name) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, "utf-8", newline=""))
        if next(reader, None) != HEADER:
            raise ImportFailed(f"{name}: header is not {','.join(HEADER)}")
        for line, row in enumerate(reader, start=2):
            rows += 1
            if len(row) != 6:
                errors.reject("malformed row", name, line, row)
                continue
            t, i, j, k, v, q = (cell.strip() for cell in row)
            k = k.zfill(6)
            try:
                value = Decimal(v) * 1000
                tonnes = None if q in ("", "NA") else Decimal(q)
            except InvalidOperation:
                errors.reject("malformed number", name, line, row)
                continue
            if t != str(year):
                errors.reject("year does not match file", name, line, row)
            elif value <= 0:
                errors.reject("non-positive value", name, line, row)
            elif i not in countries or j not in countries:
                errors.reject("unknown country code", name, line, row)
            elif k not in products:
                errors.reject("unknown product code", name, line, row)
            else:
                if i != reporter:
                    world[k][i] += value
                if j == reporter:
                    flows[(k, i)].append((line, row, value, tonnes))

    suppliers = defaultdict(list)
    for (k, i), found in flows.items():
        if len(found) > 1:
            for line, row, _, _ in found:
                errors.reject("duplicate flow key", name, line, row)
            continue
        _, _, value, tonnes = found[0]
        country, iso3 = countries[i]
        suppliers[k].append(
            {"countryCode": int(i), "countryName": country, "isoCode": iso3, "valueUsd": value, "quantityTonnes": tonnes}
        )
    return rows, sum(len(s) for s in suppliers.values()), suppliers, world


def world_summary(exporters, countries):
    entries = [
        {"countryCode": int(i), "countryName": countries[i][0], "isoCode": countries[i][1], "valueUsd": value}
        for i, value in exporters.items()
    ]
    return {
        **metrics.summarize(entries),
        "topExporters": [
            {"countryCode": e["countryCode"], "countryName": e["countryName"], "share": e["share"]}
            for e in metrics.with_shares(entries)[:WORLD_TOP]
        ],
    }


def ingest(path, db):
    path = Path(path)
    match = re.fullmatch(r"BACI_(HS\d\d)_V(\d+)\.zip", path.name)
    if not match:
        raise ImportFailed(f"{path.name} is not named like BACI_HS12_V202601.zip")
    classification, release = match.groups()
    snapshot_id = path.stem
    digest = sha256(path)

    existing = db.snapshots.find_one({"_id": snapshot_id})
    if existing and existing["status"] == "ready":
        if existing["archive"]["sha256"] != digest:
            raise ImportFailed(f"{snapshot_id} is already imported from a different archive")
        return existing
    db.product_years.delete_many({"snapshotId": snapshot_id})
    db.products.delete_many({"snapshotId": snapshot_id})

    snapshot = {
        "_id": snapshot_id,
        "status": "importing",
        "source": {
            "name": "CEPII BACI",
            "classification": classification,
            "release": release,
            "url": "https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37",
            "citation": CITATION,
            "license": "Etalab Open License 2.0",
            "valueUnit": "current USD, nominal",
            "quantityUnit": "metric tonnes",
        },
        "archive": {
            "filename": path.name,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "retrievedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        },
        "years": list(YEARS),
    }
    db.snapshots.replace_one({"_id": snapshot_id}, snapshot, upsert=True)

    try:
        with zipfile.ZipFile(path) as archive:
            country_rows = read_dictionary(
                archive, f"country_codes_V{release}.csv", ["country_code", "country_name", "country_iso2", "country_iso3"]
            )
            product_rows = read_dictionary(archive, f"product_codes_{classification}_V{release}.csv", ["code", "description"])
            countries = {r["country_code"]: (r["country_name"], r["country_iso3"]) for r in country_rows}
            iso2 = {r["country_code"]: r["country_iso2"] or None for r in country_rows}
            products = {r["code"].zfill(6): r["description"] for r in product_rows}
            reporter = next((code for code, (_, iso3) in countries.items() if iso3 == REPORTER_ISO3), None)
            if reporter is None:
                raise ImportFailed(f"{REPORTER_ISO3} is not in the country dictionary")

            errors = ErrorReport()
            files, import_years, supplier_codes = [], defaultdict(list), set()
            for year in YEARS:
                name = f"BACI_{classification}_Y{year}_V{release}.csv"
                if name not in archive.namelist():
                    raise ImportFailed(f"{name} is missing from the archive")
                rows, accepted, suppliers, world = read_year(archive, name, year, countries, products, reporter, errors)
                docs = []
                for k, entries in sorted(suppliers.items()):
                    entries.sort(key=lambda s: s["valueUsd"], reverse=True)
                    docs.append({
                        "snapshotId": snapshot_id,
                        "productCode": k,
                        "description": products[k],
                        "year": year,
                        "suppliers": entries,
                        "metrics": metrics.summarize(entries),
                        "world": world_summary(world[k], countries),
                    })
                    import_years[k].append(year)
                    supplier_codes.update(s["countryCode"] for s in entries)
                if docs:
                    db.product_years.insert_many(docs, ordered=False)
                files.append({"name": name, "rows": rows, "tunisiaRows": accepted, "products": len(docs)})
                print(f"{year}: {rows:,} rows, {accepted:,} into Tunisia across {len(docs):,} products", flush=True)

            db.products.insert_many(
                [
                    {
                        "snapshotId": snapshot_id,
                        "productCode": k,
                        "description": description,
                        "chapter": k[:2],
                        "heading": k[:4],
                        "importYears": import_years.get(k, []),
                    }
                    for k, description in sorted(products.items())
                ],
                ordered=False,
            )
    except Exception as exc:
        db.snapshots.update_one({"_id": snapshot_id}, {"$set": {"status": "failed", "failure": str(exc)}})
        raise

    reporter_name, reporter_iso3 = countries[reporter]
    ready = {
        "status": "ready",
        "importedAt": datetime.now(timezone.utc),
        "reporter": {"countryCode": int(reporter), "countryName": reporter_name, "isoCode": reporter_iso3},
        "countries": [
            {"countryCode": int(code), "countryName": name, "isoCode": iso3, "iso2": iso2[code]}
            for code, (name, iso3) in sorted(countries.items(), key=lambda item: item[1][0])
        ],
        "files": files,
        "counts": {
            "rows": sum(f["rows"] for f in files),
            "tunisiaRows": sum(f["tunisiaRows"] for f in files),
            "productYears": sum(f["products"] for f in files),
            "products": len(import_years),
            "dictionaryProducts": len(products),
            "suppliers": len(supplier_codes),
        },
        "errors": errors.as_doc(),
    }
    db.snapshots.update_one({"_id": snapshot_id}, {"$set": ready})
    return db.snapshots.find_one({"_id": snapshot_id})


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    client, database = connect()
    with client:
        result = ingest(sys.argv[1], database)
    print(f"{result['_id']} {result['status']}: {result['counts']}, {result['errors']['rejectedRows']} rows rejected")
