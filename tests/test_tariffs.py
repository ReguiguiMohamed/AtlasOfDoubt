import csv
import io
import zipfile

from atlas.tariffs import read_concordance, read_schedule, to_hs2012


def line(rate, low, high, lines=1):
    return {"rate": rate, "minRate": low, "maxRate": high, "nationalLines": lines, "naLines": 0}


def write_concordance(path, pairs):
    """A WITS concordance zip, (newer code, older code) per row."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Newer", "Newer Description", "Older", "Older Description"])
    writer.writerows([newer, "x", older, "y"] for newer, older in pairs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("JobID-1_Concordance.CSV", out.getvalue().encode("latin-1"))


def test_schedule_keeps_mfn_rates_as_exact_strings_and_leaves_out_a_missing_rate(tmp_path):
    path = tmp_path / "XYZ-2021.xml"
    path.write_text(
        "<message:StructureSpecificData xmlns:message='m'><message:DataSet>"
        "<Series PRODUCTCODE='010121'><Obs OBS_VALUE='2.5' TARIFFTYPE='MFN' MIN_RATE='0' MAX_RATE='5' TOTALNOOFLINES='2' NBR_NA_LINES='0' NOMENCODE='H5'/></Series>"
        "<Series PRODUCTCODE='010129'><Obs OBS_VALUE='9' TARIFFTYPE='AHS' NOMENCODE='H5'/></Series>"
        "<Series PRODUCTCODE='010130'><Obs OBS_VALUE='0' TARIFFTYPE='MFN' MIN_RATE='0' MAX_RATE='0' NOMENCODE='H5'/></Series>"
        "<Series PRODUCTCODE='010190'><Obs TARIFFTYPE='MFN' NOMENCODE='H5'/></Series>"
        "</message:DataSet></message:StructureSpecificData>",
        encoding="utf-8",
    )
    assert read_schedule(path) == ("H5", {"010121": line("2.5", "0", "5", 2), "010130": line("0", "0", "0", 0)})


def test_several_hs2017_codes_keep_a_range_and_never_an_average(tmp_path):
    zipped = tmp_path / "h5.zip"
    write_concordance(zipped, [("100111", "100110"), ("100119", "100110"), ("100190", "100190")])
    concordances = {"H5": read_concordance(zipped, "H5")}
    lines = {"100111": line("2", "2", "2"), "100119": line("30", "10", "50", 3), "100190": line("7", "7", "7")}

    rows = to_hs2012("H5", lines, concordances)

    assert rows["100110"] == {"rate": None, "minRate": "2", "maxRate": "50", "sourceCodes": 2, "nationalLines": 4, "naLines": 0}
    assert rows["100190"] == line("7", "7", "7") | {"sourceCodes": 1}


def test_older_schedules_take_the_one_code_hs2012_maps_to(tmp_path):
    zipped = tmp_path / "h3.zip"
    write_concordance(zipped, [("100110", "100190"), ("310230", "310230")])
    concordances = {"H3": read_concordance(zipped, "H3")}

    rows = to_hs2012("H3", {"100190": line("4", "4", "4")}, concordances)

    assert rows == {"100110": line("4", "4", "4") | {"sourceCodes": 1}}
    assert to_hs2012("H4", {"310230": line("1", "1", "1")}, {}) == {"310230": line("1", "1", "1") | {"sourceCodes": 1}}


def test_preferences_keep_their_preferential_line_count_and_skip_an_unknown_rate(tmp_path):
    path = tmp_path / "XYZ-2021-A01.xml"
    path.write_text(
        "<message:StructureSpecificData xmlns:message='m'><message:DataSet>"
        "<Series PRODUCTCODE='010121'><Obs OBS_VALUE='1.5' TARIFFTYPE='PREF' MIN_RATE='0' MAX_RATE='3' TOTALNOOFLINES='2' NBR_PREF_LINES='1' NBR_NA_LINES='0' NOMENCODE='H4'/></Series>"
        "<Series PRODUCTCODE='010129'><Obs OBS_VALUE='NaN' TARIFFTYPE='PREF' TOTALNOOFLINES='2' NBR_PREF_LINES='1' NOMENCODE='H4'/></Series>"
        "<Series PRODUCTCODE='010130'><Obs OBS_VALUE='4' TARIFFTYPE='MFN' NOMENCODE='H4'/></Series>"
        "</message:DataSet></message:StructureSpecificData>",
        encoding="utf-8",
    )
    assert read_schedule(path, "PREF") == ("H4", {"010121": line("1.5", "0", "3", 2) | {"prefLines": 1}})
