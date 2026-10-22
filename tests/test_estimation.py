import pytest

from food_planner.services.estimation import (Assumptions, estimate_event, parse_assumptions,
                                              expected_leftover_servings, RISK_LEVELS)

RICE = dict(name="Rice", dietary_category="vegetarian", portion_g=150, rate_pct=90, cost_per_kg=80, food_category="Rice")
CHICKEN = dict(name="Chicken", dietary_category="non_vegetarian", portion_g=120, rate_pct=80, cost_per_kg=None, food_category="Curry")


def run(guests=200, regs=180, dishes=(RICE, CHICKEN), **a):
    return estimate_event(guests, regs, Assumptions(**a), [dict(d) for d in dishes])


def test_attendance_uses_no_show_only_for_mean():
    r = run(no_show_rate_pct=10, confidence_pct=100)
    assert r["attendance"]["estimated_attendance"] == pytest.approx(180)
    low_conf = run(no_show_rate_pct=10, confidence_pct=20)
    assert low_conf["attendance"]["estimated_attendance"] == pytest.approx(180)  # mean unchanged
    assert low_conf["attendance"]["attendance_sd"] > r["attendance"]["attendance_sd"]


def test_servings_weight_and_cost():
    r = run(shortage_risk_pct=10)
    rice = r["dishes"][0]
    assert rice["expected_servings"] == pytest.approx(180 * 0.9)
    assert rice["recommended_servings"] >= rice["expected_servings"]
    assert rice["recommended_kg"] == pytest.approx(rice["recommended_servings"] * 150 / 1000, abs=1e-3)
    assert rice["food_cost"] == pytest.approx(rice["recommended_kg"] * 80, abs=0.01)
    assert r["dishes"][1]["food_cost"] is None and r["dishes"][1]["surplus_cost"] is None


def test_nonveg_dish_uses_only_nonveg_guests():
    r = run(veg_percent=40, confidence_pct=100)
    chicken = r["dishes"][1]
    assert chicken["eligible_guests"] == pytest.approx(180 * 0.6)
    assert chicken["expected_servings"] == pytest.approx(180 * 0.6 * 0.8)


def test_lower_risk_means_more_food_and_more_leftover():
    low, high = run(shortage_risk_pct=2), run(shortage_risk_pct=30)
    assert low["totals"]["recommended_kg"] > high["totals"]["recommended_kg"]
    assert low["totals"]["expected_leftover_kg"] > high["totals"]["expected_leftover_kg"]
    assert low["dishes"][0]["modelled_shortage_pct"] < high["dishes"][0]["modelled_shortage_pct"]


def test_curve_is_monotonic_and_marks_selected():
    r = run(shortage_risk_pct=10)
    kgs = [c["recommended_kg"] for c in r["curve"]]
    assert kgs == sorted(kgs, reverse=True)
    assert [c["risk_pct"] for c in r["curve"] if c["selected"]] == [10]
    assert len(r["curve"]) == len(RISK_LEVELS)


def test_curve_selected_point_matches_main_result():
    r = run(shortage_risk_pct=15)
    sel = [c for c in r["curve"] if c["selected"]][0]
    assert sel["recommended_kg"] == r["totals"]["recommended_kg"]
    assert sel["expected_leftover_kg"] == r["totals"]["expected_leftover_kg"]


def test_portion_adjust_and_buffer():
    base = run()["totals"]["recommended_kg"]
    assert run(portion_adjust_pct=20)["totals"]["recommended_kg"] == pytest.approx(base * 1.2, rel=0.01)
    assert run(safety_buffer_pct=20)["totals"]["recommended_kg"] > base


def test_leftover_is_non_negative_and_matches_formula_edges():
    assert expected_leftover_servings(100, 100, 0) == 0
    assert expected_leftover_servings(120, 100, 0) == 20
    assert expected_leftover_servings(100, 100, 10) > 0
    assert expected_leftover_servings(1000, 100, 10) == pytest.approx(900, rel=1e-3)


def test_zero_rate_and_no_dishes():
    zero = dict(RICE, rate_pct=0)
    r = run(dishes=[zero])
    assert r["dishes"][0]["recommended_servings"] == 0 and r["dishes"][0]["recommended_kg"] == 0
    empty = run(dishes=[])
    assert empty["totals"]["recommended_kg"] == 0 and any("No dishes" in w for w in empty["warnings"])


def test_warning_when_registrations_exceed_expected():
    assert any("exceed" in w for w in run(guests=100, regs=150)["warnings"])


def test_cost_totals_only_priced_dishes():
    t = run()["totals"]
    assert t["cost_dishes"] == 1 and t["cost_complete"] is False


@pytest.mark.parametrize("key,bad", [("shortage_risk_pct", 0), ("shortage_risk_pct", 90), ("no_show_rate_pct", -1),
                                     ("no_show_rate_pct", 95), ("safety_buffer_pct", 60), ("confidence_pct", 101),
                                     ("portion_adjust_pct", -50), ("shortage_risk_pct", "abc"), ("veg_percent", "nan")])
def test_invalid_assumptions_rejected(key, bad):
    _, errors = parse_assumptions({key: bad})
    assert key in errors


def test_valid_assumptions_parse():
    a, errors = parse_assumptions({"shortage_risk_pct": "7", "no_show_rate_pct": "12.5"})
    assert not errors and a.shortage_risk_pct == 7 and a.no_show_rate_pct == 12.5
