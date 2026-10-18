"""MongoDB connection with Decimal stored as Decimal128.

Values and shares stay Decimal end to end, so a sum read back from the
database equals the sum that was written.
"""

import os
import struct
from decimal import Decimal

from bson.codec_options import CodecOptions, TypeCodec, TypeRegistry
from bson.decimal128 import Decimal128, create_decimal128_context
from pymongo import MongoClient

BID = struct.Struct("<QQ")
CONTEXT = create_decimal128_context()
BIAS = 6176
LOW = (1 << 64) - 1
SIGN = 1 << 63
SPECIAL = 3 << 61
MAX_SIGNIFICAND = 10**34 - 1


class DecimalCodec(TypeCodec):
    """pymongo's own conversion loops over bits in Python and took most of a first visit.

    Finite values of up to 34 digits are packed with integer arithmetic here,
    bit for bit the same as pymongo's, and anything else goes through pymongo.
    """

    python_type = Decimal
    bson_type = Decimal128

    def transform_python(self, value):
        sign, digits, exponent = value.as_tuple()
        if isinstance(exponent, str) or len(digits) > 34 or not -BIAS <= exponent <= 6111:
            return Decimal128(value)
        significand = int(value.copy_abs().scaleb(-exponent, CONTEXT))
        high = (significand >> 64) | ((exponent + BIAS) << 49) | (SIGN if sign else 0)
        return Decimal128((high, significand & LOW))

    def transform_bson(self, value):
        low, high = BID.unpack(value.bid)
        significand = ((high & 0x1FFFFFFFFFFFF) << 64) | low
        exponent = ((high >> 49) & 0x3FFF) - BIAS
        if high & SPECIAL == SPECIAL or significand > MAX_SIGNIFICAND or exponent > 6111:
            return value.to_decimal()
        sign = "-" if high & SIGN else ""
        return Decimal(f"{sign}{significand}E{exponent}")


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
    db.preferences.create_index([("snapshotId", 1), ("productCode", 1), ("schedule", 1), ("partner", 1)], unique=True)
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
