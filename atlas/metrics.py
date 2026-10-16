"""Supplier concentration and disruption arithmetic.

Every number the API returns or a report stores comes from these functions,
so live results and saved reports follow one set of rules. A supplier is a
dict with at least countryCode, countryName and valueUsd (a Decimal).
"""

from decimal import Decimal

CALCULATION_VERSION = "1"

ZERO = Decimal(0)


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
