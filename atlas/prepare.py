"""Prepare one BACI release, and optionally WDI GDP, as a snapshot any country can be read from.

    python -m atlas.prepare data/raw/BACI_HS12_V202601.zip [data/raw/wdi-gdp.json]

Each annual CSV is checked in DuckDB. Valid flows are written once as Parquet
partitioned by importer and year, so one country's imports never need a scan
of the world. Exports per country and product, world totals per product and
country-year summaries are computed here, because RCA and PRODY need every
exporter at once. Rows that cannot be trusted go to the error report. The
snapshot id hashes every input, so a second run with the same files returns
the snapshot it already made, and a new GDP file or formula gives a new id.
"""

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

from atlas import metrics
from atlas.db import connect

YEARS = range(2012, 2025)
HEADER = "t,i,j,k,v,q"
SAMPLE_LIMIT = 100
WORLD_TOP = 6
LAYOUT_VERSION = "1"
DATA = Path(os.environ.get("ATLAS_DATA", "data/snapshots"))
GDP_INDICATOR = "NY.GDP.PCAP.PP.KD"
GDP_URL = f"https://api.worldbank.org/v2/country/all/indicator/{GDP_INDICATOR}?format=json&date=2012:2024&per_page=20000"
CITATION = (
    "Gaulier, G. and Zignago, S. (2010). BACI: International Trade Database at the "
    "Product-Level. The 1994-2007 Version. CEPII Working Paper, N°2010-23."
)

# Every line becomes one text column so a short row still gets its line number and its raw text.
CHECK = """
CREATE OR REPLACE TABLE checked AS
WITH lines AS (
    SELECT row_number() OVER () + 1 AS line, line AS raw
    FROM read_csv(?, header = false, skip = 1, columns = {'line': 'VARCHAR'}, delim = '\x01', quote = '', escape = '', auto_detect = false)
), cells AS (
    SELECT line, raw, string_split(raw, ',') AS c FROM lines
), parsed AS (
    SELECT line, raw, len(c) = 6 AS shaped, trim(c[1]) AS t, trim(c[2]) AS i, trim(c[3]) AS j,
        CASE WHEN length(trim(c[4])) < 6 THEN lpad(trim(c[4]), 6, '0') ELSE trim(c[4]) END AS k, trim(c[5]) AS v_text, trim(c[6]) AS q_text,
        TRY_CAST(trim(c[5]) AS DECIMAL(18, 3)) AS v, TRY_CAST(trim(c[6]) AS DECIMAL(18, 3)) AS q
    FROM cells
)
SELECT line, raw, i, j, k, v,
    CASE WHEN q_text IN ('', 'NA') THEN NULL ELSE q END AS q,
    q_text NOT IN ('', 'NA') AND q IS NULL AS bad_q,
    TRY_CAST(v_text AS DECIMAL(38, 18)) <> v OR TRY_CAST(q_text AS DECIMAL(38, 18)) <> q AS rounded,
    CASE
        WHEN raw IS NULL OR NOT shaped THEN 'malformed row'
        WHEN v IS NULL THEN 'malformed number'
        WHEN t <> ? THEN 'year does not match file'
        WHEN v <= 0 THEN 'non-positive value'
        WHEN i NOT IN (SELECT code FROM countries) OR j NOT IN (SELECT code FROM countries) THEN 'unknown country code'
        WHEN k NOT IN (SELECT code FROM products) THEN 'unknown product code'
    END AS kind
FROM parsed
"""

# A flow key seen twice is ambiguous, so every row sharing it is rejected.
DUPLICATES = """
UPDATE checked SET kind = 'duplicate flow key'
WHERE kind IS NULL AND (i, j, k) IN (SELECT (i, j, k) FROM checked WHERE kind IS NULL GROUP BY i, j, k HAVING count(*) > 1)
"""

FLOWS = """
CREATE OR REPLACE TABLE flows AS
SELECT CAST(j AS INTEGER) AS importer, k AS product, CAST(i AS INTEGER) AS exporter, v, q
FROM checked WHERE kind IS NULL
"""

# Values here are USD. Only flows with a positive quantity enter a unit value, so the value and tonnes stay matched.
EXPORTS = """
CREATE OR REPLACE TABLE exports AS
SELECT exporter AS country, product, sum(v) * 1000 AS value,
    coalesce(sum(v) FILTER (WHERE q > 0), 0) * 1000 AS quantity_value, sum(q) FILTER (WHERE q > 0) AS tonnes
FROM flows GROUP BY ALL
"""

WORLD = """
WITH ranked AS (
    SELECT *, row_number() OVER (PARTITION BY product ORDER BY value DESC, country) AS r FROM exports
)
SELECT product, sum(value), sum(value * value), count(*), sum(quantity_value), sum(tonnes),
    list({'countryCode': country, 'valueUsd': value} ORDER BY r) FILTER (WHERE r <= ?)
FROM ranked GROUP BY product
"""


class PrepareFailed(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def quoted(path):
    return "'" + Path(path).as_posix().replace("'", "''") + "'"


def read_dictionary(archive, name, columns):
    if name not in archive.namelist():
        raise PrepareFailed(f"{name} is missing from the archive")
    with archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, "utf-8-sig", newline=""))
        if not set(columns) <= set(reader.fieldnames or []):
            raise PrepareFailed(f"{name} lacks columns {columns}")
        return [{c: row[c].strip() for c in columns} for row in reader]


def read_gdp(path, country_rows):
    """WDI GDP per capita as {BACI code: {year: value}}, with its provenance.

    WDI keys countries by ISO3. BACI gives a few codes the same ISO3, and each
    takes that country's value. Regional aggregates and codes BACI lacks are
    left out and listed. Missing years stay missing, with no forward fill.
    """
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        meta, rows = json.load(f, parse_float=Decimal, parse_int=Decimal)
    if meta["pages"] != 1:
        raise PrepareFailed(f"{path.name} holds page 1 of {meta['pages']}, download it with per_page=20000")
    codes = defaultdict(list)
    for r in country_rows:
        codes[r["country_iso3"]].append(int(r["country_code"]))
    gdp, left_out = defaultdict(dict), set()
    for r in rows:
        if r["indicator"]["id"] != GDP_INDICATOR:
            raise PrepareFailed(f"{path.name} holds {r['indicator']['id']}, not {GDP_INDICATOR}")
        if r["value"] is None or r["value"] <= 0:
            continue
        if r["countryiso3code"] not in codes:
            left_out.add(r["countryiso3code"])
            continue
        for code in codes[r["countryiso3code"]]:
            gdp[code][int(r["date"])] = r["value"]
    provenance = {
        "name": "World Bank WDI",
        "indicator": GDP_INDICATOR,
        "description": rows[0]["indicator"]["value"] if rows else None,
        "url": GDP_URL,
        "license": "CC BY 4.0",
        "lastUpdated": meta.get("lastupdated"),
        "filename": path.name,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "retrievedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        "countries": len(gdp),
        "leftOut": sorted(c for c in left_out if c),
    }
    return dict(gdp), provenance


def check_year(con, csv_path, name, year, errors, samples):
    """Validate one annual file into the flows table and return its file record."""
    with open(csv_path, encoding="utf-8") as f:
        if f.readline().strip() != HEADER:
            raise PrepareFailed(f"{name}: header is not {HEADER}")
    con.execute(CHECK, [Path(csv_path).as_posix(), str(year)])
    con.execute(DUPLICATES)
    con.execute(FLOWS)
    for kind, n in con.execute("SELECT kind, count(*) FROM checked WHERE kind IS NOT NULL GROUP BY kind").fetchall():
        errors[kind] += n
    room = SAMPLE_LIMIT - len(samples)
    for kind, line, raw in con.execute(
        "SELECT kind, line, raw FROM checked WHERE kind IS NOT NULL ORDER BY line LIMIT ?", [room]
    ).fetchall():
        samples.append({"kind": kind, "file": name, "line": line, "row": raw.split(",") if raw else []})
    rows, flows, rounded, bad_q, total = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE kind IS NULL), count(*) FILTER (WHERE kind IS NULL AND rounded),"
        " count(*) FILTER (WHERE kind IS NULL AND bad_q), coalesce(sum(v) FILTER (WHERE kind IS NULL), 0) FROM checked"
    ).fetchone()
    return {"name": name, "rows": rows, "flows": flows, "roundedValues": rounded, "unreadableQuantities": bad_q, "valueThousandsUsd": total}


def write_year(con, out, year, record):
    """Write the year's flows and exports as Parquet, then read the flows back to prove nothing was lost."""
    con.execute(EXPORTS)
    options = "FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000, OVERWRITE_OR_IGNORE"
    con.execute(
        f"COPY (SELECT importer, {year} AS year, product, exporter, v, q FROM flows ORDER BY importer, product, exporter)"
        f" TO {quoted(out / 'flows')} ({options}, PARTITION_BY (importer, year))"
    )
    con.execute(
        f"COPY (SELECT country, {year} AS year, product, value, quantity_value, tonnes FROM exports ORDER BY country, product)"
        f" TO {quoted(out / 'exports')} ({options}, PARTITION_BY (country, year))"
    )
    if record["flows"]:
        written = con.execute(
            f"SELECT count(*), sum(v) FROM read_parquet({quoted(out / 'flows' / '*' / f'year={year}' / '*.parquet')})"
        ).fetchone()
        if written != (record["flows"], record["valueThousandsUsd"]):
            raise PrepareFailed(f"{record['name']}: Parquet holds {written}, expected {record['flows']} flows")


def summarize_year(con, snapshot_id, year, gdp, common, prody_2012):
    """World product and country-year documents for one year, plus the world export total."""
    world_rows = con.execute(WORLD, [WORLD_TOP]).fetchall()
    export_rows = con.execute("SELECT country, product, value FROM exports").fetchall()
    destinations = defaultdict(list)
    for exporter, importer, value in con.execute(
        "SELECT exporter, importer, sum(v) * 1000 AS value FROM flows GROUP BY ALL ORDER BY value DESC, importer"
    ).fetchall():
        destinations[exporter].append({"countryCode": importer, "valueUsd": value})
    imports = dict(con.execute("SELECT importer, sum(v) * 1000 FROM flows GROUP BY importer").fetchall())

    baskets = defaultdict(dict)
    for country, product, value in export_rows:
        baskets[country][product] = value
    year_gdp = {c: by_year[year] for c, by_year in gdp.items() if year in by_year}
    prody = metrics.prody(baskets, year_gdp)
    if year == YEARS[0]:
        prody_2012.update(metrics.prody({c: b for c, b in baskets.items() if c in common}, year_gdp))

    world_docs = []
    for product, total, squares, exporters, quantity_value, tonnes, top in world_rows:
        covered = sum((v for c, v in ((c, baskets[c].get(product)) for c in year_gdp) if v), metrics.ZERO)
        world_docs.append({
            "snapshotId": snapshot_id, "productCode": product, "year": year,
            "totalUsd": total, "sumSquares": squares, "exporterCount": exporters, "topExporters": top,
            "unitValueUsdPerTonne": metrics.unit_value(quantity_value, tonnes),
            "prody": prody.get(product), "prodyCoverage": covered / total if gdp else None,
        })

    country_docs = []
    for country in sorted(imports.keys() | baskets.keys()):
        basket = baskets.get(country, {})
        country_docs.append({
            "snapshotId": snapshot_id, "countryCode": country, "year": year,
            "importsUsd": imports.get(country, metrics.ZERO),
            "exportsUsd": sum(basket.values(), metrics.ZERO),
            "productHhi": metrics.hhi(basket.values()),
            "geoHhi": metrics.hhi(d["valueUsd"] for d in destinations[country]),
            "expy": metrics.expy(basket, prody) if gdp else None,
            "expyFixed2012": metrics.expy(basket, prody_2012) if gdp else None,
            "destinations": destinations[country],
        })
    world_total = sum((v for _, _, v in export_rows), metrics.ZERO)
    return world_docs, country_docs, world_total


def write_manifest(out):
    """List every published file with its rows and hash, so a copy can be checked against the snapshot."""
    con = duckdb.connect()
    files = []
    for path in sorted(out.rglob("*.parquet")):
        rows = con.execute("SELECT sum(num_rows) FROM parquet_file_metadata(?)", [path.as_posix()]).fetchone()[0]
        files.append({"path": path.relative_to(out).as_posix(), "rows": int(rows), "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = out / "manifest.json"
    manifest.write_text(json.dumps(files, indent=1), encoding="utf-8", newline="\n")
    return {"files": len(files), "bytes": sum(f["bytes"] for f in files), "manifestSha256": sha256(manifest)}


def prepare(path, db, gdp_path=None):
    path = Path(path)
    match = re.fullmatch(r"BACI_(HS\d\d)_V(\d+)\.zip", path.name)
    if not match:
        raise PrepareFailed(f"{path.name} is not named like BACI_HS12_V202601.zip")
    classification, release = match.groups()
    baci_sha = sha256(path)
    gdp_sha = sha256(gdp_path) if gdp_path else None
    inputs = f"{baci_sha} {gdp_sha} {metrics.CALCULATION_VERSION} {LAYOUT_VERSION}"
    snapshot_id = f"{path.stem}@{hashlib.sha256(inputs.encode()).hexdigest()[:12]}"

    existing = db.snapshots.find_one({"_id": snapshot_id})
    if existing and existing["status"] == "ready":
        return existing
    for collection in (db.products, db.world_product_years, db.country_years):
        collection.delete_many({"snapshotId": snapshot_id})

    snapshot = {
        "_id": snapshot_id,
        "status": "preparing",
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
            "sha256": baci_sha,
            "bytes": path.stat().st_size,
            "retrievedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        },
        "manifest": {
            "baciSha256": baci_sha,
            "gdpSha256": gdp_sha,
            "calculationVersion": metrics.CALCULATION_VERSION,
            "layoutVersion": LAYOUT_VERSION,
        },
        "years": list(YEARS),
    }
    db.snapshots.replace_one({"_id": snapshot_id}, snapshot, upsert=True)

    DATA.mkdir(parents=True, exist_ok=True)
    final = DATA / snapshot_id
    out = DATA / f"{snapshot_id}.partial"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    try:
        # DuckDB has to let go of its spill files before the scratch folder can be removed on Windows.
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(dir=DATA) as scratch, duckdb.connect() as con:
            country_rows = read_dictionary(
                archive, f"country_codes_V{release}.csv", ["country_code", "country_name", "country_iso2", "country_iso3"]
            )
            product_rows = read_dictionary(archive, f"product_codes_{classification}_V{release}.csv", ["code", "description"])
            products = {r["code"].zfill(6): r["description"] for r in product_rows}
            gdp, gdp_provenance = read_gdp(gdp_path, country_rows) if gdp_path else ({}, None)
            # The fixed-2012 sensitivity uses only countries with income in every year, so coverage cannot move it.
            common = {c for c, by_year in gdp.items() if set(YEARS) <= by_year.keys()}

            con.execute(f"SET temp_directory = {quoted(scratch)}")
            con.execute("CREATE TABLE countries AS SELECT unnest(?::VARCHAR[]) AS code", [[r["country_code"] for r in country_rows]])
            con.execute("CREATE TABLE products AS SELECT unnest(?::VARCHAR[]) AS code", [list(products)])

            errors, samples, files, world_totals, prody_2012 = Counter(), [], [], {}, {}
            for year in YEARS:
                name = f"BACI_{classification}_Y{year}_V{release}.csv"
                if name not in archive.namelist():
                    raise PrepareFailed(f"{name} is missing from the archive")
                csv_path = archive.extract(name, scratch)
                record = check_year(con, csv_path, name, year, errors, samples)
                os.remove(csv_path)
                write_year(con, out, year, record)
                world_docs, country_docs, world_totals[str(year)] = summarize_year(con, snapshot_id, year, gdp, common, prody_2012)
                for collection, docs in ((db.world_product_years, world_docs), (db.country_years, country_docs)):
                    if docs:
                        collection.insert_many(docs, ordered=False)
                files.append(record)
                print(f"{year}: {record['rows']:,} rows, {record['flows']:,} flows, {len(country_docs)} countries", flush=True)

            db.products.insert_many(
                [
                    {"snapshotId": snapshot_id, "productCode": k, "description": d, "chapter": k[:2], "heading": k[:4]}
                    for k, d in sorted(products.items())
                ],
                ordered=False,
            )
        storage = {"path": snapshot_id, **write_manifest(out)}
        shutil.rmtree(final, ignore_errors=True)
        os.replace(out, final)
    except Exception as exc:
        db.snapshots.update_one({"_id": snapshot_id}, {"$set": {"status": "failed", "failure": str(exc)}})
        shutil.rmtree(out, ignore_errors=True)
        raise

    iso2 = {r["country_code"]: r["country_iso2"] or None for r in country_rows}
    ready = {
        "status": "ready",
        "preparedAt": datetime.now(timezone.utc),
        "gdp": gdp_provenance,
        "countries": [
            {"countryCode": int(r["country_code"]), "countryName": r["country_name"], "isoCode": r["country_iso3"], "iso2": iso2[r["country_code"]]}
            for r in sorted(country_rows, key=lambda r: r["country_name"])
        ],
        "worldTotals": world_totals,
        "storage": storage,
        "files": files,
        "counts": {
            "rows": sum(f["rows"] for f in files),
            "flows": sum(f["flows"] for f in files),
            "roundedValues": sum(f["roundedValues"] for f in files),
            "unreadableQuantities": sum(f["unreadableQuantities"] for f in files),
            "dictionaryProducts": len(products),
            "countries": len(country_rows),
        },
        "errors": {"rejectedRows": sum(errors.values()), "byKind": dict(errors), "samples": samples},
    }
    db.snapshots.update_one({"_id": snapshot_id}, {"$set": ready})
    return db.snapshots.find_one({"_id": snapshot_id})


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    client, database = connect()
    with client:
        result = prepare(sys.argv[1], database, sys.argv[2] if len(sys.argv) == 3 else None)
    print(f"{result['_id']} {result['status']}: {result['counts']}, {result['errors']['rejectedRows']} rows rejected")
