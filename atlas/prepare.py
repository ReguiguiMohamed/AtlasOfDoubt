"""Prepare one BACI release with WDI GDP as a snapshot any country can be read from.

    python -m atlas.prepare data/raw/BACI_HS12_V202601.zip [wdi-gdp.json]

The GDP file defaults to data/snapshots/wdi-gdp.json and the CEPII GeoDist
files to geo_cepii.dta and dist_cepii.dta beside it. Each is downloaded when
missing, then kept, so later runs reuse the same files and the same snapshot
id. Delete one to fetch newer figures. The section, chapter and heading names
come the same way from DataHub's HS 2022 files into hs/. Tariffs join when python -m
atlas.tariffs has written tariffs.csv and tariff-schedules.csv there.

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
import itertools
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

from atlas import graph, metrics, twins
from atlas.db import connect

YEARS = range(2012, 2025)
HEADER = "t,i,j,k,v,q"
SAMPLE_LIMIT = 100
# Deep enough for the product page to list alternative suppliers, while views copy only the first few.
WORLD_TOP = 25
LAYOUT_VERSION = "3"
DATA = Path(os.environ.get("ATLAS_DATA", "data/snapshots"))
GDP_INDICATOR = "NY.GDP.PCAP.PP.KD"
GDP_URL = f"https://api.worldbank.org/v2/country/all/indicator/{GDP_INDICATOR}?format=json&date=2012:2024&per_page=20000"
GEO_URL = "https://www.cepii.fr/distance/geo_cepii.dta"
DIST_URL = "https://www.cepii.fr/distance/dist_cepii.dta"
HS_URL = "https://raw.githubusercontent.com/datasets/harmonized-system/main/data/"
TARIFF_ATTRIBUTION = "UNCTAD TRAINS, retrieved through the World Bank's WITS"
TARIFF_DISCLAIMER = "TRAINS data are provided as is, and the user assumes all risk in their use."
GEO_CITATION = "Mayer, T. and Zignago, S. (2011). Notes on CEPII's distances measures: the GeoDist Database. CEPII Working Paper, N°2011-25."
# GeoDist predates the split of Serbia and Montenegro, so both take YUG's geography. BACI files Taiwan as S19.
GEO_ALIASES = {"PAL": ["PSE"], "ROM": ["ROU"], "TMP": ["TLS"], "TWN": ["S19"], "YUG": ["SRB", "MNE"], "ZAR": ["COD"]}
# Stata type byte: struct format, size, and the largest value that is not a missing code.
STATA_NUMBERS = {251: ("b", 1, 100), 252: ("h", 2, 32740), 253: ("i", 4, 2147483620), 254: ("f", 4, 1.701e38), 255: ("d", 8, 8.988e307)}
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


def unmangle(text):
    """CEPII's country list stores some names encoded twice, Côte as CÃ´te. Clean text fails the round trip and stays."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def read_dictionary(archive, name, columns):
    if name not in archive.namelist():
        raise PrepareFailed(f"{name} is missing from the archive")
    with archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, "utf-8-sig", newline=""))
        if not set(columns) <= set(reader.fieldnames or []):
            raise PrepareFailed(f"{name} lacks columns {columns}")
        return [{c: unmangle(row[c].strip()) for c in columns} for row in reader]


def download(url, path):
    """Fetch url into path unless the file is already there."""
    if path.exists():
        return
    print(f"Downloading {url} to {path}", flush=True)
    # WITS answers 403 to urllib's default User-Agent.
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AtlasOfDoubt"}), timeout=120) as response:
        body = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def iso3_codes(country_rows):
    codes = defaultdict(list)
    for r in country_rows:
        codes[r["country_iso3"]].append(int(r["country_code"]))
    return codes


def read_dta(path):
    """Rows of a Stata format 113 file, the format GeoDist ships, with missing numbers as None."""
    path = Path(path)
    data = path.read_bytes()
    if data[0] != 113:
        raise PrepareFailed(f"{path.name} is Stata format {data[0]}, only 113 is read")
    order = "<" if data[1] == 2 else ">"
    nvar, nobs = struct.unpack_from(order + "Hi", data, 4)
    types = data[109:109 + nvar]
    pos = 109 + nvar
    names = [data[pos + 33 * i:pos + 33 * (i + 1)].split(b"\0")[0].decode() for i in range(nvar)]
    # Skip names, sort order, formats, value labels and variable labels, then the expansion fields.
    pos += 33 * nvar + 2 * (nvar + 1) + 12 * nvar + 33 * nvar + 81 * nvar
    while True:
        kind, length = struct.unpack_from(order + "Bi", data, pos)
        pos += 5 + length
        if (kind, length) == (0, 0):
            break
    rows = []
    for _ in range(nobs):
        row = {}
        for name, t in zip(names, types):
            if t <= 244:
                row[name] = data[pos:pos + t].split(b"\0")[0].decode("latin-1")
                pos += t
            else:
                fmt, size, top = STATA_NUMBERS[t]
                value = struct.unpack_from(order + fmt, data, pos)[0]
                row[name] = None if value > top else value
                pos += size
        rows.append(row)
    return rows


def read_geography(geo_path, dist_path, country_rows):
    """GeoDist as {(BACI code, BACI code): pair fields} and {BACI code: landlocked}, with its provenance.

    Countries match by ISO3, through GEO_ALIASES where GeoDist keeps an older code.
    The distance is between the two countries' most populated cities, the one
    measure GeoDist gives for every pair. Two BACI countries sharing one GeoDist
    entity, such as Serbia and Montenegro under YUG, get no pair, because GeoDist
    only has the distance inside that entity.
    """
    codes = iso3_codes(country_rows)

    def baci(iso3):
        return [c for alias in GEO_ALIASES.get(iso3, [iso3]) for c in codes.get(alias, [])]

    landlocked = {}
    for r in read_dta(geo_path):
        for code in baci(r["iso3"]):
            landlocked.setdefault(code, bool(r["landlocked"]))
    pairs = {}
    for r in read_dta(dist_path):
        if r["iso_o"] == r["iso_d"] or r["dist"] is None:
            continue
        fields = {"distanceKm": round(r["dist"]), "contiguous": bool(r["contig"]), "commonLanguage": bool(r["comlang_off"])}
        for a in baci(r["iso_o"]):
            for b in baci(r["iso_d"]):
                pairs[a, b] = fields
    provenance = {
        "name": "CEPII GeoDist",
        "url": "https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=6",
        "citation": GEO_CITATION,
        "license": "Etalab Open License 2.0",
        "distance": "great-circle distance between the most populated cities, km",
        "files": [
            {"filename": p.name, "sha256": sha256(p), "bytes": p.stat().st_size,
             "retrievedAt": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)}
            for p in map(Path, (geo_path, dist_path))
        ],
        "countries": len(landlocked),
        "unmatched": sorted(int(r["country_code"]) for r in country_rows if int(r["country_code"]) not in landlocked),
    }
    return pairs, landlocked, provenance


def read_tariffs(country_rows, rates_path, schedules_path, preferences_path=None, partners_path=None):
    """The schedule each BACI country applies, its provenance, and its rates and preferences as docs to stream into MongoDB.

    The rates file holds about 900,000 rows, so docs come from a generator. Rates
    stay Decimal, and a code several source codes met in has no rate, only its range.
    """
    known = {int(r["country_code"]) for r in country_rows}
    with open(schedules_path, encoding="utf-8") as f:
        applied = {
            int(r["countryCode"]): {"schedule": r["schedule"], "year": int(r["year"])}
            for r in csv.DictReader(f) if int(r["countryCode"]) in known
        }

    def docs(snapshot_id, path=rates_path):
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                yield {
                    "snapshotId": snapshot_id, "productCode": r["productCode"], "schedule": r["schedule"],
                    "year": int(r["year"]), "nomenclature": r["nomenclature"],
                    **({"partner": r["partner"], "prefLines": int(r["prefLines"])} if "partner" in r else {}),
                    **{k: Decimal(r[k]) if r[k] else None for k in ("rate", "minRate", "maxRate")},
                    **{k: int(r[k]) for k in ("sourceCodes", "nationalLines", "naLines")},
                }

    paths = [p for p in (rates_path, schedules_path, preferences_path, partners_path) if p]
    partners = {}
    if partners_path:
        with open(partners_path, encoding="utf-8") as f:
            partners = {
                r["partner"]: {"name": r["name"], "group": r["group"] == "1", "members": [int(m) for m in r["members"].split(";") if m]}
                for r in csv.DictReader(f)
            }

    provenance = {
        "name": "WITS/TRAINS MFN and preferential applied tariffs" if partners else "WITS/TRAINS MFN applied tariffs",
        "url": "https://wits.worldbank.org/",
        "attribution": TARIFF_ATTRIBUTION,
        "disclaimer": TARIFF_DISCLAIMER,
        "license": "WITS/TRAINS custom licence, see the World Bank data catalogue",
        "measure": "simple average of national tariff lines per HS6 code, ad valorem percent",
        "files": [
            {"filename": p.name, "sha256": sha256(p), "bytes": p.stat().st_size,
             "retrievedAt": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)}
            for p in map(Path, paths)
        ],
        "schedules": len({a["schedule"] for a in applied.values()}),
        "countries": len(applied),
    } | ({"partners": partners, "unresolvedPartners": sorted(p for p, v in partners.items() if not v["members"])} if partners else {})
    preference_docs = (lambda snapshot_id: docs(snapshot_id, preferences_path)) if preferences_path else None
    return docs, preference_docs, applied, provenance


def read_categories(hs_path, sections_path, products):
    """Each product's section, chapter and heading with their names, and their provenance.

    The names are those of the HS 2022 edition. A chapter or heading it no longer
    has keeps the start of its first BACI description, the text before the colon.
    """
    with open(sections_path, encoding="utf-8-sig") as f:
        sections = {r["section"]: r["name"].strip() for r in csv.DictReader(f)}
    names, section_of = {}, {}
    with open(hs_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["level"] in ("2", "4"):
                names[r["hscode"]] = r["description"].strip()
            if r["level"] == "2":
                section_of[r["hscode"]] = r["section"]
    fallback = {}
    for code, description in sorted(products.items()):
        for group in (code[:2], code[:4]):
            fallback.setdefault(group, description.split(":")[0].strip())
    fields = {}
    for code in products:
        # Chapter 99 sits under the source's TOTAL row, which names no section.
        name = sections.get(section_of.get(code[:2]))
        fields[code] = {
            "section": name and section_of[code[:2]],
            # Section I is the one name the source writes in lower case.
            "sectionName": name and name[0].upper() + name[1:],
            "chapterName": names.get(code[:2], fallback[code[:2]]),
            "headingName": names.get(code[:4], fallback[code[:4]]),
        }
    groups = {c for code in products for c in (code[:2], code[:4])}
    provenance = {
        "name": "Harmonized System names, HS 2022, from UN Comtrade through DataHub",
        "url": "https://github.com/datasets/harmonized-system",
        "license": "ODC Public Domain Dedication and License 1.0",
        "files": [
            {"filename": p.name, "sha256": sha256(p), "bytes": p.stat().st_size,
             "retrievedAt": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)}
            for p in map(Path, (hs_path, sections_path))
        ],
        "named": len(groups & names.keys()),
        "fallback": sorted(groups - names.keys()),
    }
    return fields, provenance


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
    codes = iso3_codes(country_rows)
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


def write_graph(con, out, scratch, countries, year, total):
    """Load the year's flows into the Ladybug graph, one edge per exporter, importer and heading, and prove no dollar was lost."""
    edges = Path(scratch) / "edges.parquet"
    n = con.execute(
        "COPY (SELECT CAST(exporter AS BIGINT) AS exporter, CAST(importer AS BIGINT) AS importer, left(product, 4) AS heading,"
        f" CAST(sum(v) * 1000 AS BIGINT) AS valueUsd FROM flows GROUP BY ALL) TO {quoted(edges)} (FORMAT parquet)"
    ).fetchone()[0]
    path = out / "graph.lbug"
    written = graph.build(path, countries, edges if n else None)
    if written != (n, total):
        raise PrepareFailed(f"the graph holds {written}, expected {n} edges worth {total} USD")
    return {"path": path.name, "year": year, "edges": n, "valueUsd": written[1], "bytes": path.stat().st_size, "sha256": sha256(path)}


def write_twins(con, out, year):
    """Store every country's import and export basket of the year as a Milvus vector, and prove each trading country got one."""
    side = {"imports": "importer", "exports": "exporter"}
    baskets = {f: con.execute(f"SELECT {c}, product, CAST(sum(v) AS DOUBLE) FROM flows GROUP BY ALL").fetchall() for f, c in side.items()}
    path = out / "twins.db"
    written = twins.build(path, baskets)
    expected = {f: con.execute(f"SELECT count(DISTINCT {c}) FROM flows WHERE v > 0").fetchone()[0] for f, c in side.items()}
    if written != expected:
        raise PrepareFailed(f"the twins hold {written} vectors, expected {expected}")
    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return {"path": path.name, "year": year, "metric": "Bhattacharyya coefficient", "vectors": written, "bytes": size}


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


def prepare(path, db, gdp_path=None, geo_paths=None, tariff_paths=None, hs_paths=None):
    path = Path(path)
    match = re.fullmatch(r"BACI_(HS\d\d)_V(\d+)\.zip", path.name)
    if not match:
        raise PrepareFailed(f"{path.name} is not named like BACI_HS12_V202601.zip")
    classification, release = match.groups()
    baci_sha = sha256(path)
    gdp_sha = sha256(gdp_path) if gdp_path else None
    geo_shas = [sha256(p) for p in geo_paths] if geo_paths else None
    tariff_shas = [sha256(p) for p in tariff_paths] if tariff_paths else None
    hs_shas = [sha256(p) for p in hs_paths] if hs_paths else None
    inputs = f"{baci_sha} {gdp_sha} {metrics.CALCULATION_VERSION} {LAYOUT_VERSION}"
    # Appended only when present, so a snapshot prepared without GeoDist, tariffs or HS names keeps its id.
    for shas in (geo_shas, tariff_shas, hs_shas):
        if shas:
            inputs += " " + " ".join(shas)
    snapshot_id = f"{path.stem}@{hashlib.sha256(inputs.encode()).hexdigest()[:12]}"

    existing = db.snapshots.find_one({"_id": snapshot_id})
    if existing and existing["status"] == "ready":
        return existing
    for collection in (db.products, db.world_product_years, db.country_years, db.geo_pairs, db.tariffs, db.preferences):
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
            "geodistSha256": geo_shas,
            "tariffSha256": tariff_shas,
            "hsSha256": hs_shas,
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
            pairs, landlocked, geo_provenance = read_geography(*geo_paths, country_rows) if geo_paths else ({}, {}, None)
            tariff_docs, preference_docs, applied, tariff_provenance = (
                read_tariffs(country_rows, *tariff_paths) if tariff_paths else (None, None, {}, None)
            )
            categories, category_provenance = read_categories(*hs_paths, products) if hs_paths else ({}, None)
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
                if year == YEARS[-1]:
                    trade_graph = write_graph(
                        con, out, scratch, [int(r["country_code"]) for r in country_rows], year, world_totals[str(year)]
                    )
                    trade_twins = write_twins(con, out, year)
                for collection, docs in ((db.world_product_years, world_docs), (db.country_years, country_docs)):
                    if docs:
                        collection.insert_many(docs, ordered=False)
                files.append(record)
                print(f"{year}: {record['rows']:,} rows, {record['flows']:,} flows, {len(country_docs)} countries", flush=True)

            db.products.insert_many(
                [
                    {"snapshotId": snapshot_id, "productCode": k, "description": d, "chapter": k[:2], "heading": k[:4],
                     **categories.get(k, {})}
                    for k, d in sorted(products.items())
                ],
                ordered=False,
            )
            if pairs:
                db.geo_pairs.insert_many(
                    [{"snapshotId": snapshot_id, "countryCode": a, "partnerCode": b, **f} for (a, b), f in sorted(pairs.items())],
                    ordered=False,
                )
            for collection, make in ((db.tariffs, tariff_docs), (db.preferences, preference_docs)):
                rows = make(snapshot_id) if make else iter(())
                while batch := list(itertools.islice(rows, 10_000)):
                    collection.insert_many(batch, ordered=False)
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
        "geography": geo_provenance,
        "tariffs": tariff_provenance,
        "categories": category_provenance,
        "graph": trade_graph,
        "twins": trade_twins,
        "countries": [
            {"countryCode": int(r["country_code"]), "countryName": r["country_name"], "isoCode": r["country_iso3"],
             "iso2": iso2[r["country_code"]]}
            | ({"landlocked": landlocked[int(r["country_code"])]} if int(r["country_code"]) in landlocked else {})
            | ({"tariffSchedule": applied[int(r["country_code"])]} if int(r["country_code"]) in applied else {})
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
    gdp_path = Path(sys.argv[2]) if len(sys.argv) == 3 else DATA / "wdi-gdp.json"
    download(GDP_URL, gdp_path)
    geo_paths = (DATA / "geo_cepii.dta", DATA / "dist_cepii.dta")
    for url, geo_path in zip((GEO_URL, DIST_URL), geo_paths):
        download(url, geo_path)
    # Tariffs come from python -m atlas.tariffs, which needs the coverage list first, so they join only once present.
    tariff_paths = (DATA / "tariffs.csv", DATA / "tariff-schedules.csv")
    if not all(p.exists() for p in tariff_paths):
        print("No tariffs.csv yet, preparing without tariffs", flush=True)
        tariff_paths = None
    # Preferences from the same run join only when both files are there, so the snapshot id stays put without them.
    elif all((DATA / n).exists() for n in ("preferences.csv", "tariff-partners.csv")):
        tariff_paths += (DATA / "preferences.csv", DATA / "tariff-partners.csv")
    hs_paths = (DATA / "hs" / "harmonized-system.csv", DATA / "hs" / "sections.csv")
    for hs_path in hs_paths:
        download(HS_URL + hs_path.name, hs_path)
    client, database = connect()
    with client:
        result = prepare(sys.argv[1], database, gdp_path, geo_paths, tariff_paths, hs_paths)
    print(f"{result['_id']} {result['status']}: {result['counts']}, {result['errors']['rejectedRows']} rows rejected")
