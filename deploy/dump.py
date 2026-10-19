"""Dump one snapshot's MongoDB documents in the layout mongorestore reads, so a server can load them.

    python -m deploy.dump BACI_HS12_V202601@537b2fe453e3
"""

import gzip
import sys

from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument

from atlas.db import connect
from atlas.prepare import DATA

BY_SNAPSHOT = ("products", "world_product_years", "country_years", "geo_pairs", "tariffs", "preferences", "materializations")


def queries(db, snapshot_id):
    yield "snapshots", {"_id": snapshot_id}
    for name in BY_SNAPSHOT:
        yield name, {"snapshotId": snapshot_id}
    ready = db.materializations.distinct("generationId", {"snapshotId": snapshot_id, "status": "ready"})
    yield "country_product_years", {"generationId": {"$in": ready}}


def dump(snapshot_id):
    client, db = connect()
    out = DATA / "mongo-dump" / db.name
    out.mkdir(parents=True, exist_ok=True)
    # Raw documents skip a decode and encode round trip on 4.7 million rows.
    raw = db.with_options(codec_options=CodecOptions(document_class=RawBSONDocument))
    for name, query in queries(raw, snapshot_id):
        with gzip.open(out / f"{name}.bson.gz", "wb") as f:
            for doc in raw[name].find(query):
                f.write(doc.raw)
    client.close()


if __name__ == "__main__":
    dump(sys.argv[1])
