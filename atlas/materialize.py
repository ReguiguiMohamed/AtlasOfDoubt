"""Build one country's view of a snapshot into MongoDB on its first visit.

The country's imports come from its own Parquet partition and its exports
from its export partition, joined to the world aggregates the snapshot
already holds. Each build is one generation of documents, readable only
after its job is marked ready, so a failed or interrupted build never
shows. The least recently used generations are evicted once the cache
passes its byte budget.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

import duckdb
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from atlas import metrics
from atlas.prepare import DATA

CACHE_BYTES = 1_000_000_000
LEASE = timedelta(minutes=10)
POLL = 0.5
WORLD_ALTERNATIVES = 5


def ensure(db, snapshot, country, budget=CACHE_BYTES):
    """Return the ready generation id for this snapshot and country, building it if needed."""
    key = {"snapshotId": snapshot["_id"], "countryCode": country}
    while True:
        now = datetime.now(timezone.utc)
        job = db.materializations.find_one_and_update({**key, "status": "ready"}, {"$set": {"lastUsedAt": now}})
        if job:
            return job["generationId"]
        generation = uuid.uuid4().hex
        try:
            # Only a failed job or one whose builder stopped renewing can be taken over. Anything else hits the unique key.
            previous = db.materializations.find_one_and_update(
                {**key, "$or": [{"status": "failed"}, {"status": "building", "leaseUntil": {"$lt": now}}]},
                {"$set": {"status": "building", "generationId": generation, "leaseUntil": now + LEASE, "startedAt": now}},
                upsert=True,
                return_document=ReturnDocument.BEFORE,
            )
        except DuplicateKeyError:
            time.sleep(POLL)
            continue
        if previous:
            db.country_product_years.delete_many({"generationId": previous["generationId"]})
        try:
            build(db, snapshot, country, generation)
        except Exception as exc:
            db.materializations.update_one(
                {**key, "generationId": generation},
                {"$set": {"status": "failed", "failure": str(exc)}, "$unset": {"leaseUntil": ""}},
            )
            db.country_product_years.delete_many({"generationId": generation})
            raise
        size = next(
            db.country_product_years.aggregate([
                {"$match": {"generationId": generation}},
                {"$group": {"_id": None, "bytes": {"$sum": {"$bsonSize": "$$ROOT"}}}},
            ]),
            {"bytes": 0},
        )["bytes"]
        # A builder whose lease was taken over while it ran must not overwrite the newer job.
        done = db.materializations.update_one(
            {**key, "generationId": generation, "status": "building"},
            {"$set": {"status": "ready", "bytes": size, "lastUsedAt": now}, "$unset": {"leaseUntil": ""}},
        )
        if not done.modified_count:
            db.country_product_years.delete_many({"generationId": generation})
            continue
        evict(db, budget, keep=generation)
        return generation


def evict(db, budget, keep):
    """Drop the least recently used generations beyond the budget, never the one just built.

    ponytail: a request that read a job just before its eviction sees an empty
    generation once, and the next request rebuilds. Add a reader count if that
    ever shows up in practice.
    """
    used = 0
    for job in db.materializations.find({"status": "ready"}, sort=[("lastUsedAt", -1)]):
        used += job.get("bytes", 0)
        if used > budget and job["generationId"] != keep:
            db.materializations.delete_one({"_id": job["_id"], "generationId": job["generationId"]})
            db.country_product_years.delete_many({"generationId": job["generationId"]})


def parquet(path):
    return sorted(p.as_posix() for p in path.glob("*/*.parquet"))


def build(db, snapshot, country, generation):
    root = DATA / snapshot["storage"]["path"]
    flow_files = parquet(root / "flows" / f"importer={country}")
    export_files = parquet(root / "exports" / f"country={country}")
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
    exported = {(product, year): (value, quantity_value, tonnes) for year, product, value, quantity_value, tonnes in exports}
    keys = suppliers.keys() | exported.keys()
    codes = sorted({product for product, _ in keys})
    descriptions = {
        p["productCode"]: p["description"]
        for p in db.products.find({"snapshotId": snapshot["_id"], "productCode": {"$in": codes}})
    }
    worlds = {
        (w["productCode"], w["year"]): w
        for w in db.world_product_years.find({"snapshotId": snapshot["_id"], "productCode": {"$in": codes}})
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
        docs.append(doc)
    if docs:
        db.country_product_years.insert_many(docs, ordered=False)


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
