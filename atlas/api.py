"""HTTP API over one or more imported snapshots.

    uvicorn atlas.api:app

Every request names its snapshot, and every figure in a response is computed
here from stored supplier values. Numbers sent by the browser are never used.
"""

import re
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from pymongo.database import Database

from atlas import metrics
from atlas.db import connect

CODE_PATTERN = r"^\d{2}(\d{2}){0,2}$"


@asynccontextmanager
async def lifespan(app):
    client, app.state.db = connect()
    yield
    client.close()


app = FastAPI(title="AtlasOfDoubt", lifespan=lifespan)


def database(request: Request):
    return request.app.state.db


Db = Annotated[Database, Depends(database)]
SnapshotId = Annotated[str, Query(alias="snapshot")]
Code = Annotated[str, Path(pattern=CODE_PATTERN)]


def ready_snapshot(db, snapshot_id):
    snapshot = db.snapshots.find_one({"_id": snapshot_id, "status": "ready"})
    if not snapshot:
        raise HTTPException(404, f"no ready snapshot {snapshot_id}")
    return snapshot


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


def product_years(db, snapshot_id, code, year=None):
    query = {"snapshotId": snapshot_id, "productCode": {"$regex": f"^{code}"}}
    if year is not None:
        query["year"] = year
    return list(db.product_years.find(query, {"_id": 0}))


def combined_suppliers(code, docs):
    """Stored suppliers of one product, or a group's suppliers summed across products."""
    if len(code) == 6:
        return docs[0]["suppliers"] if docs else []
    return metrics.merge(d["suppliers"] for d in docs)


@app.get("/api/snapshots")
def list_snapshots(db: Db):
    return list(db.snapshots.find({"status": "ready"}, {"countries": 0, "errors.samples": 0}).sort("_id", -1))


@app.get("/api/snapshots/{snapshot_id}")
def get_snapshot(db: Db, snapshot_id: str):
    return ready_snapshot(db, snapshot_id)


@app.get("/api/products")
def search_products(db: Db, snapshot_id: SnapshotId, q: str = ""):
    ready_snapshot(db, snapshot_id)
    q = q.strip()
    query = {"snapshotId": snapshot_id}
    if q.isdigit():
        query["productCode"] = {"$regex": f"^{q}"}
    elif q:
        query["description"] = {"$regex": re.escape(q), "$options": "i"}
    return list(db.products.find(query, {"_id": 0, "snapshotId": 0}).sort("productCode").limit(50))


@app.get("/api/overview")
def overview(db: Db, snapshot_id: SnapshotId, year: int | None = None, min_value: Annotated[int, Query(alias="minValue", ge=0)] = 0):
    year = checked_year(ready_snapshot(db, snapshot_id), year)
    rows = db.product_years.find(
        {"snapshotId": snapshot_id, "year": year, "metrics.totalUsd": {"$gte": min_value}},
        {"_id": 0, "productCode": 1, "description": 1, "metrics": 1, "world.hhi": 1, "world.totalUsd": 1, "world.topSupplier": 1},
    ).sort("metrics.totalUsd", -1)
    return {"snapshot": snapshot_id, "year": year, "rows": list(rows)}


@app.get("/api/products/{code}/history")
def history(db: Db, code: Code, snapshot_id: SnapshotId):
    snapshot = ready_snapshot(db, snapshot_id)
    products = group_products(db, snapshot_id, code)
    by_year = {}
    for doc in product_years(db, snapshot_id, code):
        by_year.setdefault(doc["year"], []).append(doc)
    years = []
    for year in snapshot["years"]:
        docs = by_year.get(year)
        if not docs:
            years.append({"year": year, "metrics": None, "suppliers": [], "world": None})
            continue
        suppliers = combined_suppliers(code, docs)
        years.append({
            "year": year,
            "metrics": metrics.summarize(suppliers),
            "suppliers": metrics.with_shares(suppliers),
            "world": docs[0]["world"] if len(code) == 6 else None,
        })
    return {"snapshot": snapshot_id, "code": code, "products": products, "years": years}
