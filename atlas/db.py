"""MongoDB connection with Decimal stored as Decimal128.

Values and shares stay Decimal end to end, so a sum read back from the
database equals the sum that was written.
"""

import os
from decimal import Decimal

from bson.codec_options import CodecOptions, TypeCodec, TypeRegistry
from bson.decimal128 import Decimal128
from pymongo import MongoClient


class DecimalCodec(TypeCodec):
    python_type = Decimal
    bson_type = Decimal128

    def transform_python(self, value):
        return Decimal128(value)

    def transform_bson(self, value):
        return value.to_decimal()


CODEC_OPTIONS = CodecOptions(type_registry=TypeRegistry([DecimalCodec()]), tz_aware=True)


def connect():
    client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    db = client.get_database(os.environ.get("ATLAS_DB", "atlas"), codec_options=CODEC_OPTIONS)
    db.products.create_index([("snapshotId", 1), ("productCode", 1)], unique=True)
    db.products.create_index([("snapshotId", 1), ("description", "text")])
    db.world_product_years.create_index([("snapshotId", 1), ("productCode", 1), ("year", 1)], unique=True)
    db.country_years.create_index([("snapshotId", 1), ("countryCode", 1), ("year", 1)], unique=True)
    db.geo_pairs.create_index([("snapshotId", 1), ("countryCode", 1), ("partnerCode", 1)], unique=True)
    db.tariffs.create_index([("snapshotId", 1), ("productCode", 1), ("schedule", 1)], unique=True)
    db.materializations.create_index([("snapshotId", 1), ("countryCode", 1)], unique=True)
    cache = db.country_product_years
    cache.create_index([("generationId", 1), ("productCode", 1), ("year", 1)], unique=True)
    cache.create_index([("generationId", 1), ("year", 1), ("imports.metrics.totalUsd", -1), ("productCode", 1)])
    cache.create_index([("generationId", 1), ("year", 1), ("exports.totalUsd", -1), ("productCode", 1)])
    cache.create_index([("generationId", 1), ("imports.suppliers.countryCode", 1), ("year", 1)])
    db.reports.create_index([("reporter.countryCode", 1), ("createdAt", -1)])
    # Snapshots and reports from before any country could be chosen were all Tunisia's and carry no Parquet copy.
    db.snapshots.update_many({"status": "ready", "storage": {"$exists": False}}, {"$set": {"status": "legacy"}})
    db.reports.update_many(
        {"reporter": {"$exists": False}},
        {"$set": {"reporter": {"countryCode": 788, "countryName": "Tunisia", "isoCode": "TUN"}}},
    )
    return client, db
