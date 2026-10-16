from decimal import Decimal

import pytest

from atlas.metrics import merge, scenario, summarize, with_shares


def supplier(code, value):
    return {"countryCode": code, "countryName": f"C{code}", "valueUsd": Decimal(value)}


ABC = [supplier(1, 60_000_000), supplier(2, 30_000_000), supplier(3, 10_000_000)]


def test_blueprint_example():
    result = scenario(ABC, [1], Decimal("0.5"))
    assert result["affectedUsd"] == Decimal(30_000_000)
    assert result["exposureShare"] == Decimal("0.3")
    assert result["remainingUsd"] == Decimal(70_000_000)
    assert result["remaining"]["topSupplier"]["share"] == Decimal(30) / Decimal(70)


def test_baseline_measures():
    metrics = summarize(ABC)
    assert metrics["totalUsd"] == Decimal(100_000_000)
    assert metrics["topSupplier"]["countryCode"] == 1
    assert metrics["topSupplier"]["share"] == Decimal("0.6")
    assert metrics["top3Share"] == 1
    assert metrics["hhi"] == Decimal("0.46")


def test_shares_sum_to_one():
    suppliers = [supplier(i, v) for i, v in enumerate(["1.001", "333.333", "7", "0.002"])]
    assert abs(sum(s["share"] for s in with_shares(suppliers)) - 1) < Decimal("1e-20")


def test_single_supplier_hhi_is_one():
    assert summarize([supplier(1, 5)])["hhi"] == 1


@pytest.mark.parametrize("n", [2, 3, 7])
def test_equal_suppliers_hhi_is_one_over_n(n):
    hhi = summarize([supplier(i, 10) for i in range(n)])["hhi"]
    assert abs(hhi - Decimal(1) / n) < Decimal("1e-20")


def test_no_recorded_imports_gives_unavailable_measures():
    metrics = summarize([])
    assert metrics["totalUsd"] == 0
    assert metrics["topSupplier"] is metrics["top3Share"] is metrics["hhi"] is None


def test_zero_percent_disruption_changes_nothing():
    result = scenario(ABC, [1, 2], Decimal(0))
    assert result["affectedUsd"] == 0
    assert result["remaining"] == result["baseline"]


def test_full_disruption_of_all_suppliers():
    result = scenario(ABC, [1, 2, 3], Decimal(1))
    assert result["exposureShare"] == 1
    assert result["remainingUsd"] == 0
    assert result["remaining"]["hhi"] is None
    assert all(s["share"] is None for s in result["remainingSuppliers"])


def test_absent_supplier_affects_nothing():
    assert scenario(ABC, [99], Decimal("0.5"))["affectedUsd"] == 0


def test_scenario_on_empty_product():
    result = scenario([], [1], Decimal(1))
    assert result["affectedUsd"] == 0
    assert result["exposureShare"] is None


@pytest.mark.parametrize("reduction", [Decimal("-0.1"), Decimal("1.01")])
def test_reduction_outside_range_is_rejected(reduction):
    with pytest.raises(ValueError):
        scenario(ABC, [1], reduction)


def test_group_recomputes_shares_from_summed_values():
    wheat = [supplier(1, 90), supplier(2, 10)]
    barley = [supplier(2, 900)]
    group = summarize(merge([wheat, barley]))
    assert group["topSupplier"] == {"countryCode": 2, "countryName": "C2", "share": Decimal("0.91")}
    assert group["hhi"] == Decimal("0.91") ** 2 + Decimal("0.09") ** 2
    averaged = (summarize(wheat)["hhi"] + summarize(barley)["hhi"]) / 2
    assert group["hhi"] != averaged
