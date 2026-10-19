"""Build one country's view of a snapshot into MongoDB on its first visit.

The country's imports come from its own Parquet partition and its exports
from its export partition, joined to the world aggregates the snapshot
already holds. The last year's exports also keep their destinations, read
from every importer's partition of that year. Each build is one generation of documents, readable only
after its job is marked ready, so a failed or interrupted build never
shows. The least recently used generations are evicted once the cache
passes its byte budget.

A page that reads only the first and last years, like the overview, does
not wait for the rest. Those two years are built and readable first, and a
background thread adds the other years to the same generation.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import duckdb
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from atlas import metrics
from atlas.prepare import DATA

# Uncompressed BSON, which WiredTiger stores in about half, so the VM keeps some 15 visited countries in 2 GB of disk.
CACHE_BYTES = 4_000_000_000
LEASE = timedelta(minutes=10)
POLL = 0.5
WORLD_ALTERNATIVES = 5
INSERT_BATCH = 2000
INSERT_THREADS = 4
RECENT = 3
# Two years build at once, so two first visits both move while the app stays within its memory cap.
# Reads of countries already built never wait on this.
BUILDS = threading.BoundedSemaphore(2)
# Fills and the boot rewarm run in the background and take one slot at most, so a visitor's first build always has the other.
FILLS = threading.BoundedSemaphore(1)
WORLD_FIELDS = ("productCode", "year", "totalUsd", "sumSquares", "exporterCount", "unitValueUsdPerTonne", "prody")


def ensure(db, snapshot, country, years=None, budget=CACHE_BYTES, background=False):
    """Return the ready generation id for this snapshot and country that holds these years, or every year when none are given."""
    key = {"snapshotId": snapshot["_id"], "countryCode": country}
    quick = {min(snapshot["years"]), max(snapshot["years"])}
    split = years is not None and set(years) <= quick
    while True:
        now = datetime.now(timezone.utc)
        job = db.materializations.find_one_and_update({**key, "status": "ready"}, {"$set": {"lastUsedAt": now}})
        # A job still filling in lists the years it holds so far.
        if job and ("years" not in job or set(years or snapshot["years"]) <= set(job["years"])):
            return job["generationId"]
        generation = uuid.uuid4().hex
        try:
            # Only a failed job or one whose builder stopped renewing can be taken over. Anything else hits the unique key.
            previous = db.materializations.find_one_and_update(
                {**key, "$or": [{"status": {"$in": ["failed", "evicted"]}}, {"status": {"$in": ["building", "ready"]}, "leaseUntil": {"$lt": now}}]},
                {"$set": {"status": "building", "generationId": generation, "leaseUntil": now + LEASE, "startedAt": now}, "$unset": {"years": ""}},
                upsert=True,
                return_document=ReturnDocument.BEFORE,
            )
        except DuplicateKeyError:
            time.sleep(POLL)
            continue
        if previous:
            db.country_product_years.delete_many({"generationId": previous["generationId"]})
        try:
            # Holding the slot only while building, a rewarm waiting on a visitor's fill never blocks that fill.
            with FILLS if background else nullcontext():
                build(db, snapshot, country, generation, quick if split else None)
        except Exception as exc:
            db.materializations.update_one(
                {**key, "generationId": generation},
                {"$set": {"status": "failed", "failure": str(exc)}, "$unset": {"leaseUntil": ""}},
            )
            db.country_product_years.delete_many({"generationId": generation})
            raise
        ready = {"status": "ready", "bytes": size_of(db, generation), "lastUsedAt": now}
        # The filler keeps the lease, so a reader can take over if the process stops before the other years are in.
        update = {"$set": {**ready, "years": sorted(quick)}} if split else {"$set": ready, "$unset": {"leaseUntil": ""}}
        # A builder whose lease was taken over while it ran must not overwrite the newer job.
        done = db.materializations.update_one({**key, "generationId": generation, "status": "building"}, update)
        if not done.modified_count:
            db.country_product_years.delete_many({"generationId": generation})
            continue
        evict(db, budget, keep=generation)
        if split:
            threading.Thread(
                target=fill, args=(db, snapshot, country, generation, set(snapshot["years"]) - quick, budget),
                name=f"fill-{country}", daemon=True,
            ).start()
        return generation


def fill(db, snapshot, country, generation, years, budget):
    """Add the years a quick first build left out to its generation, then mark the job complete."""
    key = {"snapshotId": snapshot["_id"], "countryCode": country, "generationId": generation}
    try:
        with FILLS:
            build(db, snapshot, country, generation, years)
    except Exception as exc:
        db.materializations.update_one(key, {"$set": {"status": "failed", "failure": str(exc)}, "$unset": {"leaseUntil": "", "years": ""}})
        db.country_product_years.delete_many({"generationId": generation})
        return
    done = db.materializations.update_one(
        {**key, "status": "ready"}, {"$set": {"bytes": size_of(db, generation)}, "$unset": {"leaseUntil": "", "years": ""}}
    )
    if not done.modified_count:
        db.country_product_years.delete_many({"generationId": generation})
        return
    evict(db, budget, keep=generation)


def size_of(db, generation):
    return next(
        db.country_product_years.aggregate([
            {"$match": {"generationId": generation}},
            {"$group": {"_id": None, "bytes": {"$sum": {"$bsonSize": "$$ROOT"}}}},
        ]),
        {"bytes": 0},
    )["bytes"]


def evict(db, budget, keep):
    """Drop the least recently used generations beyond the budget, never the one just built or one still filling in.

    The job stays as "evicted" with its last use, so a restart knows which countries to rebuild.

    ponytail: a request that read a job just before its eviction sees an empty
    generation once, and the next request rebuilds. Add a reader count if that
    ever shows up in practice.
    """
    used = 0
    for job in db.materializations.find({"status": "ready"}, sort=[("lastUsedAt", -1)]):
        used += job.get("bytes", 0)
        if used > budget and job["generationId"] != keep and "years" not in job:
            db.materializations.update_one(
                {"_id": job["_id"], "generationId": job["generationId"]}, {"$set": {"status": "evicted"}}
            )
            db.country_product_years.delete_many({"generationId": job["generationId"]})


def rewarm(db, snapshot, count=RECENT):
    """Build the snapshot's view for the countries visited last in any snapshot, the latest built last so it stays newest."""
    known = {c["countryCode"] for c in snapshot["countries"]}
    recent = []
    for job in db.materializations.find({"lastUsedAt": {"$exists": True}}, {"countryCode": 1}, sort=[("lastUsedAt", -1)]):
        if job["countryCode"] in known and job["countryCode"] not in recent:
            recent.append(job["countryCode"])
        if len(recent) == count:
            break
    for country in reversed(recent):
        ensure(db, snapshot, country, background=True)
    return recent


def parquet(path, years):
    return sorted(p.as_posix() for p in path.glob("year=*/*.parquet") if int(p.parent.name.removeprefix("year=")) in years)


def build(db, snapshot, country, generation, years=None):
    """Write the country's documents of these years, or of every year, into the generation."""
    # A year's rows sit in Python lists until they are inserted. All 13 years of the USA at once
    # filled a 2.5 GB container, while one year needs a few hundred MB.
    for year in sorted(years or snapshot["years"]):
        with BUILDS:
            build_year(db, snapshot, country, generation, year)


def build_year(db, snapshot, country, generation, year):
    years = {year}
    root = DATA / snapshot["storage"]["path"]
    flow_files = parquet(root / "flows" / f"importer={country}", years)
    export_files = parquet(root / "exports" / f"country={country}", years)
    last = max(snapshot["years"])
    sold_files = sorted(p.as_posix() for p in (root / "flows").glob(f"*/year={last}/*.parquet")) if last in years else []
    with duckdb.connect() as con:
        flows = con.execute(
            "SELECT year, product, exporter, v * 1000, q FROM read_parquet(?, hive_partitioning = true)"
            " ORDER BY year, product, v DESC, exporter",
            [flow_files],
        ).fetchall() if flow_files else []
        exports = con.execute(
            "SELECT year, product, value, quantity_value, tonnes FROM read_parquet(?, hive_partitioning = true)",
            [export_files],
        ).fetchall() if export_files else []
        sold = con.execute(
            "SELECT product, importer, v * 1000 FROM read_parquet(?, hive_partitioning = true)"
            " WHERE exporter = ? ORDER BY product, v DESC, importer",
            [sold_files, country],
        ).fetchall() if sold_files else []

    names = {c["countryCode"]: c for c in snapshot["countries"]}
    suppliers = {}
    for year, product, exporter, value, tonnes in flows:
        suppliers.setdefault((product, year), []).append({
            "countryCode": exporter,
            "countryName": names[exporter]["countryName"],
            "isoCode": names[exporter]["isoCode"],
            "valueUsd": value,
            "quantityTonnes": tonnes,
        })
    destinations = {}
    for product, importer, value in sold:
        destinations.setdefault(product, []).append({"countryCode": importer, "valueUsd": value})
    exported = {(product, year): (value, quantity_value, tonnes) for year, product, value, quantity_value, tonnes in exports}
    keys = suppliers.keys() | exported.keys()
    codes = sorted({product for product, _ in keys})
    descriptions = {
        p["productCode"]: p["description"]
        for p in db.products.find(
            {"snapshotId": snapshot["_id"], "productCode": {"$in": codes}}, {"_id": 0, "productCode": 1, "description": 1}
        )
    }
    worlds = {
        (w["productCode"], w["year"]): w
        for w in db.world_product_years.find(
            {"snapshotId": snapshot["_id"], "productCode": {"$in": codes}, "year": {"$in": sorted(years)}},
            # The country itself may be one of the top exporters, so one more than the alternatives kept.
            {**{f: 1 for f in WORLD_FIELDS}, "topExporters": {"$slice": WORLD_ALTERNATIVES + 1}},
        )
    }
    basket_totals = {
        y["year"]: y["exportsUsd"] for y in db.country_years.find({"snapshotId": snapshot["_id"], "countryCode": country})
    }

    docs = []
    for product, year in sorted(keys):
        world = worlds[(product, year)]
        own = exported.get((product, year))
        doc = {"generationId": generation, "productCode": product, "description": descriptions[product], "year": year}
        if (product, year) in suppliers:
            found = suppliers[(product, year)]
            doc["imports"] = {
                "metrics": metrics.summarize(found),
                "suppliers": found,
                "world": world_without(world, country, own[0] if own else metrics.ZERO, names),
            }
        if own:
            value, quantity_value, tonnes = own
            coverage = quantity_value / value
            unit_value = metrics.unit_value(quantity_value, tonnes)
            doc["exports"] = {
                "totalUsd": value,
                "quantityValidValueUsd": quantity_value,
                "validQuantityTonnes": tonnes,
                "quantityCoverage": coverage,
                "unitValueUsdPerTonne": unit_value,
                "rca": metrics.rca(value, basket_totals[year], world["totalUsd"], snapshot["worldTotals"][str(year)]),
                "worldShare": value / world["totalUsd"],
                "prody": world["prody"],
                "qualityFlags": metrics.quality_flags(coverage, tonnes, unit_value, world["unitValueUsdPerTonne"]),
            }
            if year == last:
                doc["exports"]["destinations"] = destinations.get(product, [])
        docs.append(doc)
    # Parallel batches keep mongod indexing one batch while the next is encoded.
    with ThreadPoolExecutor(INSERT_THREADS) as pool:
        list(pool.map(
            lambda i: db.country_product_years.insert_many(docs[i:i + INSERT_BATCH], ordered=False),
            range(0, len(docs), INSERT_BATCH),
        ))


def world_without(world, country, value, names):
    """World exporters of one product with this country taken out, the alternatives it could buy from."""
    rest = world["totalUsd"] - value
    if not rest:
        return None
    top = [
        {
            "countryCode": e["countryCode"],
            "countryName": names[e["countryCode"]]["countryName"],
            "isoCode": names[e["countryCode"]]["isoCode"],
            "share": e["valueUsd"] / rest,
        }
        for e in world["topExporters"]
        if e["countryCode"] != country
    ][:WORLD_ALTERNATIVES]
    return {
        "totalUsd": rest,
        "supplierCount": world["exporterCount"] - (1 if value else 0),
        "hhi": metrics.excluded_hhi(world["totalUsd"], world["sumSquares"], value),
        "topSupplier": {k: top[0][k] for k in ("countryCode", "countryName", "share")},
        "top3Share": sum((e["share"] for e in top[:3]), metrics.ZERO),
        "topExporters": top,
    }
