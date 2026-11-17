"""Tests for SubterraX: every number checked against the model."""
import math

import pytest

import main as m


# ---- TBM boring model (labelled planning rates)
def test_advance_granite():
    assert abs(m.advance_m_per_day("granite") - 12.6) < 1e-9


def test_advance_all_rocks():
    assert abs(m.advance_m_per_day("basalt") - 18.0576) < 1e-6
    assert abs(m.advance_m_per_day("sandstone") - 34.992) < 1e-6
    assert abs(m.advance_m_per_day("clay") - 30.24) < 1e-9
    assert abs(m.advance_m_per_day("mixed_face") - 5.76) < 1e-9


def test_advance_hour_formula():
    assert abs(m.advance_m_per_hour("granite") - 1.5) < 1e-12
    r = m.ROCKS["basalt"]
    assert abs(m.advance_m_per_hour("basalt")
               - r["pen_mm_rev"] / 1000.0 * r["rpm"] * 60.0) < 1e-12


def test_mixed_face_slowest():
    rates = {rock: m.advance_m_per_day(rock) for rock in m.ROCKS}
    assert min(rates, key=rates.get) == "mixed_face"


def test_schedule_granite_10km():
    s = m.boring_schedule("granite", 10000.0)
    assert abs(s["days"] - 793.6508) < 0.01
    assert abs(s["years"] - s["days"] / 365.25) < 1e-12


def test_schedule_scales_linearly():
    assert abs(m.boring_schedule("clay", 20000.0)["days"]
               - 2 * m.boring_schedule("clay", 10000.0)["days"]) < 1e-9


def test_unknown_rock_raises():
    with pytest.raises(ValueError):
        m.advance_m_per_day("unobtanium")
    with pytest.raises(ValueError):
        m.boring_schedule("granite", 0.0)


# ---- excavation & spoil
def test_bore_area():
    assert abs(m.bore_area_m2(10.0) - 78.5398) < 0.001
    assert abs(m.bore_area_m2(8.0) - math.pi * 16.0) < 1e-9


def test_excavation_granite_10km():
    ex = m.excavation("granite", 10000.0)
    assert abs(ex["volume_in_situ_m3"] - 785398.16) < 1.0
    assert abs(ex["spoil_mass_t"] - 2120575.04) < 1.0
    assert ex["truck_loads"] == 106029
    assert ex["train_loads"] == 2121


def test_excavation_bulking():
    ex = m.excavation("basalt", 5000.0)
    assert abs(ex["volume_bulked_m3"]
               - ex["volume_in_situ_m3"] * m.BULKING_FACTOR) < 1e-6


def test_excavation_density_orders_mass():
    assert (m.excavation("clay", 10000.0)["spoil_mass_t"]
            < m.excavation("granite", 10000.0)["spoil_mass_t"]
            < m.excavation("basalt", 10000.0)["spoil_mass_t"])


# ---- depth environment
def test_rock_temperature():
    assert m.rock_temperature_c(0.0) == 15.0
    assert abs(m.rock_temperature_c(1000.0) - 40.0) < 1e-9
    assert abs(m.rock_temperature_c(2000.0) - 65.0) < 1e-9
    assert abs(m.rock_temperature_c(2300.0) - 72.5) < 1e-9


def test_lithostatic_pressure():
    assert abs(m.lithostatic_pressure_mpa(1000.0) - 26.478) < 0.01
    assert abs(m.lithostatic_pressure_mpa(2300.0) - 60.90) < 0.05
    assert abs(m.lithostatic_pressure_mpa(2000.0)
               - 2 * m.lithostatic_pressure_mpa(1000.0)) < 1e-9


def test_cooling_and_airflow():
    assert m.cooling_load_kw(500.0) == 0.0
    assert abs(m.cooling_load_kw(2000.0) - 581.19) < 0.5
    assert abs(m.required_airflow_m3_s(2000.0) - 60.24) < 0.1
    assert m.required_airflow_m3_s(1500.0) < m.required_airflow_m3_s(2000.0)


def test_negative_depth_raises():
    with pytest.raises(ValueError):
        m.rock_temperature_c(-1.0)
    with pytest.raises(ValueError):
        m.lithostatic_pressure_mpa(-1.0)


# ---- labelled references
def test_real_tunnels_labelled():
    refs = m.real_tunnels()
    assert len(refs) == 3
    assert [t["length_km"] for t in refs] == [57.0, 50.5, 24.5]
    assert max(refs, key=lambda t: t["length_km"])["name"] == "Gotthard Base Tunnel"


# ---- routing (Dijkstra)
def test_edge_time_depth_penalty():
    assert abs(m.edge_time_min(4600.0, 1700.0) - 5.382) < 1e-9
    assert m.edge_time_min(1000.0, 2000.0) > m.edge_time_min(1000.0, 0.0)


def test_fastest_route_uses_express():
    fast = m.dijkstra("PORTAL_W", "PORTAL_E")
    assert fast["path"][-2] == "JUNCTION"
    assert abs(fast["time_min"] - 12.546) < 0.01
    assert abs(fast["distance_m"] - 11200.0) < 1e-9


def test_compliant_route_respects_egress():
    comp = m.dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=m.EGRESS_LIMIT_M)
    assert all(s["length_m"] <= m.EGRESS_LIMIT_M
               for s in m.route_segments(comp["path"]))
    assert abs(comp["time_min"] - 14.106) < 0.01
    assert abs(comp["distance_m"] - 12900.0) < 1e-9


def test_compliant_slower_than_fastest():
    fast = m.dijkstra("PORTAL_W", "PORTAL_E")
    comp = m.dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=m.EGRESS_LIMIT_M)
    assert comp["time_min"] > fast["time_min"]


def test_dijkstra_unknown_node_raises():
    with pytest.raises(ValueError):
        m.dijkstra("PORTAL_W", "NOWHERE")


def test_gamma_route_depth():
    deep = m.dijkstra("PORTAL_W", "STN_GAMMA")
    assert max(s["max_depth_m"] for s in m.route_segments(deep["path"])) == 2100.0


# ---- safety interlocks
def test_plan_book_verdicts():
    book = m.plan_book()
    assert book["north_link_compliant"]["accepted"] is True
    assert book["express_bore_fastest"]["violations"] == ["EGRESS_SPACING"]
    assert book["deep_gamma_no_cooling"]["violations"] == ["ROCK_TEMPERATURE"]
    assert book["wet_alpha_link_no_grout"]["violations"] == ["WATER_INGRESS"]


def test_ventilation_interlock():
    comp = m.dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=m.EGRESS_LIMIT_M)
    starved = m.check_plan(comp, vent_provided_m3_s=10.0, refrigeration=True)
    assert "VENTILATION_RATE" in starved["violations"]
    assert starved["accepted"] is False


def test_refrigeration_and_grouting_fix():
    deep = m.dijkstra("PORTAL_W", "STN_GAMMA")
    assert m.check_plan(deep, vent_provided_m3_s=200.0,
                        refrigeration=True)["accepted"] is True
    comp = m.dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=m.EGRESS_LIMIT_M)
    assert m.check_plan(comp, vent_provided_m3_s=80.0, refrigeration=True,
                        water_risk="high", grouting=True)["accepted"] is True


# ---- pod model
def test_blockage_ratio():
    assert abs(m.blockage_ratio() - 0.19140625) < 1e-12
    with pytest.raises(ValueError):
        m.blockage_ratio(9.0, 8.0)


def test_piston_pressure():
    assert 65.0 < m.piston_pressure_pa() < 75.0
    assert m.piston_pressure_pa(100.0) > m.piston_pressure_pa(80.0)


def test_pod_capacity():
    cap = m.pod_capacity()
    assert cap["pods_per_hour"] == 30.0
    assert cap["passengers_per_hour"] == 1200.0


# ---- classifier
def test_classifier_scenarios():
    rep = m.ground_report()
    assert rep["shallow_sandstone_dry"] == "favourable"
    assert rep["granite_1km_low_water"] == "difficult"
    assert rep["basalt_mid_depth"] == "difficult"
    assert rep["deep_granite_hot"] == "prohibitive"
    assert rep["mixed_face_deep_wet"] == "prohibitive"


def test_classifier_invalid_raises():
    with pytest.raises(ValueError):
        m.classify_ground(100.0, 1.0, 1.5)


# ---- gates + seats
def test_hold_gates_all_present():
    assert len(m.HOLD_GATES) == 14
    assert all(v.startswith("HOLD") for v in m.HOLD_GATES.values())


def test_claim_gates_hold():
    for action in ("blasting_guidance", "real_excavation_guidance",
                   "tbm_operation_live", "structural_certification_claim",
                   "trespass_tunneling_guidance", "commercial_service_claim"):
        assert m.gate(action) == "HOLD"


def test_sandbox_proceeds():
    assert m.gate("run_simulation") == "PROCEED"


def test_seats_never_override():
    b = m.brains_report()
    assert b["decider"]["can_override_hold"] is False
    assert b["advisor"]["can_override_hold"] is False
    assert b["flow"]["rendered"] is False and b["flow"]["live"] == 0


def test_demo_checks_all_pass():
    checks = m.run_checks()
    assert all(ok for _, ok in checks), [n for n, ok in checks if not ok]


def test_demo_deterministic():
    import io
    import contextlib
    out1, out2 = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out1):
        m.demo()
    with contextlib.redirect_stdout(out2):
        m.demo()
    assert out1.getvalue() == out2.getvalue()
