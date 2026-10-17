import struct

from atlas.coverage import matrix, read_dta, read_wits

STATA_MISSING = 2.0**1023


def write_dta(path, columns, rows):
    """A Stata format 113 file: string columns are sized by their type byte, 251 is a byte, 255 a double."""
    nvar = len(columns)
    out = struct.pack("<BBBBHi", 113, 2, 1, 0, nvar, len(rows)) + bytes(81 + 18)
    out += bytes(t for _, t in columns) + b"".join(n.encode().ljust(33, b"\0") for n, _ in columns)
    out += bytes(2 * (nvar + 1) + 12 * nvar + 33 * nvar + 81 * nvar) + struct.pack("<Bi", 0, 0)
    for row in rows:
        for (_, t), v in zip(columns, row):
            out += v.encode().ljust(t, b"\0") if t <= 244 else struct.pack("<b" if t == 251 else "<d", v)
    path.write_bytes(out)


def reporter(iso3, year, hs="H5", agreements=0):
    return (
        f'<wits:reporter iso3Code="{iso3}"><wits:year>{year}</wits:year>'
        f'<wits:reporternernomenclature reporternernomenclaturecode="{hs}"/>'
        f"<wits:numberofpreferentialagreement>{agreements}</wits:numberofpreferentialagreement></wits:reporter>"
    )


def test_coverage_maps_source_codes_and_eu_schedules_to_baci(tmp_path):
    xml = tmp_path / "wits.xml"
    xml.write_text(
        '<wits:datasource xmlns:wits="http://wits.worldbank.org"><wits:dataavailability>'
        + reporter("EUN", 2019, agreements=40) + reporter("EUN", 2021, agreements=41)
        + reporter("GBR", 2021, agreements=9) + reporter("TWN", 2020, "H4") + reporter("SER", 2021)
        + reporter("USA", 2008, "H3") + reporter("HRV", 2019, "H4")
        + "</wits:dataavailability></wits:datasource>",
        encoding="utf-8",
    )
    geo, dist = tmp_path / "geo.dta", tmp_path / "dist.dta"
    write_dta(geo, [("iso3", 3), ("landlocked", 255)], [("FRA", 0.0), ("YUG", 1.0), ("TWN", 0.0)])
    write_dta(dist, [("iso_o", 3), ("iso_d", 3), ("dist", 255)], [("FRA", "YUG", 1400.5), ("FRA", "TWN", STATA_MISSING)])
    countries = [
        {"country_code": c, "country_name": n, "country_iso3": i}
        for c, n, i in [
            ("251", "France", "FRA"), ("826", "United Kingdom", "GBR"), ("688", "Serbia", "SRB"),
            ("499", "Montenegro", "MNE"), ("490", "Other Asia, nes", "S19"), ("842", "USA", "USA"),
            ("191", "Croatia", "HRV"), ("891", "Serbia and Montenegro (...2005)", "SCG"),
        ]
    ]

    assert read_dta(dist)[1] == {"iso_o": "FRA", "iso_d": "TWN", "dist": None}
    rows = {r["iso3"]: r for r in matrix(countries, read_wits(xml), read_dta(geo), read_dta(dist))}

    assert "SCG" not in rows
    assert (rows["FRA"]["tariff_latest"], rows["FRA"]["tariff_source"], rows["FRA"]["preferential_agreements"]) == (2021, "EUN", 41)
    assert rows["HRV"]["tariff_years"] == "2019;2021" and rows["HRV"]["tariff_source"] == "EUN"
    assert read_wits(xml)["HRV"][2019] == ("HRV", "H4", 0)
    assert (rows["GBR"]["tariff_years"], rows["GBR"]["tariff_source"]) == ("2019;2021", "GBR")
    assert (rows["S19"]["tariff_latest"], rows["S19"]["tariff_hs"]) == (2020, "H4")
    assert rows["SRB"]["tariff_source"] == "SER" and rows["MNE"]["tariff_latest"] is None
    assert rows["USA"]["tariff_latest"] is None
    assert [rows[c]["geo_source"] for c in ("SRB", "MNE", "S19", "USA")] == ["YUG", "YUG", "TWN", None]
    assert (rows["MNE"]["landlocked"], rows["FRA"]["geo_partners"], rows["S19"]["geo_partners"]) == (1, 2, 0)
