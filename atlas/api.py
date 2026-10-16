"""HTTP API over one or more imported snapshots.

    uvicorn atlas.api:app

Every request names its snapshot, and every figure in a response is computed
here from stored supplier values. Numbers sent by the browser are never used.
"""

import csv
import io
import re
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

from atlas import metrics
from atlas.db import connect

CODE_PATTERN = r"^\d{2}(\d{2}){0,2}$"


@asynccontextmanager
async def lifespan(app):
    client, app.state.db = connect()
    yield
    client.close()


app = FastAPI(title="AtlasOfDoubt", lifespan=lifespan)
# The overview sends every imported product at once, about 2 MB of JSON for a real year.
app.add_middleware(GZipMiddleware)


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


LIMITATIONS = [
    "Values are nominal current US dollars as published in BACI, with no inflation adjustment.",
    "The affected value is historical import value exposed under this scenario. It is not a forecast of losses.",
    "No replacement by other suppliers and no price response are assumed.",
    "A missing flow means BACI recorded no positive flow. It is not a confirmed zero.",
    "Tonnes are never added across different products.",
]


class ScenarioSpec(BaseModel):
    snapshot: str
    year: int
    mode: Literal["product", "country"]
    productCode: str | None = Field(None, pattern=CODE_PATTERN)
    suppliers: list[int] = Field(min_length=1)
    reduction: Decimal = Field(ge=0, le=1)


class ReportRequest(ScenarioSpec):
    title: str = Field(min_length=1, max_length=200)


def run_scenario(db, snapshot, spec):
    checked_year(snapshot, spec.year)
    names = {c["countryCode"]: c["countryName"] for c in snapshot["countries"]}
    unknown = set(spec.suppliers) - names.keys()
    if unknown:
        raise HTTPException(422, f"unknown country codes {sorted(unknown)}")
    if spec.mode == "product":
        if spec.productCode is None:
            raise HTTPException(422, "product mode needs a productCode")
        products = group_products(db, spec.snapshot, spec.productCode)
        suppliers = combined_suppliers(spec.productCode, product_years(db, spec.snapshot, spec.productCode, spec.year))
        return {
            "description": products[0]["description"] if len(spec.productCode) == 6 else f"{len(products)} products",
            **metrics.scenario(suppliers, spec.suppliers, spec.reduction),
        }

    selected = set(spec.suppliers)
    rows, total_imports, supplier_totals = [], metrics.ZERO, dict.fromkeys(selected, metrics.ZERO)
    docs = db.product_years.find(
        {"snapshotId": spec.snapshot, "year": spec.year}, {"_id": 0, "productCode": 1, "description": 1, "suppliers": 1}
    )
    for doc in docs:
        total_imports += metrics.total(doc["suppliers"])
        hit = [s for s in doc["suppliers"] if s["countryCode"] in selected]
        if not hit:
            continue
        for s in hit:
            supplier_totals[s["countryCode"]] += s["valueUsd"]
        result = metrics.scenario(doc["suppliers"], selected, spec.reduction)
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
    result = run_scenario(db, ready_snapshot(db, spec.snapshot), spec)
    return {"spec": spec.model_dump(), "calculationVersion": metrics.CALCULATION_VERSION, "result": result}


@app.post("/api/reports", status_code=201)
def create_report(db: Db, request: ReportRequest):
    snapshot = ready_snapshot(db, request.snapshot)
    result = run_scenario(db, snapshot, request)
    report = {
        "title": request.title,
        "createdAt": datetime.now(timezone.utc),
        "spec": request.model_dump(exclude={"title"}),
        "snapshot": {"id": snapshot["_id"], "source": snapshot["source"], "archive": snapshot["archive"]},
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
def list_reports(db: Db):
    reports = db.reports.find({}, {"title": 1, "createdAt": 1, "spec": 1}).sort("createdAt", -1)
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
