from decimal import Decimal

import pytest

from atlas.metrics import disruption, merge, summarize, with_shares


def supplier(code, value):
    return {"countryCode": code, "countryName": f"C{code}", "valueUsd": Decimal(value)}


ABC = [supplier(1, 60_000_000), supplier(2, 30_000_000), supplier(3, 10_000_000)]


def test_blueprint_example():
    result = disruption(ABC, {1: "embargo"}, Decimal("0.5"))
    assert result["affectedUsd"] == result["strandedUsd"] == result["gapUsd"] == Decimal(30_000_000)
    assert result["reroutedUsd"] == result["replacedUsd"] == 0
    assert result["exposureShare"] == Decimal("0.3")
    assert result["remainingHhi"] == 2 * (Decimal(3) / 7) ** 2 + (Decimal(1) / 7) ** 2


def test_a_rerouted_supplier_arrives_late_and_is_never_lost():
    result = disruption(ABC, {1: "rerouted", 3: "cutOff"}, Decimal(1))
    assert (result["affectedUsd"], result["reroutedUsd"], result["strandedUsd"]) == (70_000_000, 60_000_000, 10_000_000)
    assert abs(result["remainingHhi"] - Decimal(5) / 9) < Decimal("1e-20")


@pytest.mark.parametrize(("headroom", "replaced"), [(20_000_000, 20_000_000), (90_000_000, 60_000_000)])
def test_untouched_exporters_replace_up_to_their_headroom(headroom, replaced):
    result = disruption(ABC, {1: "embargo"}, Decimal(1), Decimal(headroom))
    assert result["replacedUsd"] == replaced
    assert result["gapUsd"] == 60_000_000 - replaced


def test_a_short_shock_scales_values_but_not_shares():
    result = disruption(ABC, {1: "embargo"}, Decimal(1), Decimal(20_000_000), Decimal("0.25"))
    assert (result["totalUsd"], result["affectedUsd"], result["gapUsd"]) == (25_000_000, 15_000_000, 10_000_000)
    assert result["exposureShare"] == Decimal("0.6")


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
    result = disruption(ABC, {1: "embargo", 2: "region"}, Decimal(0))
    assert result["affectedUsd"] == 0
    assert result["remainingHhi"] == result["baselineHhi"]


def test_full_disruption_of_all_suppliers():
    result = disruption(ABC, {1: "embargo", 2: "embargo", 3: "region"}, Decimal(1))
    assert result["exposureShare"] == 1
    assert result["remainingHhi"] is None


def test_absent_supplier_affects_nothing():
    assert disruption(ABC, {99: "embargo"}, Decimal("0.5"))["affectedUsd"] == 0


def test_disruption_of_an_empty_product():
    result = disruption([], {1: "embargo"}, Decimal(1))
    assert result["affectedUsd"] == 0
    assert result["exposureShare"] is None


@pytest.mark.parametrize("severity", [Decimal("-0.1"), Decimal("1.01")])
def test_severity_outside_range_is_rejected(severity):
    with pytest.raises(ValueError):
        disruption(ABC, {1: "embargo"}, severity)


def test_group_recomputes_shares_from_summed_values():
    wheat = [supplier(1, 90), supplier(2, 10)]
    barley = [supplier(2, 900)]
    group = summarize(merge([wheat, barley]))
    assert group["topSupplier"] == {"countryCode": 2, "countryName": "C2", "share": Decimal("0.91")}
    assert group["hhi"] == Decimal("0.91") ** 2 + Decimal("0.09") ** 2
    averaged = (summarize(wheat)["hhi"] + summarize(barley)["hhi"]) / 2
    assert group["hhi"] != averaged
