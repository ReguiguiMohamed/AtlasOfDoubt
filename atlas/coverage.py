"""Which BACI countries have a WITS/TRAINS tariff schedule and CEPII GeoDist geography.

    python -m atlas.coverage data/raw/BACI_HS12_V202601.zip

The WITS availability list and the two GeoDist files are downloaded into
data/snapshots when missing, then kept. Both are matched to the archive's
country list by ISO3 and written to data/snapshots/coverage.csv, one row per
BACI country code, with the tariff years inside BACI's years, the latest
schedule's HS revision and whether GeoDist has the country and its pairs.
"""

import csv
import re
import struct
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict

from atlas.prepare import DATA, YEARS, PrepareFailed, read_dictionary

SOURCES = {
    "wits-trains-availability.xml": "https://wits.worldbank.org/API/V1/wits/datasource/trn/dataavailability/country/all/year/all",
    "geo_cepii.dta": "https://www.cepii.fr/distance/geo_cepii.dta",
    "dist_cepii.dta": "https://www.cepii.fr/distance/dist_cepii.dta",
}
WITS = {"w": "http://wits.worldbank.org"}

# Codes a source uses where BACI has another. BACI files Taiwan as S19, "Other Asia, nes".
WITS_ALIASES = {"MNT": ["MNE"], "ROM": ["ROU"], "SER": ["SRB"], "SUD": ["SDN"], "TMP": ["TLS"], "TWN": ["S19"], "ZAR": ["COD"]}
# GeoDist predates the split of Serbia and Montenegro, so both take YUG's geography.
GEO_ALIASES = {"PAL": ["PSE"], "ROM": ["ROU"], "TMP": ["TLS"], "TWN": ["S19"], "YUG": ["SRB", "MNE"], "ZAR": ["COD"]}

# The EU files one schedule, EUN, for its members. A member's own schedule for the same year wins.
EU = "AUT BEL BGR CYP CZE DEU DNK ESP EST FIN FRA GRC HRV HUN IRL ITA LTU LUX LVA MLT NLD POL PRT ROU SVK SVN SWE".split()
LEFT_EU = {"GBR": 2020}

# Stata type byte: struct format, size, and the largest value that is not a missing code.
STATA_NUMBERS = {251: ("b", 1, 100), 252: ("h", 2, 32740), 253: ("i", 4, 2147483620), 254: ("f", 4, 1.701e38), 255: ("d", 8, 8.988e307)}


def read_dta(path):
    """Rows of a Stata format 113 file, the format GeoDist ships, with missing numbers as None."""
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


def read_wits(path):
    """{BACI ISO3: {year: (source ISO3, HS revision, preferential agreements)}} for BACI's years."""
    schedules = defaultdict(dict)
    for e in ET.parse(path).getroot().iterfind(".//w:reporter", WITS):
        year = int(e.findtext("w:year", namespaces=WITS))
        if year not in YEARS:
            continue
        source = e.get("iso3Code")
        hs = e.find("w:reporternernomenclature", WITS).get("reporternernomenclaturecode")
        agreements = int(e.findtext("w:numberofpreferentialagreement", namespaces=WITS))
        for iso3 in WITS_ALIASES.get(source, [source]):
            schedules[iso3][year] = (source, hs, agreements)
    for iso3 in EU + list(LEFT_EU):
        for year, schedule in schedules["EUN"].items():
            if year <= LEFT_EU.get(iso3, YEARS.stop):
                schedules[iso3].setdefault(year, schedule)
    return schedules


def matrix(country_rows, schedules, geo_rows, dist_rows):
    geo = {}
    for r in geo_rows:
        for iso3 in GEO_ALIASES.get(r["iso3"], [r["iso3"]]):
            geo.setdefault(iso3, (r["iso3"], r["landlocked"]))
    pairs = defaultdict(set)
    for r in dist_rows:
        if r["dist"] is not None:
            for origin in GEO_ALIASES.get(r["iso_o"], [r["iso_o"]]):
                pairs[origin].update(GEO_ALIASES.get(r["iso_d"], [r["iso_d"]]))
    baci = {r["country_iso3"] for r in country_rows}
    rows = []
    for r in country_rows:
        # Codes BACI closed before its first year have no flows and would borrow a successor's ISO3.
        ended = re.search(r"\(\.\.\.(\d{4})\)", r["country_name"])
        if ended and int(ended[1]) < YEARS.start:
            continue
        iso3 = r["country_iso3"]
        years = schedules.get(iso3, {})
        latest = max(years, default=None)
        source, hs, agreements = years[latest] if latest else (None, None, None)
        geo_source, landlocked = geo.get(iso3, (None, None))
        rows.append({
            "country_code": int(r["country_code"]),
            "iso3": iso3,
            "name": r["country_name"],
            "tariff_years": ";".join(map(str, sorted(years))),
            "tariff_latest": latest,
            "tariff_source": source,
            "tariff_hs": hs,
            "preferential_agreements": agreements,
            "geo_source": geo_source,
            "landlocked": None if landlocked is None else int(landlocked),
            "geo_partners": len(pairs[iso3] & baci - {iso3}),
        })
    return rows


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    DATA.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        if not (DATA / name).exists():
            print(f"Downloading {url}", flush=True)
            # WITS answers 403 to urllib's default User-Agent.
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AtlasOfDoubt"}), timeout=120) as response:
                (DATA / name).write_bytes(response.read())
    release = re.search(r"_V(\d+)\.zip$", sys.argv[1])[1]
    with zipfile.ZipFile(sys.argv[1]) as archive:
        country_rows = read_dictionary(archive, f"country_codes_V{release}.csv", ["country_code", "country_name", "country_iso3"])
    schedules = read_wits(DATA / "wits-trains-availability.xml")
    geo_rows = read_dta(DATA / "geo_cepii.dta")
    rows = matrix(country_rows, schedules, geo_rows, read_dta(DATA / "dist_cepii.dta"))
    with open(DATA / "coverage.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    baci = {r["iso3"] for r in rows}
    with_tariff = [r for r in rows if r["tariff_latest"]]
    print(f"{len(rows)} BACI countries, written to {DATA / 'coverage.csv'}")
    print(f"Tariff schedule in {YEARS.start}-{YEARS.stop - 1}: {len(with_tariff)}, none: {len(rows) - len(with_tariff)}")
    print("Latest year:", sorted(Counter(r["tariff_latest"] for r in with_tariff).items()))
    print("Latest HS revision:", sorted(Counter(r["tariff_hs"] for r in with_tariff).items()))
    for year in (YEARS.stop - 1, 2021, 2017):
        print(f"With a {year} schedule: {sum(str(year) in r['tariff_years'].split(';') for r in rows)}")
    print(f"GeoDist: {sum(bool(r['geo_source']) for r in rows)} matched, missing:", ", ".join(r["name"] for r in rows if not r["geo_source"]))
    print("WITS reporters BACI lacks:", ", ".join(sorted(set(schedules) - baci - {"EUN"})))
    print("GeoDist countries BACI lacks:", ", ".join(sorted({c for r in geo_rows for c in GEO_ALIASES.get(r["iso3"], [r["iso3"]])} - baci)))
