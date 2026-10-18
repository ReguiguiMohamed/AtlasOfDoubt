import random
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128

from atlas.db import DecimalCodec


def test_decimal_codec_matches_pymongo_bit_for_bit():
    codec = DecimalCodec()
    rng = random.Random(7)
    values = [Decimal(rng.randrange(-10**34 + 1, 10**34)).scaleb(rng.randrange(-60, 40)) for _ in range(5000)]
    values += [Decimal(rng.randrange(10**12)) / 1000 for _ in range(5000)]
    values += [Decimal(s) for s in ("0", "-0", "0.000", "1E+6111", "1E-6176", "9" * 34, "-" + "9" * 34 + "E-12")]
    values += [Decimal(s) for s in ("NaN", "-Infinity", "1" * 40, "1E-7000")]
    for value in values:
        try:
            reference = Decimal128(value)
        except Exception as exc:
            with pytest.raises(type(exc)):
                codec.transform_python(value)
            continue
        encoded = codec.transform_python(value)
        assert encoded.bid == reference.bid, value
        decoded = codec.transform_bson(encoded)
        expected = encoded.to_decimal()
        assert str(decoded) == str(expected), value
