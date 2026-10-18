"""HTTP API over one or more prepared snapshots, for any reporting country.

    uvicorn atlas.api:app

Every request names its snapshot and its reporter, the country whose imports
and exports are shown. The reporter's view is built on its first visit, and
every figure in a response is computed here from stored values. Numbers sent
by the browser are never used.
"""

import csv
import io
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path as FilePath
from typing import Annotated, Literal

from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo.database import Database

from atlas import graph, materialize, metrics, routes, twins
from atlas.db import connect
from atlas.prepare import DATA

CODE_PATTERN = r"^\d{2}(\d{2}){0,2}$"


def warm(db):
    """Open the newest snapshot's Milvus twins and Ladybug graph, then build the countries visited last.

    The stores otherwise cost the first visitor about 2 s, and a country's first visit up to 2 min.
    """
    snapshot = db.snapshots.find_one({"status": "ready"}, sort=[("preparedAt", -1)])
    if not snapshot:
        return
    for part, opened in (("twins", twins.opened), ("graph", graph.opened)):
        if snapshot.get(part):
            path = DATA / snapshot["storage"]["path"] / snapshot[part]["path"]
            if path.exists():
                opened(path)
    materialize.rewarm(db, snapshot)


@asynccontextmanager
async def lifespan(app):
    client, app.state.db = connect()
    # Tests prepare and delete snapshots under the warm thread's feet, so they turn it off.
    if os.environ.get("ATLAS_WARM", "1") == "1":
        threading.Thread(target=warm, args=(app.state.db,), daemon=True).start()
    yield
    client.close()


app = FastAPI(title="AtlasOfDoubt", lifespan=lifespan)
# The imports page sends every imported product at once, about 2 MB of JSON for a real year.
app.add_middleware(GZipMiddleware)


def database(request: Request):
    return request.app.state.db


Db = Annotated[Database, Depends(database)]
SnapshotId = Annotated[str, Query(alias="snapshot")]
Reporter = Annotated[int, Query()]
Code = Annotated[str, Path(pattern=CODE_PATTERN)]
MinValue = Annotated[int, Query(alias="minValue", ge=0)]


def ready_snapshot(db, snapshot_id):
    snapshot = db.snapshots.find_one({"_id": snapshot_id, "status": "ready"})
    if not snapshot:
        raise HTTPException(404, f"no ready snapshot {snapshot_id}")
    return snapshot


def find_country(snapshot, code, status=404):
    country = next((c for c in snapshot["countries"] if c["countryCode"] == code), None)
    if not country:
        raise HTTPException(status, f"no country {code} in {snapshot['_id']}")
    return country


def scope(db, snapshot_id, reporter):
    """The snapshot, the reporter and the generation of the reporter's cached view."""
    snapshot = ready_snapshot(db, snapshot_id)
    country = find_country(snapshot, reporter, status=422)
    return snapshot, country, materialize.ensure(db, snapshot, reporter)


def checked_year(snapshot, year):
    if year is None:
        return max(snapshot["years"])
    if year not in snapshot["years"]:
        raise HTTPException(422, f"{snapshot['_id']} has no year {year}")
    return year


def group_products(db, snapshot_id, code):
    """Dictionary products under an HS code. A 2 or 4 digit code is a group."""
    found = list(
        db.products.find({"snapshotId": snapshot_id, "productCode": {"$regex": f"^{code}"}}, {"_id": 0, "snapshotId": 0})
        .sort("productCode")
    )
    if not found:
        raise HTTPException(404, f"no product {code} in {snapshot_id}")
    return found


def cached(db, generation, code=None, **query):
    if code:
        query["productCode"] = {"$regex": f"^{code}"}
    return list(db.country_product_years.find({"generationId": generation, **query}, {"_id": 0}))


def combined_suppliers(code, docs):
    """Stored suppliers of one product, or a group's suppliers summed across products."""
    lists = [d["imports"]["suppliers"] for d in docs if "imports" in d]
    if len(code) == 6:
        return lists[0] if lists else []
    return metrics.merge(lists)


def names_of(snapshot):
    return {c["countryCode"]: c for c in snapshot["countries"]}


def companion(snapshot, part, store):
    """The path of the snapshot's graph or twins, or a 503 when its files are gone, so only that panel fails."""
    path = DATA / snapshot["storage"]["path"] / snapshot[part]["path"]
    if not path.exists():
        raise HTTPException(503, f"the {store} of {snapshot['_id']} is unavailable")
    return path


def geography(db, snapshot_id, reporter):
    """{partner code: distance, border and language} from CEPII GeoDist, empty when the snapshot has none."""
    found = db.geo_pairs.find({"snapshotId": snapshot_id, "countryCode": reporter}, {"_id": 0, "snapshotId": 0, "countryCode": 0})
    return {g.pop("partnerCode"): g for g in found}


@app.get("/api/snapshots")
def list_snapshots(db: Db):
    return list(db.snapshots.find({"status": "ready"}, {"countries": 0, "files": 0, "errors.samples": 0}).sort("preparedAt", -1))


@app.get("/api/snapshots/{snapshot_id}")
def get_snapshot(db: Db, snapshot_id: str):
    return ready_snapshot(db, snapshot_id)


def categories_named(db, snapshot_id, q, limit=10):
    """Chapters and headings whose HS name holds q, the ones it starts first and the broader before the narrower."""
    pattern = {"$regex": re.escape(q), "$options": "i"}
    found = db.products.find(
        {"snapshotId": snapshot_id, "$or": [{"chapterName": pattern}, {"headingName": pattern}]},
        {"_id": 0, "chapter": 1, "heading": 1, "chapterName": 1, "headingName": 1},
    )
    rows = {}
    for p in found:
        for code, name, level in ((p["chapter"], p["chapterName"], "chapter"), (p["heading"], p["headingName"], "heading")):
            if q.lower() in name.lower():
                rows.setdefault(code, {"productCode": code, "description": name, "heading": p["heading"][: len(code)], "level": level})
    return sorted(rows.values(), key=lambda r: (not r["description"].lower().startswith(q.lower()), len(r["productCode"]),
                                                r["productCode"]))[:limit]


@app.get("/api/categories")
def categories(db: Db, snapshot_id: SnapshotId, reporter: Reporter, year: int | None = None):
    """The reporter's imports as a tree of HS sections, chapters, headings and products, each summed exactly."""
    snapshot, _, generation = scope(db, snapshot_id, reporter)
    if not snapshot.get("categories"):
        raise HTTPException(404, f"{snapshot_id} was prepared without HS names")
    year = checked_year(snapshot, year)
    products = {p["productCode"]: p for p in db.products.find({"snapshotId": snapshot_id}, {"_id": 0, "snapshotId": 0})}
    root = {"children": {}}
    found = db.country_product_years.find(
        {"generationId": generation, "year": year, "imports": {"$exists": True}}, {"productCode": 1, "imports.metrics.totalUsd": 1}
    )
    for r in found:
        p, value = products[r["productCode"]], r["imports"]["metrics"]["totalUsd"]
        # Chapter 99 has no section, so its chapter stands in for one.
        levels = ((p["section"] or p["chapter"], p["sectionName"] or p["chapterName"]), (p["chapter"], p["chapterName"]),
                  (p["heading"], p["headingName"]), (p["productCode"], p["description"]))
        node = root
        for code, name in levels:
            node = node["children"].setdefault(code, {"code": code, "name": name, "valueUsd": metrics.ZERO, "children": {}})
            node["valueUsd"] += value

    def listed(node):
        return sorted(({**n, "children": listed(n)} for n in node["children"].values()), key=lambda n: -n["valueUsd"])

    tree = listed(root)
    return {"snapshot": snapshot_id, "reporter": reporter, "year": year, "totalUsd": sum((n["valueUsd"] for n in tree), metrics.ZERO),
            "sections": tree}


@app.get("/api/products")
def search_products(db: Db, snapshot_id: SnapshotId, q: str = ""):
    ready_snapshot(db, snapshot_id)
    q = q.strip()
    query = {"snapshotId": snapshot_id}
    fields = {"_id": 0, "snapshotId": 0}
    if q.isdigit():
        query["productCode"] = {"$regex": f"^{q}"}
    elif q:
        # The text index matches whole stemmed words in any order and ranks them, and the regex keeps a half-typed word matching.
        score = {"score": {"$meta": "textScore"}}
        ranked = list(db.products.find({**query, "$text": {"$search": q}}, fields | score).sort(score).limit(50))
        for p in ranked:
            del p["score"]
        query["description"] = {"$regex": re.escape(q), "$options": "i"}
        query["productCode"] = {"$nin": [p["productCode"] for p in ranked]}
        rest = list(db.products.find(query, fields).sort("productCode").limit(50 - len(ranked)))
        return categories_named(db, snapshot_id, q) + ranked + rest
    return list(db.products.find(query, fields).sort("productCode").limit(50))


@app.get("/api/overview")
def overview(db: Db, snapshot_id: SnapshotId, reporter: Reporter, year: int | None = None, min_value: MinValue = 0):
    snapshot, _, generation = scope(db, snapshot_id, reporter)
    year = checked_year(snapshot, year)
    found = db.country_product_years.find(
        {"generationId": generation, "year": year, "imports.metrics.totalUsd": {"$gte": min_value}},
        {"_id": 0, "productCode": 1, "description": 1, "imports.metrics": 1, "imports.world.hhi": 1, "imports.world.totalUsd": 1,
         "imports.world.topSupplier": 1},
    ).sort("imports.metrics.totalUsd", -1)
    rows = [
        {"productCode": r["productCode"], "description": r["description"], "metrics": r["imports"]["metrics"],
         "world": r["imports"].get("world")}
        for r in found
    ]
    return {"snapshot": snapshot_id, "reporter": reporter, "year": year, "rows": rows}


@app.get("/api/movers")
def movers(
    db: Db,
    snapshot_id: SnapshotId,
    reporter: Reporter,
    start: Annotated[int | None, Query(alias="from")] = None,
    end: Annotated[int | None, Query(alias="to")] = None,
    min_value: MinValue = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """Products whose supplier HHI rose or fell the most between two years.

    A product counts only if it reached minValue in both years, so a trickle of imports
    that swings from one supplier to another does not crowd out the products that matter.
    """
    snapshot, _, generation = scope(db, snapshot_id, reporter)
    start = checked_year(snapshot, start if start is not None else min(snapshot["years"]))
    end = checked_year(snapshot, end)

    def year_rows(year):
        found = db.country_product_years.find(
            {"generationId": generation, "year": year, "imports.metrics.totalUsd": {"$gte": min_value},
             "imports.metrics.hhi": {"$ne": None}},
            {"_id": 0, "productCode": 1, "description": 1, "imports.metrics": 1},
        )
        return {r["productCode"]: r for r in found}

    before = year_rows(start)
    changes = []
    for code, after in year_rows(end).items():
        if code not in before:
            continue
        old, new = before[code]["imports"]["metrics"], after["imports"]["metrics"]
        changes.append({
            "productCode": code, "description": after["description"],
            "from": old, "to": new, "change": new["hhi"] - old["hhi"],
        })
    changes.sort(key=lambda r: r["change"])
    return {
        "snapshot": snapshot_id, "reporter": reporter, "from": start, "to": end, "compared": len(changes),
        "rising": [r for r in reversed(changes[-limit:]) if r["change"] > 0],
        "falling": [r for r in changes[:limit] if r["change"] < 0],
    }


@app.get("/api/products/{code}/history")
def history(db: Db, code: Code, snapshot_id: SnapshotId, reporter: Reporter):
    """The reporter's imports and exports of one product or group, year by year.

    A product's year also lists the world's largest exporters of it other than
    the reporter, each with its share of world exports.

    A group's RCA compares the reporter's summed exports of the group with the
    world's summed exports of it, as for one product.
    """
    snapshot, _, generation = scope(db, snapshot_id, reporter)
    products = group_products(db, snapshot_id, code)
    by_year = {}
    for doc in cached(db, generation, code):
        by_year.setdefault(doc["year"], []).append(doc)
    world_totals, baskets, exporters = {}, {}, {}
    if len(code) == 6:
        names = names_of(snapshot)
        exporters = {
            w["year"]: [
                {**{k: names[e["countryCode"]][k] for k in ("countryCode", "countryName", "isoCode")}, "valueUsd": e["valueUsd"], "share": e["valueUsd"] / w["totalUsd"]}
                for e in w["topExporters"] if e["countryCode"] != reporter
            ]
            for w in db.world_product_years.find({"snapshotId": snapshot_id, "productCode": code}, {"year": 1, "totalUsd": 1, "topExporters": 1})
        }
    else:
        world = db.world_product_years.aggregate([
            {"$match": {"snapshotId": snapshot_id, "productCode": {"$regex": f"^{code}"}}},
            {"$group": {"_id": "$year", "totalUsd": {"$sum": "$totalUsd"}}},
        ])
        world_totals = {r["_id"]: r["totalUsd"] for r in world}
        baskets = {
            y["year"]: y["exportsUsd"]
            for y in db.country_years.find({"snapshotId": snapshot_id, "countryCode": reporter}, {"year": 1, "exportsUsd": 1})
        }

    years = []
    for year in snapshot["years"]:
        docs = by_year.get(year, [])
        suppliers = combined_suppliers(code, docs)
        sold = [d["exports"] for d in docs if "exports" in d]
        if len(code) == 6:
            imported = docs[0].get("imports") if docs else None
            world, exports = imported and imported["world"], sold[0] if sold else None
        else:
            value = sum((e["totalUsd"] for e in sold), metrics.ZERO)
            world = None
            exports = {
                "totalUsd": value,
                "rca": metrics.rca(value, baskets.get(year), world_totals.get(year), snapshot["worldTotals"][str(year)]),
                "worldShare": value / world_totals[year],
            } if sold else None
        years.append({
            "year": year,
            "metrics": metrics.summarize(suppliers) if suppliers else None,
            "suppliers": metrics.with_shares(suppliers),
            "world": world,
            "exports": exports,
            "exporters": exporters.get(year, []),
        })
    return {
        "snapshot": snapshot_id, "reporter": reporter, "code": code, "products": products, "years": years,
        "geography": geography(db, snapshot_id, reporter),
    }


@app.get("/api/products/{code}/network")
def network(db: Db, code: Code, snapshot_id: SnapshotId, reporter: Reporter):
    """The reporter's supplier network for the heading of a 4 or 6 digit code, from the snapshot's Ladybug graph."""
    snapshot = ready_snapshot(db, snapshot_id)
    find_country(snapshot, reporter, status=422)
    if not snapshot.get("graph"):
        raise HTTPException(404, f"{snapshot_id} has no graph")
    if len(code) < 4:
        raise HTTPException(422, "the graph holds headings, so the code needs 4 or 6 digits")
    group_products(db, snapshot_id, code)
    found = graph.network(companion(snapshot, "graph", "Ladybug graph"), reporter, code[:4])
    names = names_of(snapshot)
    codes = {reporter, *(r[k] for rows in found.values() for r in rows for k in ("countryCode", "origin", "via") if k in r)}
    return {
        "snapshot": snapshot_id, "reporter": reporter, "heading": code[:4], "year": snapshot["graph"]["year"], **found,
        "names": {c: names[c]["countryName"] for c in codes},
    }


@app.get("/api/twins")
def trade_twins(db: Db, snapshot_id: SnapshotId, reporter: Reporter, flow: Literal["imports", "exports"] = "exports"):
    """Countries whose basket of the flow looks most like the reporter's in the snapshot's last year, from Milvus."""
    snapshot = ready_snapshot(db, snapshot_id)
    home = find_country(snapshot, reporter, status=422)
    if not snapshot.get("twins"):
        raise HTTPException(404, f"{snapshot_id} has no twins")
    found = twins.twins(companion(snapshot, "twins", "Milvus twins"), flow, reporter)
    if found is None:
        raise HTTPException(404, f"{home['countryName']} has no {flow} in {snapshot['twins']['year']}")
    names = names_of(snapshot)
    codes = {p["productCode"] for s in found["closest"] for p in s["shared"]}
    descriptions = {p["productCode"]: p["description"] for p in db.products.find({"snapshotId": snapshot_id, "productCode": {"$in": list(codes)}})}
    country = lambda s: {k: names[s["countryCode"]][k] for k in ("countryName", "isoCode")} | s
    return {
        "snapshot": snapshot_id, "reporter": reporter, "flow": flow, "year": snapshot["twins"]["year"], "metric": snapshot["twins"]["metric"],
        "similar": [country(s) for s in found["similar"]],
        "closest": [country(s) | {"shared": [p | {"description": descriptions.get(p["productCode"])} for p in s["shared"]]} for s in found["closest"]],
    }


@app.get("/api/products/{code}/tariffs")
def tariffs(db: Db, code: Code, snapshot_id: SnapshotId, reporter: Reporter):
    """The tariff every market with a TRAINS schedule charges the reporter on one HS6 product.

    Each market's rate is the lower of its MFN rate and the best preference
    covering the reporter, with the agreement in preference and the MFN rate in
    mfn. Members of one customs union, like the EU, charge each other nothing.
    A rate is a simple average of national lines, and a code several source
    codes met in has only a range. Markets are ordered by their rate, or a
    range's maximum. Each market carries what the reporter sold it in the
    snapshot's last year. charged holds the suppliers the reporter's own
    schedule gives a preference, with their rate.
    """
    snapshot, _, generation = scope(db, snapshot_id, reporter)
    if not snapshot.get("tariffs"):
        raise HTTPException(404, f"{snapshot_id} has no tariffs")
    if len(code) != 6:
        raise HTTPException(422, "tariffs are per HS6 product, so the code needs 6 digits")
    products = group_products(db, snapshot_id, code)
    found = db.tariffs.find({"snapshotId": snapshot_id, "productCode": code}, {"_id": 0, "snapshotId": 0, "productCode": 0})
    rates = {t.pop("schedule"): t for t in found}
    partners = snapshot["tariffs"].get("partners", {})
    names = {c["countryCode"]: c for c in snapshot["countries"]}
    covering = [p for p, v in partners.items() if reporter in v["members"]]
    best = {}
    for f in db.preferences.find({"snapshotId": snapshot_id, "productCode": code, "partner": {"$in": covering}}, {"_id": 0}):
        if f["schedule"] not in best or rank(f) < rank(best[f["schedule"]]):
            best[f["schedule"]] = f
    reporter_schedule = (names.get(reporter, {}).get("tariffSchedule") or {}).get("schedule")

    def charge(schedule, country):
        mfn = rates[schedule]
        if schedule == reporter_schedule and country != reporter:
            return {"rate": 0.0, "minRate": 0.0, "maxRate": 0.0, "mfn": mfn, "preference": {"partner": schedule, "name": "customs union"}}
        # ponytail: the lowest of HS6 averages stands in for the line-level minimum, which WITS does not send per line.
        if (pref := best.get(schedule)) and rank(pref) < rank(mfn):
            return {k: pref[k] for k in ("rate", "minRate", "maxRate", "nationalLines", "prefLines")} | {
                "mfn": mfn, "preference": {"partner": pref["partner"], "name": partners[pref["partner"]]["name"]},
            }
        return mfn | {"mfn": mfn, "preference": None}

    year = max(snapshot["years"])
    view = db.country_product_years.find_one({"generationId": generation, "productCode": code, "year": year}, {"exports.destinations": 1})
    sold = {d["countryCode"]: d["valueUsd"] for d in (view or {}).get("exports", {}).get("destinations", [])}
    markets = sorted(
        (
            {k: c[k] for k in ("countryCode", "countryName", "isoCode")} | {"schedule": s["schedule"]} | charge(s["schedule"], c["countryCode"])
            | {"exportsUsd": sold.get(c["countryCode"])}
            for c in snapshot["countries"] if (s := c.get("tariffSchedule")) and s["schedule"] in rates
        ),
        key=lambda m: (-rank(m), m["countryName"]),
    )
    charged = {}
    if reporter_schedule in rates:
        for f in db.preferences.find({"snapshotId": snapshot_id, "productCode": code, "schedule": reporter_schedule}, {"_id": 0}):
            for member in partners.get(f["partner"], {}).get("members", []):
                if member != reporter and (member not in charged or rank(f) < rank(charged[member])):
                    charged[member] = f
        charged = {
            str(m): {k: f[k] for k in ("rate", "minRate", "maxRate", "partner")} | {"name": partners[f["partner"]]["name"]}
            for m, f in charged.items() if rank(f) < rank(rates[reporter_schedule])
        }
    return {
        "snapshot": snapshot_id, "reporter": reporter, "code": code, "description": products[0]["description"],
        "source": snapshot["tariffs"], "markets": markets, "exportYear": year,
        "own": next((m for m in markets if m["countryCode"] == reporter), None), "charged": charged,
    }


def rank(rate):
    return rate["rate"] if rate["rate"] is not None else rate["maxRate"] or 0


@app.get("/api/countries/{country_code}")
def country_profile(db: Db, country_code: int, snapshot_id: SnapshotId, reporter: Reporter, year: int | None = None):
    """What one partner sends the reporter, and what the reporter sends it back.

    Rank is one plus the number of suppliers that sent more, so equal values share a rank.
    """
    snapshot, home, generation = scope(db, snapshot_id, reporter)
    year = checked_year(snapshot, year)
    country = find_country(snapshot, country_code)

    totals = {
        y["year"]: y for y in db.country_years.find({"snapshotId": snapshot_id, "countryCode": reporter})
    }
    own = {"$first": {"$filter": {"input": "$imports.suppliers", "cond": {"$eq": ["$$this.countryCode", country_code]}}}}
    supplied = db.country_product_years.aggregate([
        {"$match": {"generationId": generation, "imports.suppliers.countryCode": country_code}},
        {"$project": {"year": 1, "own": own}},
        {"$group": {"_id": "$year", "valueUsd": {"$sum": "$own.valueUsd"}, "productCount": {"$sum": 1}}},
    ])
    by_year = {r["_id"]: r for r in supplied}
    years = []
    for y in snapshot["years"]:
        row, total = by_year.get(y), totals.get(y)
        sold = next((d["valueUsd"] for d in total["destinations"] if d["countryCode"] == country_code), None) if total else None
        years.append({
            "year": y,
            "valueUsd": row["valueUsd"] if row else None,
            "shareOfImports": row["valueUsd"] / total["importsUsd"] if row else None,
            "productCount": row["productCount"] if row else 0,
            "exportsUsd": sold,
            "shareOfExports": sold / total["exportsUsd"] if sold else None,
        })

    # Ranking inside the database sends one small row per product instead of every supplier list.
    rows = db.country_product_years.aggregate([
        {"$match": {"generationId": generation, "year": year, "imports.suppliers.countryCode": country_code}},
        {"$project": {"productCode": 1, "description": 1, "metrics": "$imports.metrics", "values": "$imports.suppliers.valueUsd", "own": own}},
        {"$project": {
            "_id": 0,
            "productCode": 1,
            "description": 1,
            "valueUsd": "$own.valueUsd",
            "rank": {"$add": [1, {"$size": {"$filter": {"input": "$values", "cond": {"$gt": ["$$this", "$own.valueUsd"]}}}}]},
            "supplierCount": {"$size": "$values"},
            "totalUsd": "$metrics.totalUsd",
            "hhi": "$metrics.hhi",
        }},
        {"$sort": {"valueUsd": -1}},
    ])
    products = [{**r, "share": r["valueUsd"] / r["totalUsd"]} for r in rows]
    route = routes.route(home["isoCode"], country["isoCode"])
    return {
        "snapshot": snapshot_id, "reporter": home, "year": year, "country": country, "years": years, "products": products,
        "geography": geography(db, snapshot_id, reporter).get(country_code),
        "route": {"id": route["id"], "name": route["name"], "via": [routes.CHOKEPOINTS[c]["name"] for c in route["via"]]}
        if route else None,
    }


@app.get("/api/routes")
def sea_routes(
    db: Db,
    snapshot_id: SnapshotId,
    reporter: Reporter,
    year: int | None = None,
    code: Annotated[str | None, Query(pattern=CODE_PATTERN)] = None,
):
    """The reporter's imports grouped by modelled sea route and chokepoint, for one year and as a yearly trend.

    A chokepoint carries the sum of the routes through it, so a country counts once
    per strait it passes and never twice on one strait.
    """
    snapshot, home, generation = scope(db, snapshot_id, reporter)
    year = checked_year(snapshot, year)
    match = {"generationId": generation, "imports": {"$exists": True}}
    if code:
        group_products(db, snapshot_id, code)
        match["productCode"] = {"$regex": f"^{code}"}
    names = names_of(snapshot)
    supplied = db.country_product_years.aggregate([
        {"$match": match},
        {"$unwind": "$imports.suppliers"},
        {"$group": {"_id": {"year": "$year", "country": "$imports.suppliers.countryCode"},
                    "valueUsd": {"$sum": "$imports.suppliers.valueUsd"}}},
    ])
    by_year = {y: [] for y in snapshot["years"]}
    for r in supplied:
        country = names[r["_id"]["country"]]
        by_year[r["_id"]["year"]].append({
            "countryCode": country["countryCode"], "countryName": country["countryName"],
            "isoCode": country["isoCode"], "valueUsd": r["valueUsd"],
        })
    grouped = {y: routes.by_route(s) for y, s in by_year.items()}
    totals = {y: metrics.total(s) for y, s in by_year.items()}
    plan = routes.plan(home["isoCode"])
    # A reporter outside every region has no modelled routes, so all its suppliers are unrouted.
    unrouted = [None] if plan else [None, *(r["id"] for r in routes.REGIONS)]

    def measure(route_ids, y):
        value = metrics.total(s for r in route_ids for s in grouped[y].get(r, []))
        return {"year": y, "valueUsd": value, "share": value / totals[y] if totals[y] else None}

    def entry(route_ids):
        suppliers = [s for r in route_ids for s in grouped[year].get(r, [])]
        return {
            **measure(route_ids, year),
            "countries": metrics.with_shares(suppliers),
            "years": [measure(route_ids, y) for y in snapshot["years"]],
        }

    return {
        "snapshot": snapshot_id, "reporter": home, "year": year, "code": code, "totalUsd": totals[year],
        "home": next((r["hub"] for r in routes.REGIONS if r["id"] == routes.REGION_OF.get(home["isoCode"])), None),
        "chokepoints": [
            {"id": c, "name": p["name"], "at": p["at"], "routes": routes.through(plan, c), **entry(routes.through(plan, c))}
            for c, p in routes.CHOKEPOINTS.items()
        ],
        "routes": [{**r, **entry([r["id"]])} for r in plan],
        "unrouted": entry(unrouted),
    }


PRODUCT_EXPORT_FIELDS = (
    "totalUsd", "quantityValidValueUsd", "validQuantityTonnes", "quantityCoverage",
    "unitValueUsdPerTonne", "rca", "worldShare", "prody", "qualityFlags",
)


@app.get("/api/exports")
def exports(db: Db, snapshot_id: SnapshotId, reporter: Reporter, year: int | None = None, min_value: MinValue = 0):
    """The reporter's export structure: a yearly trend, its destinations and its products of one year."""
    snapshot, _, generation = scope(db, snapshot_id, reporter)
    year = checked_year(snapshot, year)
    names = names_of(snapshot)
    by_year = {y["year"]: y for y in db.country_years.find({"snapshotId": snapshot_id, "countryCode": reporter}, {"_id": 0})}
    trend = [
        {k: by_year[y][k] for k in ("year", "exportsUsd", "importsUsd", "productHhi", "geoHhi", "expy", "expyFixed2012")}
        if y in by_year else {"year": y, "exportsUsd": None}
        for y in snapshot["years"]
    ]
    chosen = by_year.get(year)
    geo = geography(db, snapshot_id, reporter)
    destinations = [
        {**{k: names[d["countryCode"]][k] for k in ("countryCode", "countryName", "isoCode")}, "valueUsd": d["valueUsd"],
         "share": d["valueUsd"] / chosen["exportsUsd"], **geo.get(d["countryCode"], {})}
        for d in chosen["destinations"]
    ] if chosen else []
    found = db.country_product_years.find(
        {"generationId": generation, "year": year, "exports.totalUsd": {"$gte": min_value}},
        # Each product's destinations, the bulk of the document, are read on the product page instead.
        {"_id": 0, "productCode": 1, "description": 1} | {f"exports.{f}": 1 for f in PRODUCT_EXPORT_FIELDS},
    ).sort("exports.totalUsd", -1)
    products = [{"productCode": r["productCode"], "description": r["description"], **r["exports"]} for r in found]
    return {
        "snapshot": snapshot_id, "reporter": reporter, "year": year, "gdp": snapshot.get("gdp"),
        "years": trend, "destinations": destinations, "products": products,
    }


LIMITATIONS = [
    "Values are nominal current US dollars as published in BACI, with no inflation adjustment.",
    "The affected value is historical import value exposed under this scenario. It is not a forecast of losses.",
    "No replacement by other suppliers and no price response are assumed.",
    "A missing flow means BACI recorded no positive flow. It is not a confirmed zero.",
    "Tonnes are never added across different products.",
]


class ScenarioSpec(BaseModel):
    snapshot: str
    reporter: int
    year: int
    mode: Literal["product", "country"]
    productCode: str | None = Field(None, pattern=CODE_PATTERN)
    suppliers: list[int] = Field(min_length=1)
    reduction: Decimal = Field(ge=0, le=1)


class ReportRequest(ScenarioSpec):
    title: str = Field(min_length=1, max_length=200)


def run_scenario(db, snapshot, generation, spec):
    checked_year(snapshot, spec.year)
    names = {c["countryCode"]: c["countryName"] for c in snapshot["countries"]}
    unknown = set(spec.suppliers) - names.keys()
    if unknown:
        raise HTTPException(422, f"unknown country codes {sorted(unknown)}")
    if spec.mode == "product":
        if spec.productCode is None:
            raise HTTPException(422, "product mode needs a productCode")
        products = group_products(db, spec.snapshot, spec.productCode)
        suppliers = combined_suppliers(spec.productCode, cached(db, generation, spec.productCode, year=spec.year))
        return {
            "description": products[0]["description"] if len(spec.productCode) == 6 else f"{len(products)} products",
            **metrics.scenario(suppliers, spec.suppliers, spec.reduction),
        }

    selected = set(spec.suppliers)
    rows, total_imports, supplier_totals = [], metrics.ZERO, dict.fromkeys(selected, metrics.ZERO)
    for doc in cached(db, generation, year=spec.year, imports={"$exists": True}):
        suppliers = doc["imports"]["suppliers"]
        total_imports += metrics.total(suppliers)
        hit = [s for s in suppliers if s["countryCode"] in selected]
        if not hit:
            continue
        for s in hit:
            supplier_totals[s["countryCode"]] += s["valueUsd"]
        result = metrics.scenario(suppliers, selected, spec.reduction)
        rows.append({
            "productCode": doc["productCode"],
            "description": doc["description"],
            "totalUsd": result["baseline"]["totalUsd"],
            "affectedUsd": result["affectedUsd"],
            "exposureShare": result["exposureShare"],
            "baselineHhi": result["baseline"]["hhi"],
            "remainingHhi": result["remaining"]["hhi"],
        })
    rows.sort(key=lambda r: r["affectedUsd"], reverse=True)
    affected = sum((r["affectedUsd"] for r in rows), metrics.ZERO)
    return {
        "totalImportsUsd": total_imports,
        "affectedUsd": affected,
        "exposureShare": affected / total_imports if total_imports else None,
        "suppliers": [
            {"countryCode": code, "countryName": names[code], "valueUsd": value} for code, value in supplier_totals.items()
        ],
        "products": rows,
    }


@app.post("/api/scenarios/preview")
def preview(db: Db, spec: ScenarioSpec):
    snapshot, _, generation = scope(db, spec.snapshot, spec.reporter)
    result = run_scenario(db, snapshot, generation, spec)
    return {"spec": spec.model_dump(), "calculationVersion": metrics.CALCULATION_VERSION, "result": result}


@app.post("/api/reports", status_code=201)
def create_report(db: Db, request: ReportRequest):
    snapshot, reporter, generation = scope(db, request.snapshot, request.reporter)
    result = run_scenario(db, snapshot, generation, request)
    report = {
        "title": request.title,
        "createdAt": datetime.now(timezone.utc),
        "reporter": {k: reporter[k] for k in ("countryCode", "countryName", "isoCode")},
        "spec": request.model_dump(exclude={"title"}),
        "snapshot": {k: snapshot[k] for k in ("source", "archive", "manifest")} | {"id": snapshot["_id"]},
        "calculationVersion": metrics.CALCULATION_VERSION,
        "limitations": LIMITATIONS,
        "result": result,
    }
    return {"id": str(db.reports.insert_one(report).inserted_id)}


def find_report(db, report_id):
    report = db.reports.find_one({"_id": ObjectId(report_id)}) if ObjectId.is_valid(report_id) else None
    if not report:
        raise HTTPException(404, f"no report {report_id}")
    return {**report, "_id": str(report["_id"])}


@app.get("/api/reports")
def list_reports(db: Db, reporter: Reporter):
    reports = db.reports.find({"reporter.countryCode": reporter}, {"title": 1, "createdAt": 1, "spec": 1}).sort("createdAt", -1)
    return [{**r, "_id": str(r["_id"])} for r in reports]


CSV_COLUMNS = {
    "product": ["countryCode", "countryName", "isoCode", "selected", "baselineUsd", "baselineShare", "remainingUsd", "remainingShare"],
    "country": ["productCode", "description", "totalUsd", "affectedUsd", "exposureShare", "baselineHhi", "remainingHhi"],
}


@app.get("/api/reports/{report_id}.csv")
def report_csv(db: Db, report_id: str):
    """The report's result table. Provenance and limitations live in the report page."""
    report = find_report(db, report_id)
    mode = report["spec"]["mode"]
    rows = report["result"]["suppliers" if mode == "product" else "products"]
    out = io.StringIO()
    writer = csv.DictWriter(out, CSV_COLUMNS[mode], extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="report-{report_id}.csv"'},
    )


@app.get("/api/reports/{report_id}")
def get_report(db: Db, report_id: str):
    return find_report(db, report_id)


class RevalidatedFiles(StaticFiles):
    # With no Cache-Control browsers cache by heuristic, and after a deploy one page can load new and stale modules together.
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Mounted last so every /api route above wins over the static catch-all.
app.mount("/", RevalidatedFiles(directory=FilePath(__file__).parent / "static", html=True), name="static")
