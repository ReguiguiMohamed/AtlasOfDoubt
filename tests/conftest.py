import os
import tempfile
import threading
import zipfile

import pytest

# These are read when atlas is imported, so they are set first.
os.environ["ATLAS_DB"] = "atlas_test"
os.environ["ATLAS_WARM"] = "0"
os.environ["ATLAS_DATA"] = tempfile.mkdtemp(prefix="atlas-test-")

from atlas.db import connect
from atlas.prepare import YEARS

COUNTRIES = [
    ("4", "Afghanistan", "AFG"),
    ("156", "China", "CHN"),
    ("251", "France", "FRA"),
    ("380", "Italy", "ITA"),
    ("788", "Tunisia", "TUN"),
    ("842", "USA", "USA"),
]
PRODUCTS = [
    ("010121", "Horses: live, pure-bred breeding animals"),
    ("100119", "Wheat: durum wheat, other than seed"),
    ("100199", "Meslin: other"),
    ("310230", "Fertilizers: ammonium nitrate"),
]


@pytest.fixture
def products():
    return dict(PRODUCTS)


@pytest.fixture
def db():
    client, database = connect()
    client.drop_database(database.name)
    client.close()
    client, database = connect()
    yield database
    # A first visit's background fill must finish before the next test drops the database under it.
    for thread in threading.enumerate():
        if thread.name.startswith("fill-"):
            thread.join(timeout=30)
    client.close()


@pytest.fixture
def make_archive(tmp_path):
    """Write a BACI-shaped zip with the given flows, {year: ["t,i,j,k,v,q" lines]}."""

    def make(rows_by_year, release="202601", skip_year=None):
        path = tmp_path / f"BACI_HS12_V{release}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                f"country_codes_V{release}.csv",
                "country_code,country_name,country_iso2,country_iso3\n"
                + "".join(f"{c},{n},{i[:2]},{i}\n" for c, n, i in COUNTRIES),
            )
            archive.writestr(
                f"product_codes_HS12_V{release}.csv",
                "code,description\n" + "".join(f'{c},"{d}"\n' for c, d in PRODUCTS),
            )
            for year in YEARS:
                if year != skip_year:
                    lines = rows_by_year.get(year, [])
                    archive.writestr(f"BACI_HS12_Y{year}_V{release}.csv", "t,i,j,k,v,q\n" + "".join(f"{r}\n" for r in lines))
        return path

    return make
