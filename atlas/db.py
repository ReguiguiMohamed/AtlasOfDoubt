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
    db.product_years.create_index([("snapshotId", 1), ("productCode", 1), ("year", 1)], unique=True)
    db.product_years.create_index([("snapshotId", 1), ("year", 1)])
    db.product_years.create_index([("snapshotId", 1), ("suppliers.countryCode", 1), ("year", 1)])
    db.products.create_index([("snapshotId", 1), ("productCode", 1)], unique=True)
    db.reports.create_index([("createdAt", -1)])
    return client, db
