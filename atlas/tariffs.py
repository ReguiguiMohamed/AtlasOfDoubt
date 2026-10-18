"""Each BACI country's latest WITS/TRAINS import tariff and its preferences, mapped to HS2012.

    python -m atlas.tariffs

Downloads the latest TRAINS schedule each BACI country applies from the
anonymous WITS SDMX API, and the WITS HS concordances, into data/snapshots/wits.
Files already there are kept, so an interrupted run resumes and a later run
reuses the same schedules. Then it writes data/snapshots/tariffs.csv, one row
per schedule and HS2012 code, and tariff-schedules.csv, the schedule each
country applies. EU members share the EUN schedule, which is stored once.
Run python -m atlas.coverage first, since its WITS list says which schedules exist.

For each kept schedule it then downloads the preferential rate of every partner
the WITS list names, one request per schedule and partner, into
data/snapshots/wits/pref, and writes preferences.csv. A partner is a country or
a beneficiary group, so tariff-partners.csv lists each partner's BACI members,
from the WITS country list and the TRAINS beneficiaries file. That file dates
from 2018, so a newer group has no members and is never applied.
WITS sends only the codes where a preference covers at least one national line.
The rate averages every line for that partner, preferential or not.

WITS reports an HS6 rate as the simple average of the national tariff lines
under it, with their minimum and maximum. A schedule in HS2012 keeps its rates.
In HS2007 or HS2002, each HS2012 code takes the one older code WITS maps it to.
In HS2017, several codes can meet in one HS2012 code. Their rates are never
averaged: the row keeps only the lowest and highest rate and how many codes met.
"""

import csv
import io
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

SDMX = "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter/{code}/partner/{partner}/product/all/year/{year}/datatype/reported"
CONCORDANCE = "https://wits.worldbank.org/data/public/concordance/Concordance_{name}.zip"
# WITS publishes each concordance from the newer revision to the older, so HS2007 and HS2002 come from HS2012's tables.
CONCORDANCES = {"H5": "H5_to_H4", "H3": "H4_to_H3", "H2": "H4_to_H2"}
BENEFICIARIES = "https://wits.worldbank.org/data/public/TRAINSPreferenceBenficiaries.xls"
PARTNERS = "https://wits.worldbank.org/API/V1/wits/datasource/trn/country/ALL"
# The beneficiaries file files France under its UN code, which the WITS country list leaves out.
UN_CODES = {"250": "FRA"}
COLUMNS = ["schedule", "year", "nomenclature", "productCode", "rate", "minRate", "maxRate", "sourceCodes", "nationalLines", "naLines"]


def read_concordance(path, nomenclature):
    """{HS2012 code: [source codes]} from a WITS concordance zip."""
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.upper().endswith(".CSV"))
        rows = list(csv.reader(io.TextIOWrapper(archive.open(name), "latin-1")))[1:]
    sources = defaultdict(list)
    for r in rows:
        newer, older = r[0], r[2]
        hs2012, source = (older, newer) if nomenclature == "H5" else (newer, older)
        sources[hs2012].append(source)
    return sources


def read_schedule(path, kind="MFN"):
    """(nomenclature, {HS6 code: line}) from one SDMX response, with rates as exact decimal strings."""
    lines, nomenclatures = {}, set()
    for series in ET.parse(path).getroot().iter("Series"):
        obs = series.find("Obs")
        # A line without a rate is left out, so the market shows no rate for the code rather than a zero.
        if obs is None or obs.get("TARIFFTYPE") != kind or obs.get("OBS_VALUE") in (None, "", "NaN"):
            continue
        nomenclatures.add(obs.get("NOMENCODE"))
        lines[series.get("PRODUCTCODE")] = {
            "rate": obs.get("OBS_VALUE"),
            "minRate": obs.get("MIN_RATE"),
            "maxRate": obs.get("MAX_RATE"),
            "nationalLines": int(obs.get("TOTALNOOFLINES") or 0),
            "naLines": int(obs.get("NBR_NA_LINES") or 0),
        } | ({"prefLines": int(obs.get("NBR_PREF_LINES") or 0)} if kind == "PREF" else {})
    if len(nomenclatures) > 1:
        raise ValueError(f"{Path(path).name} mixes {sorted(nomenclatures)}")
    return next(iter(nomenclatures), None), lines


def to_hs2012(nomenclature, lines, concordances):
    """{HS2012 code: row}. One source code keeps its rate, several keep only their lowest and highest."""
    if nomenclature == "H4":
        sources = {code: [code] for code in lines}
    else:
        sources = concordances[nomenclature]
    rows = {}
    for hs2012, codes in sources.items():
        found = [lines[c] for c in codes if c in lines]
        if not found:
            continue
        if len(found) == 1:
            rows[hs2012] = found[0] | {"sourceCodes": 1}
            continue
        rates = [Decimal(r) for f in found for r in (f["rate"], f["minRate"], f["maxRate"]) if r]
        rows[hs2012] = {
            "rate": None,
            "minRate": str(min(rates)),
            "maxRate": str(max(rates)),
            "sourceCodes": len(found),
            **{k: sum(f[k] for f in found) for k in ("nationalLines", "naLines", "prefLines") if k in found[0]},
        }
    return rows


def read_partners(countries_path, beneficiaries_path, baci):
    """{WITS partner code: (name, is a group, [BACI country codes])}, baci being {ISO3: BACI code}."""
    import xlrd

    from atlas.coverage import EU, WITS, WITS_ALIASES

    def members(iso3):
        isos = EU if iso3 == "EUN" else WITS_ALIASES.get(iso3, [iso3])
        return [baci[i] for i in isos if i in baci]

    partners, iso3s, codes = {}, {}, set(baci.values())
    for e in ET.parse(countries_path).getroot().iterfind(".//w:country", WITS):
        code, iso3 = e.get("countrycode"), e.findtext("w:iso3Code", namespaces=WITS)
        iso3s[code] = iso3
        partners[code] = (e.findtext("w:name", namespaces=WITS), e.get("isgroup") == "Yes", members(iso3))
    iso3s |= UN_CODES
    sheet = xlrd.open_workbook(beneficiaries_path).sheet_by_index(0)
    groups = defaultdict(set)
    names = {}
    for group, name, member, _ in (sheet.row_values(i) for i in range(1, sheet.nrows)):
        names[group] = name
        # EU members are missing from the WITS country list, and their UN codes match BACI's.
        groups[group].update(members(iso3s[member]) if member in iso3s else [int(member)] if member.isdigit() and int(member) in codes else [])
    for group, found in groups.items():
        partners[group] = (names[group], True, sorted(found))
    return partners


def fetch(url, path):
    """Download url into path unless it is there. False when WITS has no such slice."""
    if path.exists():
        return True
    try:
        # WITS answers 403 to urllib's default User-Agent.
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AtlasOfDoubt"}), timeout=300) as r:
            body = r.read()
    except urllib.error.HTTPError as exc:
        print(f"{url}: HTTP {exc.code}", flush=True)
        return False
    # Written beside the target and renamed, so an interrupted run never leaves half a file.
    part = path.with_name(path.name + ".part")
    part.write_bytes(body)
    part.replace(path)
    # One request at a time with a pause, to stay inside WITS's anonymous limits.
    time.sleep(1)
    return True


def main():
    from atlas.coverage import WITS
    from atlas.prepare import DATA

    availability, coverage = DATA / "wits-trains-availability.xml", DATA / "coverage.csv"
    if not coverage.exists():
        sys.exit(f"{coverage} is missing, run python -m atlas.coverage first")
    codes = {e.get("iso3Code"): e.get("countrycode") for e in ET.parse(availability).getroot().iterfind(".//w:reporter", WITS)}
    with open(coverage, encoding="utf-8") as f:
        latest = {int(r["country_code"]): (r["tariff_source"], int(r["tariff_latest"])) for r in csv.DictReader(f) if r["tariff_latest"]}
    folder = DATA / "wits"
    folder.mkdir(exist_ok=True)

    concordances = {}
    for nomenclature, name in CONCORDANCES.items():
        path = folder / f"Concordance_{name}.zip"
        fetch(CONCORDANCE.format(name=name), path)
        concordances[nomenclature] = read_concordance(path, nomenclature)

    schedules = sorted(set(latest.values()))
    rows, kept = [], set()
    for i, (source, year) in enumerate(schedules, 1):
        path = folder / f"{source}-{year}.xml"
        print(f"{i}/{len(schedules)} {source} {year}", flush=True)
        if not fetch(SDMX.format(code=codes[source], partner="000", year=year), path):
            continue
        try:
            nomenclature, lines = read_schedule(path)
        except ET.ParseError:
            print(f"{path.name} is not XML, left out", flush=True)
            continue
        if nomenclature != "H4" and nomenclature not in concordances:
            print(f"{source} {year}: {nomenclature} has no concordance to HS2012, left out", flush=True)
            continue
        mapped = to_hs2012(nomenclature, lines, concordances)
        rows += [{"schedule": source, "year": year, "nomenclature": nomenclature, "productCode": code, **r} for code, r in sorted(mapped.items())]
        kept.add((source, year))

    with open(DATA / "tariffs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(DATA / "tariff-schedules.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["countryCode", "schedule", "year"])
        writer.writerows(sorted((code, source, year) for code, (source, year) in latest.items() if (source, year) in kept))
    print(f"{len(rows):,} rows from {len(kept)} schedules for {sum(s in kept for s in latest.values())} countries")

    lists = {
        (e.get("iso3Code"), int(e.findtext("w:year", namespaces=WITS))): (e.findtext("w:partnerlist", namespaces=WITS) or "").split(";")
        for e in ET.parse(availability).getroot().iterfind(".//w:reporter", WITS)
    }
    pairs = [(source, year, p) for source, year in sorted(kept) for p in lists.get((source, year), []) if p and p != "000"]
    (folder / "pref").mkdir(exist_ok=True)
    rows = []
    for i, (source, year, partner) in enumerate(pairs, 1):
        path = folder / "pref" / f"{source}-{year}-{partner}.xml"
        print(f"{i}/{len(pairs)} {source} {year} partner {partner}", flush=True)
        if not fetch(SDMX.format(code=codes[source], partner=partner, year=year), path):
            continue
        try:
            nomenclature, lines = read_schedule(path, "PREF")
        except ET.ParseError:
            print(f"{path.name} is not XML, left out", flush=True)
            continue
        if nomenclature is None or nomenclature != "H4" and nomenclature not in concordances:
            continue
        mapped = to_hs2012(nomenclature, lines, concordances)
        rows += [
            {"schedule": source, "year": year, "partner": partner, "nomenclature": nomenclature, "productCode": code, **r}
            for code, r in sorted(mapped.items())
        ]
    with open(DATA / "preferences.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, ["partner", *COLUMNS, "prefLines"])
        writer.writeheader()
        writer.writerows(rows)

    fetch(PARTNERS, folder / "countries.xml")
    fetch(BENEFICIARIES, folder / "TRAINSPreferenceBenficiaries.xls")
    with open(coverage, encoding="utf-8") as f:
        countries = list(csv.DictReader(f))
    baci = {r["iso3"]: int(r["country_code"]) for r in countries}
    partners = read_partners(folder / "countries.xml", folder / "TRAINSPreferenceBenficiaries.xls", baci)
    # Some partner lists name a country by its BACI code, which the WITS country list lacks.
    partners = {r["country_code"]: (r["name"], False, [int(r["country_code"])]) for r in countries} | partners
    used = {p: partners.get(p, (p, True, [])) for p in sorted({p for _, _, p in pairs})}
    with open(DATA / "tariff-partners.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["partner", "name", "group", "members"])
        writer.writerows([p, name, int(group), ";".join(map(str, members))] for p, (name, group, members) in used.items())
    unresolved = [p for p, (_, _, members) in used.items() if not members]
    print(f"{len(rows):,} preference rows from {len(pairs)} partners, {len(unresolved)} partners without BACI members: {' '.join(unresolved)}")


if __name__ == "__main__":
    main()
