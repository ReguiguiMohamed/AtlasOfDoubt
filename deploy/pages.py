"""Save the GET answers of a few countries as files, the static sample published on GitHub Pages.

    python -m deploy.pages

Reads the API running on localhost:8000 and writes deploy/sample/api. On
github.io, atlas/static/lib.js reads these files in place of the API.
"""

import json
import shutil
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode
from urllib.request import urlopen

API = "http://localhost:8000/api"
OUT = Path("deploy/sample")
SNAPSHOT = "BACI_HS12_V202601@537b2fe453e3"
# Japan, Germany, Brazil, Mexico, Nigeria, Ethiopia, India and Australia: every inhabited continent, low to high income.
REPORTERS = [392, 276, 76, 484, 566, 231, 699, 36]
# The case studies the product page links to, wheat among them.
CASE_STUDIES = ["10", "1001", "31", "85"]
PRODUCTS = 6
PARTNERS = 5
MIN_VALUE = 1_000_000


def filename(path, latest):
    """The file of one GET answer: its path, then its query sorted, so the browser finds it whatever the order.

    A missing year means the latest one to the API, so that year is left out and both links share a file.
    """
    base, _, search = path.partition("?")
    params = "&".join(f"{k}={v}" for k, v in sorted(parse_qsl(search)) if not (k == "year" and v == str(latest)))
    return f"api{base}{'/' + params if params else ''}.json"


def get(path):
    # A country's first visit answers with the latest year while the others build.
    while True:
        with urlopen(API + path, timeout=600) as response:
            body = json.load(response)
        if not (isinstance(body, dict) and body.get("filling")):
            return body
        time.sleep(5)


def save(path, body, latest):
    file = OUT / filename(path, latest)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    shutil.rmtree(OUT / "api", ignore_errors=True)
    detail = get(f"/snapshots/{quote(SNAPSHOT)}")
    years = detail["years"]
    latest = years[-1]
    # The sample's reporter picker lists these countries only. Partners keep every name for the French labels.
    detail["reporters"] = REPORTERS
    save("/snapshots", [s for s in get("/snapshots") if s["_id"] == SNAPSHOT], latest)
    save(f"/snapshots/{SNAPSHOT}", detail, latest)
    paths = [f"/scenarios/presets?{urlencode({'snapshot': SNAPSHOT})}"]
    for reporter in REPORTERS:
        q = lambda **extra: urlencode({"snapshot": SNAPSHOT, "reporter": reporter, **extra})
        # Asked first, since it builds the country's view.
        overview = get(f"/overview?{q(minValue=MIN_VALUE)}")
        save(f"/overview?{q(minValue=MIN_VALUE)}", overview, latest)
        rows = sorted(overview["rows"], key=lambda r: -r["metrics"]["totalUsd"])
        products = CASE_STUDIES + [r["productCode"] for r in rows[:PRODUCTS]]
        partners = list(dict.fromkeys(r["metrics"]["topSupplier"]["countryCode"] for r in rows if r["metrics"].get("topSupplier")))
        paths += [
            f"/categories?{q()}",
            f"/movers?{q(to=latest, minValue=MIN_VALUE, **{'from': years[0]})}",
            f"/exports?{q(minValue=MIN_VALUE)}",
            f"/routes?{q()}",
            f"/twins?{q(flow='imports')}",
            f"/twins?{q(flow='exports')}",
            *[f"/products/{code}/history?{q()}" for code in products],
            *[f"/products/{code}/tariffs?{q()}" for code in products if len(code) == 6],
            *[f"/products/{code}/network?{q()}" for code in products if len(code) >= 4],
            *[f"/countries/{code}?{q()}" for code in partners[:PARTNERS]],
        ]
    for path in paths:
        try:
            save(path, get(path), latest)
        except HTTPError as error:
            # A reporter with no exports has no export twins, and the page then leaves the panel out.
            print(f"skipped {path}: {error.code}")
    files = list((OUT / "api").rglob("*.json"))
    print(f"{len(files)} files, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB in {OUT / 'api'}")


if __name__ == "__main__":
    main()
