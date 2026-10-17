"""Concentration, disruption and export arithmetic.

Every number the API returns or a report stores comes from these functions,
so live results and saved reports follow one set of rules. A supplier is a
dict with at least countryCode, countryName and valueUsd (a Decimal).
"""

from decimal import Decimal

CALCULATION_VERSION = "2"

ZERO = Decimal(0)


PARTIAL_QUANTITIES = Decimal("0.5")
TINY_TONNES = Decimal(1)
UNIT_VALUE_RANGE = (Decimal("0.1"), Decimal(10))


def total(suppliers):
    return sum((s["valueUsd"] for s in suppliers), ZERO)


def with_shares(suppliers):
    """Suppliers ranked by value, each with its share of the total.

    The share is None when the total is zero, because a share of nothing is
    undefined rather than zero.
    """
    value = total(suppliers)
    ranked = sorted(suppliers, key=lambda s: s["valueUsd"], reverse=True)
    return [{**s, "share": s["valueUsd"] / value if value else None} for s in ranked]


def summarize(suppliers):
    """Total, leading supplier, top-three share and unnormalised HHI (0 to 1)."""
    ranked = with_shares(suppliers)
    if not ranked or ranked[0]["share"] is None:
        return {
            "totalUsd": total(suppliers),
            "supplierCount": len(suppliers),
            "topSupplier": None,
            "top3Share": None,
            "hhi": None,
        }
    top = ranked[0]
    return {
        "totalUsd": total(suppliers),
        "supplierCount": len(suppliers),
        "topSupplier": {
            "countryCode": top["countryCode"],
            "countryName": top["countryName"],
            "share": top["share"],
        },
        "top3Share": sum((s["share"] for s in ranked[:3]), ZERO),
        "hhi": sum((s["share"] * s["share"] for s in ranked), ZERO),
    }


def merge(supplier_lists):
    """Sum each supplier's value across several products.

    Group shares and HHI must come from this merged list. Averaging the HHI of
    each product would weight a tiny product like a large one. Tonnes are
    dropped because adding tonnes of different goods means nothing.
    """
    merged = {}
    for suppliers in supplier_lists:
        for s in suppliers:
            entry = merged.setdefault(
                s["countryCode"],
                {
                    "countryCode": s["countryCode"],
                    "countryName": s["countryName"],
                    "isoCode": s.get("isoCode"),
                    "valueUsd": ZERO,
                },
            )
            entry["valueUsd"] += s["valueUsd"]
    return list(merged.values())


def scenario(suppliers, selected, reduction):
    """Cut the selected suppliers by `reduction` (0 to 1), leave the rest unchanged.

    No replacement and no price response are assumed. The affected value is
    historical import value exposed under the scenario, not a forecast.
    """
    if not ZERO <= reduction <= 1:
        raise ValueError("reduction must be between 0 and 1")
    selected = set(selected)
    remaining = [
        {**s, "valueUsd": s["valueUsd"] * (1 - reduction)} if s["countryCode"] in selected else s
        for s in suppliers
    ]
    baseline = total(suppliers)
    affected = reduction * total(s for s in suppliers if s["countryCode"] in selected)
    after = {s["countryCode"]: s for s in with_shares(remaining)}
    return {
        "baseline": summarize(suppliers),
        "affectedUsd": affected,
        "exposureShare": affected / baseline if baseline else None,
        "remainingUsd": baseline - affected,
        "remaining": summarize(remaining),
        "suppliers": [
            {
                "countryCode": s["countryCode"],
                "countryName": s["countryName"],
                "isoCode": s.get("isoCode"),
                "selected": s["countryCode"] in selected,
                "baselineUsd": s["valueUsd"],
                "baselineShare": s["share"],
                "remainingUsd": after[s["countryCode"]]["valueUsd"],
                "remainingShare": after[s["countryCode"]]["share"],
            }
            for s in with_shares(suppliers)
        ],
    }


def hhi(values):
    """Sum of squared shares, None when the values add to zero."""
    values = list(values)
    whole = sum(values, ZERO)
    return sum(((v / whole) ** 2 for v in values), ZERO) if whole else None


def excluded_hhi(total_usd, sum_squares, value):
    """World exporter HHI with one country taken out, from the world totals alone."""
    rest = total_usd - value
    return (sum_squares - value * value) / (rest * rest) if rest else None


def rca(x_ck, x_c, x_k, x):
    """Balassa revealed comparative advantage, (X_ck/X_c)/(X_k/X)."""
    if not (x_c and x_k and x):
        return None
    return (x_ck / x_c) / (x_k / x)


def unit_value(value, tonnes):
    """USD per tonne over the flows that report a quantity."""
    return value / tonnes if tonnes else None


def prody(baskets, gdp):
    """PRODY per product among exporters with GDP, as {product: income}.

    Each exporter weighs by the share the product takes in its own basket,
    relative to the other covered exporters, so a small rich exporter can
    still mark a product as rich-country.
    """
    weights, incomes = {}, {}
    for country, basket in baskets.items():
        whole = sum(basket.values(), ZERO)
        if country not in gdp or not whole:
            continue
        for product, value in basket.items():
            share = value / whole
            weights[product] = weights.get(product, ZERO) + share
            incomes[product] = incomes.get(product, ZERO) + share * gdp[country]
    return {k: incomes[k] / weights[k] for k in weights if weights[k]}


def expy(basket, prody_by_product):
    """Export sophistication of one basket.

    The value is None when any product lacks a PRODY, because dropping it
    would raise or lower the index without saying so. The covered basket
    result and its coverage are kept beside it.
    """
    whole = sum(basket.values(), ZERO)
    if not whole:
        return None
    covered = {k: v for k, v in basket.items() if k in prody_by_product}
    covered_total = sum(covered.values(), ZERO)
    weighted = sum((v * prody_by_product[k] for k, v in covered.items()), ZERO)
    return {
        "value": weighted / whole if len(covered) == len(basket) else None,
        "coverage": covered_total / whole,
        "coveredBasket": weighted / covered_total if covered_total else None,
    }


def quality_flags(coverage, tonnes, unit_value_usd, world_unit_value):
    """Warnings that make an export unit value unsafe to read as a price."""
    flags = []
    if coverage is not None and coverage < PARTIAL_QUANTITIES:
        flags.append("partial quantities")
    if tonnes is not None and tonnes < TINY_TONNES:
        flags.append("tiny quantity")
    if unit_value_usd is not None and world_unit_value:
        low, high = UNIT_VALUE_RANGE
        if not low <= unit_value_usd / world_unit_value <= high:
            flags.append("extreme unit value")
    return flags
