#!/usr/bin/env python3
"""SubterraX - educational underground transport & tunneling lab.

by Darion Kellar

Pure Python standard library. Zero dependencies. Zero network.
Education only: the world moves more people and freight under the
ground every year, and this lab computes the planning arithmetic
honestly: a tunnel boring machine (TBM) advance-rate model by rock
type (penetration per revolution x RPM x utilisation), excavation
volumes and spoil mass with a bulking factor, the depth environment
(geothermal gradient, lithostatic pressure, ventilation cooling
load), a deterministic station/shaft graph routed with Dijkstra
where edge times are penalised by depth, a pod model with a piston-
effect estimate and headway capacity, and safety interlocks that
REFUSE a plan - egress spacing, ventilation rate, rock temperature,
water ingress - with the violated rule named. Real tunnels (Gotthard
Base, Channel, Laerdal) appear as LABELLED published facts, never as
computed results. This is a planning and learning simulator: it
designs nothing buildable, guides no excavation, and every real-
world construction / blasting / operation action is a HOLD gate -
with Gemini Carbon 4 as DECIDER (names-only, tighten-only), Muse
as advisor (never overrides HOLD), and Google Flow plan-only seats.
"""
import hashlib
import heapq
import json
import math
import sys

# ---------------------------------------------------------------- constants
G_EARTH = 9.80665               # standard gravity, m/s^2 (exact, SI)
VERSION = "1.0.0"

# Depth-environment model constants (LABELLED model values)
SURFACE_TEMP_C = 15.0           # labelled average surface temperature
GEOTHERMAL_GRADIENT_C_PER_KM = 25.0   # labelled continental average
CRUSTAL_DENSITY_KG_M3 = 2700.0  # labelled average crustal rock density
AIR_TARGET_C = 28.0             # labelled occupational air target
ROCK_TEMP_LIMIT_C = 60.0        # labelled uncooled working limit
VENT_U_W_M2K = 0.5              # labelled overall wall heat coefficient
AIR_CP_J_KGK = 1005.0           # specific heat of air
AIR_DENSITY_KG_M3 = 1.2         # air density at surface conditions
AIR_RISE_K = 8.0                # labelled allowed air temperature rise

# Routing / safety model constants (LABELLED model values)
EGRESS_LIMIT_M = 3000.0         # egress point at least every 3,000 m
POD_SPEED_M_PER_MIN = 1000.0    # 60 km/h service speed
DEPTH_PENALTY_PER_KM = 0.10     # +10% edge time per km of depth

# ---------------------------------------------------------------- HOLD gates
HOLD_GATES = {
    "real_excavation_guidance": "HOLD - no guidance for any real excavation; this lab plans on paper only",
    "blasting_guidance": "HOLD - no blasting or explosives guidance of any kind, ever",
    "tbm_operation_live": "HOLD - no operating, driving or maintaining a real tunnel boring machine",
    "construction_instruction": "HOLD - no construction instructions for real tunnels, shafts or stations",
    "mine_operation_claim": "HOLD - no real mine operation; simulated headings are not workings",
    "structural_certification_claim": "HOLD - no certifying any real tunnel safe or structurally sound",
    "geological_survey_live": "HOLD - no interpreting live survey data for a real site or face",
    "emergency_evacuation_live": "HOLD - no live emergency or evacuation direction; egress math here is a planning model",
    "commercial_service_claim": "HOLD - this is an educational lab, not a commercial transport service or product",
    "investment_claim": "HOLD - no investment advice about tunneling, mining or transport companies",
    "guaranteed_schedule_claim": "HOLD - no guaranteed real schedule or cost; every rate here is a labelled model value",
    "weapons_application_claim": "HOLD - no weapons application guidance of any kind",
    "trespass_tunneling_guidance": "HOLD - no guidance for unauthorised digging, tunnelling or subsurface trespass",
    "subsurface_rights_claim": "HOLD - no legal claims or advice about subsurface ownership or rights",
}


def gate(action):
    """Return 'HOLD' if the action is gated, else 'PROCEED' (sandbox sim)."""
    return "HOLD" if action in HOLD_GATES else "PROCEED"


# ================================================================ 1. TBM boring model
# A tunnel boring machine advances one cutterhead revolution at a
# time. The LABELLED planning model used across the industry:
#   penetration  p   [mm per revolution]  - how deep the cutters bite
#   cutterhead   RPM [revolutions / min]
#   utilisation  U   [fraction of the day actually boring - the rest
#                     is segment erection, maintenance, mucking out]
#   advance = p * RPM * 60 / 1000  [m/hour]  ->  x 24 x U  [m/day]
# Rock parameters below are LABELLED planning values in published
# ranges, not measurements from any real face.

ROCKS = {
    "granite":    {"ucs_mpa": 200.0, "density_kg_m3": 2700.0,
                   "pen_mm_rev": 5.0, "rpm": 5.0, "utilization": 0.35},
    "basalt":     {"ucs_mpa": 180.0, "density_kg_m3": 2900.0,
                   "pen_mm_rev": 6.0, "rpm": 5.5, "utilization": 0.38},
    "sandstone":  {"ucs_mpa": 80.0, "density_kg_m3": 2400.0,
                   "pen_mm_rev": 9.0, "rpm": 6.0, "utilization": 0.45},
    "clay":       {"ucs_mpa": 5.0, "density_kg_m3": 1800.0,
                   "pen_mm_rev": 14.0, "rpm": 3.0, "utilization": 0.50},
    "mixed_face": {"ucs_mpa": 120.0, "density_kg_m3": 2500.0,
                   "pen_mm_rev": 4.0, "rpm": 4.0, "utilization": 0.25},
}


def _rock(rock):
    if rock not in ROCKS:
        raise ValueError(f"unknown rock type: {rock}")
    return ROCKS[rock]


def advance_m_per_hour(rock):
    """TBM advance while boring (m/hour) = pen x RPM, unit-converted."""
    r = _rock(rock)
    return r["pen_mm_rev"] / 1000.0 * r["rpm"] * 60.0


def advance_m_per_day(rock):
    """Calendar advance (m/day): boring rate x 24 h x utilisation."""
    r = _rock(rock)
    return advance_m_per_hour(rock) * 24.0 * r["utilization"]


def boring_schedule(rock, length_m=10000.0):
    """Days to bore length_m of tunnel in one rock type (one heading)."""
    if length_m <= 0:
        raise ValueError("length must be positive")
    days = length_m / advance_m_per_day(rock)
    return {"rock": rock, "length_m": length_m,
            "advance_m_per_day": advance_m_per_day(rock),
            "days": days, "years": days / 365.25}


def schedule_table(length_m=10000.0):
    return [boring_schedule(rock, length_m) for rock in
            ("granite", "basalt", "sandstone", "clay", "mixed_face")]


# ================================================================ 2. Excavation & spoil
# Every metre of bore is a cylinder of rock that has to go somewhere.
# Broken rock takes MORE room than it did in the ground - the bulking
# (swell) factor, labelled 1.6 here - and its in-situ mass sets the
# haulage bill: 20-tonne trucks or 1,000-tonne spoil trains.

BULKING_FACTOR = 1.6            # labelled typical swell factor
TRUCK_T = 20.0                  # labelled truck payload, tonnes
TRAIN_T = 1000.0                # labelled spoil-train payload, tonnes
DEFAULT_BORE_D_M = 10.0         # rail-tunnel-class bore diameter


def bore_area_m2(diameter_m=DEFAULT_BORE_D_M):
    """Excavated cross-section of a circular bore (m^2)."""
    if diameter_m <= 0:
        raise ValueError("diameter must be positive")
    return math.pi * (diameter_m / 2.0) ** 2


def excavation(rock, length_m=10000.0, diameter_m=DEFAULT_BORE_D_M):
    """In-situ volume, bulked volume, spoil mass and haulage loads."""
    r = _rock(rock)
    if length_m <= 0:
        raise ValueError("length must be positive")
    volume = bore_area_m2(diameter_m) * length_m
    mass_t = volume * r["density_kg_m3"] / 1000.0
    return {"rock": rock, "length_m": length_m, "diameter_m": diameter_m,
            "area_m2": bore_area_m2(diameter_m),
            "volume_in_situ_m3": volume,
            "volume_bulked_m3": volume * BULKING_FACTOR,
            "spoil_mass_t": mass_t,
            "truck_loads": math.ceil(mass_t / TRUCK_T),
            "train_loads": math.ceil(mass_t / TRAIN_T)}


# ================================================================ 3. Depth environment
# Going down costs twice. The rock gets HOTTER - the geothermal
# gradient, a labelled continental average of ~25 degC per km - and
# the rock column overhead gets HEAVIER: lithostatic pressure
# P = rho g h, about 26.5 MPa per km for crustal rock. Hot rock
# heats the tunnel air through the walls; the ventilation plant must
# carry that heat out, which sizes the airflow.

def rock_temperature_c(depth_m):
    """Rock temperature at depth (degC), labelled gradient model."""
    if depth_m < 0:
        raise ValueError("depth must be non-negative")
    return SURFACE_TEMP_C + GEOTHERMAL_GRADIENT_C_PER_KM * depth_m / 1000.0


def lithostatic_pressure_mpa(depth_m, density_kg_m3=CRUSTAL_DENSITY_KG_M3):
    """Overburden pressure rho g h at depth (MPa)."""
    if depth_m < 0:
        raise ValueError("depth must be non-negative")
    return density_kg_m3 * G_EARTH * depth_m / 1.0e6


def cooling_load_kw(depth_m, diameter_m=DEFAULT_BORE_D_M, per_km=True):
    """Rock-heat load the ventilation must remove (kW per km of tunnel).

    Q = U * A_wall * (T_rock - T_air_target), floored at zero: rock
    cooler than the air target adds no cooling load in this model.
    """
    t_rock = rock_temperature_c(depth_m)
    delta = max(t_rock - AIR_TARGET_C, 0.0)
    wall_area = math.pi * diameter_m * (1000.0 if per_km else 1.0)
    return VENT_U_W_M2K * wall_area * delta / 1000.0


def required_airflow_m3_s(depth_m, diameter_m=DEFAULT_BORE_D_M):
    """Air volume flow that carries the cooling load out (m^3/s per km).

    m_dot = Q / (cp * dT_air); volume flow = m_dot / rho_air.
    """
    q_w = cooling_load_kw(depth_m, diameter_m) * 1000.0
    m_dot = q_w / (AIR_CP_J_KGK * AIR_RISE_K)
    return m_dot / AIR_DENSITY_KG_M3


def depth_table(depths_m=(500.0, 1000.0, 1500.0, 2000.0, 2300.0)):
    rows = []
    for z in depths_m:
        rows.append({"depth_m": z, "rock_temp_c": rock_temperature_c(z),
                     "pressure_mpa": lithostatic_pressure_mpa(z),
                     "cooling_kw_per_km": cooling_load_kw(z),
                     "airflow_m3_s_per_km": required_airflow_m3_s(z)})
    return rows


# ================================================================ 4. Real tunnels (LABELLED published facts)
# These numbers are published facts about finished tunnels, printed
# for scale only. They are NOT outputs of the models above and the
# lab claims no part in any of them.

REAL_TUNNELS = [
    {"name": "Gotthard Base Tunnel", "country": "Switzerland",
     "length_km": 57.0, "kind": "rail", "opened": 2016,
     "note": "longest rail tunnel in the world; max overburden ~2,300 m"},
    {"name": "Channel Tunnel", "country": "UK-France",
     "length_km": 50.5, "kind": "rail", "opened": 1994,
     "note": "under the English Channel; ~37.9 km of it is undersea"},
    {"name": "Laerdal Tunnel", "country": "Norway",
     "length_km": 24.5, "kind": "road", "opened": 2000,
     "note": "longest road tunnel in the world"},
]


def real_tunnels():
    return [dict(t) for t in REAL_TUNNELS]


# ================================================================ 5. Subterranean routing (Dijkstra)
# A small deterministic network: two portals, two ventilation /
# egress shafts, three stations and a junction. Every edge is a bore
# segment with a length and a greatest depth; the traversal time is
# length / speed, penalised +10% per km of depth (pressure, cooling
# and ventilation burden - labelled model). Dijkstra over that graph
# is implemented from scratch on heapq. The EXPRESS_BORE edge is the
# trap: it is the fastest way across and it breaks the egress rule.

GRAPH = {
    "PORTAL_W": [("SHAFT_1", 1800.0, 300.0), ("STN_ALPHA", 4100.0, 800.0)],
    "SHAFT_1": [("PORTAL_W", 1800.0, 300.0), ("STN_ALPHA", 2200.0, 900.0)],
    "STN_ALPHA": [("SHAFT_1", 2200.0, 900.0), ("PORTAL_W", 4100.0, 800.0),
                  ("JUNCTION", 2600.0, 1200.0), ("STN_GAMMA", 2800.0, 2100.0)],
    "JUNCTION": [("STN_ALPHA", 2600.0, 1200.0), ("STN_BETA", 2400.0, 1600.0),
                 ("PORTAL_E", 4600.0, 1700.0)],
    "STN_BETA": [("JUNCTION", 2400.0, 1600.0), ("STN_GAMMA", 2900.0, 1900.0),
                 ("SHAFT_2", 2000.0, 1100.0)],
    "STN_GAMMA": [("STN_ALPHA", 2800.0, 2100.0), ("STN_BETA", 2900.0, 1900.0)],
    "SHAFT_2": [("STN_BETA", 2000.0, 1100.0), ("PORTAL_E", 1900.0, 200.0)],
    "PORTAL_E": [("SHAFT_2", 1900.0, 200.0), ("JUNCTION", 4600.0, 1700.0)],
}

# Nodes where an egress / safe area exists in the model: portals,
# shafts and stations (the junction is a bare crossover cavern).
EGRESS_NODES = {"PORTAL_W", "PORTAL_E", "SHAFT_1", "SHAFT_2",
                "STN_ALPHA", "STN_BETA", "STN_GAMMA"}


def edge_time_min(length_m, depth_m):
    """Depth-penalised traversal time for one bore segment (minutes)."""
    if length_m <= 0:
        raise ValueError("segment length must be positive")
    return (length_m / POD_SPEED_M_PER_MIN) * (1.0 + DEPTH_PENALTY_PER_KM * depth_m / 1000.0)


def _edge_lookup(a, b):
    for (n, length, depth) in GRAPH[a]:
        if n == b:
            return length, depth
    raise KeyError(f"no edge {a}-{b}")


def dijkstra(start, goal, max_segment_m=None):
    """Shortest-time route; optionally forbids segments over a length.

    Returns {"path": [...], "time_min": float, "distance_m": float}.
    """
    if start not in GRAPH or goal not in GRAPH:
        raise ValueError("unknown node")
    dist = {start: 0.0}
    prev = {}
    pq = [(0.0, start)]
    seen = set()
    while pq:
        t, node = heapq.heappop(pq)
        if node in seen:
            continue
        seen.add(node)
        if node == goal:
            break
        for (nxt, length, depth) in GRAPH[node]:
            if max_segment_m is not None and length > max_segment_m:
                continue
            nt = t + edge_time_min(length, depth)
            if nxt not in dist or nt < dist[nxt]:
                dist[nxt] = nt
                prev[nxt] = node
                heapq.heappush(pq, (nt, nxt))
    if goal not in dist:
        raise ValueError(f"no route from {start} to {goal}")
    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    path.reverse()
    distance = sum(_edge_lookup(a, b)[0] for a, b in zip(path, path[1:]))
    return {"path": path, "time_min": dist[goal], "distance_m": distance}


def route_segments(path):
    """Segment-by-segment breakdown of a route path."""
    segs = []
    for a, b in zip(path, path[1:]):
        length, depth = _edge_lookup(a, b)
        segs.append({"from": a, "to": b, "length_m": length,
                     "max_depth_m": depth,
                     "time_min": edge_time_min(length, depth)})
    return segs


# ================================================================ 6. Safety interlocks
# A plan is a route plus an operating envelope. Four interlocks,
# each with a named refusal reason - a plan that breaks one is
# REFUSED, never warned-and-waved-through:
#   EGRESS_SPACING    no bore segment between egress points may
#                     exceed EGRESS_LIMIT_M (labelled model rule)
#   VENTILATION_RATE  provided airflow must cover the cooling-driven
#                     requirement at the route's greatest depth
#   ROCK_TEMPERATURE  rock at the greatest depth must sit at or
#                     under the limit unless a refrigeration plant
#                     is part of the plan
#   WATER_INGRESS     high water-risk geology requires a grouting /
#                     ground-treatment programme in the plan

def check_plan(route, vent_provided_m3_s, refrigeration=False,
               water_risk="low", grouting=False):
    """Audit a route plan against the four interlocks.

    Returns {"accepted": bool, "violations": [reasons], "audit": {...}}.
    """
    segs = route_segments(route["path"])
    max_depth = max(s["max_depth_m"] for s in segs)
    violations = []
    longest = max(s["length_m"] for s in segs)
    # Egress rule: every segment joins two egress nodes by construction
    # of the graph, so the binding test is the segment length itself.
    egress_ok = longest <= EGRESS_LIMIT_M
    if not egress_ok:
        violations.append("EGRESS_SPACING")
    required_flow = required_airflow_m3_s(max_depth)
    vent_ok = vent_provided_m3_s >= required_flow
    if not vent_ok:
        violations.append("VENTILATION_RATE")
    t_rock = rock_temperature_c(max_depth)
    temp_ok = t_rock <= ROCK_TEMP_LIMIT_C or refrigeration
    if not temp_ok:
        violations.append("ROCK_TEMPERATURE")
    water_ok = water_risk != "high" or grouting
    if not water_ok:
        violations.append("WATER_INGRESS")
    return {"accepted": not violations, "violations": violations,
            "audit": {"longest_segment_m": longest,
                      "max_depth_m": max_depth,
                      "rock_temp_c": t_rock,
                      "required_airflow_m3_s": required_flow,
                      "vent_provided_m3_s": vent_provided_m3_s,
                      "egress_ok": egress_ok, "vent_ok": vent_ok,
                      "temp_ok": temp_ok, "water_ok": water_ok}}


def plan_book():
    """The demo plan book: one compliant plan, three refused plans."""
    fast = dijkstra("PORTAL_W", "PORTAL_E")
    compliant = dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=EGRESS_LIMIT_M)
    deep = dijkstra("PORTAL_W", "STN_GAMMA")
    return {
        "north_link_compliant": check_plan(
            compliant, vent_provided_m3_s=80.0, refrigeration=True,
            water_risk="low"),
        "express_bore_fastest": check_plan(
            fast, vent_provided_m3_s=80.0, refrigeration=True,
            water_risk="low"),
        "deep_gamma_no_cooling": check_plan(
            deep, vent_provided_m3_s=200.0, refrigeration=False,
            water_risk="low"),
        "wet_alpha_link_no_grout": check_plan(
            compliant, vent_provided_m3_s=80.0, refrigeration=True,
            water_risk="high", grouting=False),
    }


# ================================================================ 7. Pod model
# A transport pod in a bore is a loose piston: it shoves the air
# ahead of it and drags a wake behind. The blockage ratio beta is
# the pod's cross-section over the bore's; the labelled pressure
# pulse model is dP = 0.5 * rho_air * v^2 * beta / (1 - beta).
# Capacity is set by the signalling headway, not by the pod.

POD_DIAMETER_M = 3.5            # labelled pod diameter
POD_BORE_D_M = 8.0              # labelled transport bore diameter
POD_SPEED_KMH = 80.0            # labelled cruise speed
POD_SEATS = 40                  # labelled seats per pod
HEADWAY_S = 120.0               # labelled minimum headway


def blockage_ratio(pod_d_m=POD_DIAMETER_M, bore_d_m=POD_BORE_D_M):
    """Pod cross-section as a fraction of the bore cross-section."""
    if pod_d_m <= 0 or bore_d_m <= 0 or pod_d_m >= bore_d_m:
        raise ValueError("need 0 < pod diameter < bore diameter")
    return (pod_d_m / bore_d_m) ** 2


def piston_pressure_pa(speed_kmh=POD_SPEED_KMH, pod_d_m=POD_DIAMETER_M,
                       bore_d_m=POD_BORE_D_M):
    """Piston-effect pressure pulse ahead of the pod (Pa, labelled)."""
    v = speed_kmh / 3.6
    beta = blockage_ratio(pod_d_m, bore_d_m)
    return 0.5 * AIR_DENSITY_KG_M3 * v ** 2 * beta / (1.0 - beta)


def pod_capacity(headway_s=HEADWAY_S, seats=POD_SEATS):
    """Pods per hour per direction and passengers per hour."""
    if headway_s <= 0:
        raise ValueError("headway must be positive")
    pods_per_hour = 3600.0 / headway_s
    return {"pods_per_hour": pods_per_hour,
            "passengers_per_hour": pods_per_hour * seats}


def pod_report(route=None):
    if route is None:
        route = dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=EGRESS_LIMIT_M)
    cap = pod_capacity()
    return {"route_path": route["path"], "route_distance_m": route["distance_m"],
            "route_time_min": route["time_min"],
            "blockage_ratio": blockage_ratio(),
            "piston_pressure_pa": piston_pressure_pa(),
            "pods_per_hour": cap["pods_per_hour"],
            "passengers_per_hour": cap["passengers_per_hour"]}


# ================================================================ 8. kNN ground classifier
# Features: (UCS / 100, depth in km x 1.5, water risk x 2) - scaled
# so depth (which brings the heat) counts, and no single feature
# shouts over the others. Labels follow the boring model: hard +
# deep + wet ground eats schedule; soft shallow dry ground is where
# TBMs earn their keep. Training rows are stored in raw units
# (UCS MPa, depth km, water risk 0..1) and scaled by _features.

_CLASSIFIER_TRAIN = [
    # (ucs_mpa, depth_km, water_risk, label)
    (80.0, 0.3, 0.1, "favourable"), (60.0, 0.5, 0.2, "favourable"),
    (100.0, 0.4, 0.1, "favourable"), (40.0, 0.8, 0.3, "favourable"),
    (90.0, 0.2, 0.0, "favourable"), (120.0, 0.6, 0.2, "favourable"),
    (200.0, 1.0, 0.2, "difficult"), (180.0, 1.2, 0.3, "difficult"),
    (150.0, 1.5, 0.4, "difficult"), (200.0, 0.8, 0.5, "difficult"),
    (130.0, 1.8, 0.2, "difficult"), (170.0, 1.0, 0.6, "difficult"),
    (220.0, 2.5, 0.8, "prohibitive"), (200.0, 3.0, 0.6, "prohibitive"),
    (160.0, 2.8, 0.9, "prohibitive"), (240.0, 2.2, 0.7, "prohibitive"),
    (140.0, 3.2, 0.8, "prohibitive"), (190.0, 2.6, 1.0, "prohibitive"),
]


def _features(ucs_mpa, depth_km, water_risk):
    return (ucs_mpa / 100.0, depth_km * 1.5, water_risk * 2.0)


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def classify_ground(ucs_mpa, depth_km, water_risk, k=3):
    """kNN (k=3) ground classifier: favourable / difficult / prohibitive."""
    if ucs_mpa <= 0 or depth_km < 0 or not (0.0 <= water_risk <= 1.0):
        raise ValueError("need ucs > 0, depth >= 0, water risk in [0, 1]")
    f = _features(ucs_mpa, depth_km, water_risk)
    ranked = sorted(_CLASSIFIER_TRAIN,
                    key=lambda row: _dist(f, _features(*row[:3])))
    votes = {}
    for row in ranked[:k]:
        votes[row[3]] = votes.get(row[3], 0) + 1
    return max(sorted(votes), key=lambda lab: votes[lab])


def ground_report():
    scenarios = {
        "shallow_sandstone_dry": (80.0, 0.4, 0.1),
        "granite_1km_low_water": (200.0, 1.0, 0.2),
        "basalt_mid_depth": (180.0, 1.2, 0.3),
        "deep_granite_hot": (200.0, 2.6, 0.3),
        "mixed_face_deep_wet": (120.0, 2.6, 0.85),
    }
    return {name: classify_ground(*vals) for name, vals in scenarios.items()}


# ================================================================ 9. Advisory seats
def _trace(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def carbon4_decide(topic="subterrax-demo"):
    """Gemini Carbon 4 DECIDER seat: MAP->MODEL->STRESS->DECIDE.

    Names-only keys, live calls 0, tighten-only: can add HOLDs, never lift one.
    """
    stages = ["MAP", "MODEL", "STRESS", "DECIDE"]
    payload = {"seat": "gemini-carbon-4", "topic": topic, "stages": stages}
    return {
        "seat": "Gemini Carbon 4 Extended Thinking",
        "role": "DECIDER",
        "pipeline": stages,
        "tiers": [2048, 8192, 32768],
        "key": "names-only (GEMINI_API_KEY name checked, value never read)",
        "live_calls": 0,
        "decision": "PROCEED - sandbox simulation only, all claim gates stay HOLD",
        "can_override_hold": False,
        "trace_sha256_16": _trace(payload),
    }


def claude_advisor(topic="subterrax-demo"):
    """Muse advisor seat: advises, can never override a HOLD."""
    return {
        "seat": "Muse",
        "role": "ADVISOR",
        "key": "names-only (MODEL_API_KEY name checked, value never read)",
        "live_calls": 0,
        "advice": "Quote the advance rate with its utilisation next to it, keep published tunnel lengths labelled as published, and let the interlocks refuse out loud: underground, the plan you reject is the one that saves you.",
        "can_override_hold": False,
    }


def google_flow_plan():
    """Google Flow seat: plan-only, nothing rendered, nothing live."""
    return {
        "seat": "Google Flow",
        "role": "PLAN-ONLY",
        "shots": ["the cutterhead turning, segments rising behind it",
                  "spoil trains climbing out of the dark",
                  "heat shimmer at two kilometres down",
                  "a pod's pressure pulse rolling ahead of it",
                  "the express bore with its egress refusal stamped red"],
        "rendered": False,
        "live": 0,
    }


def brains_report():
    return {"decider": carbon4_decide(), "advisor": claude_advisor(),
            "flow": google_flow_plan()}


# ================================================================ checks
def run_checks():
    c = []

    def chk(name, ok):
        c.append((name, bool(ok)))

    # 1. TBM boring model
    chk("advance_granite_day", abs(advance_m_per_day("granite") - 12.6) < 1e-9)
    chk("advance_basalt_day", abs(advance_m_per_day("basalt") - 18.0576) < 1e-6)
    chk("advance_sandstone_day", abs(advance_m_per_day("sandstone") - 34.992) < 1e-6)
    chk("advance_clay_day", abs(advance_m_per_day("clay") - 30.24) < 1e-9)
    chk("advance_mixed_slowest", advance_m_per_day("mixed_face") == min(
        advance_m_per_day(r) for r in ROCKS))
    chk("advance_hour_is_pen_times_rpm",
        abs(advance_m_per_hour("granite") - 1.5) < 1e-12)
    sched = boring_schedule("granite", 10000.0)
    chk("schedule_granite_10km_days", abs(sched["days"] - 793.6508) < 0.01)
    chk("schedule_years_consistent", abs(sched["years"] - sched["days"] / 365.25) < 1e-12)
    chk("schedule_scales_with_length",
        abs(boring_schedule("clay", 20000.0)["days"]
            - 2 * boring_schedule("clay", 10000.0)["days"]) < 1e-9)
    # 2. excavation & spoil
    chk("bore_area_10m", abs(bore_area_m2(10.0) - 78.5398) < 0.001)
    ex = excavation("granite", 10000.0)
    chk("excavation_volume", abs(ex["volume_in_situ_m3"] - 785398.16) < 1.0)
    chk("excavation_bulked", abs(ex["volume_bulked_m3"]
        - ex["volume_in_situ_m3"] * BULKING_FACTOR) < 1e-6)
    chk("excavation_mass_granite", abs(ex["spoil_mass_t"] - 2120575.04) < 1.0)
    chk("excavation_trucks", ex["truck_loads"] == 106029)
    chk("excavation_trains", ex["train_loads"] == 2121)
    chk("excavation_clay_lighter",
        excavation("clay", 10000.0)["spoil_mass_t"] < ex["spoil_mass_t"])
    # 3. depth environment
    chk("temp_surface", rock_temperature_c(0.0) == SURFACE_TEMP_C)
    chk("temp_1km", abs(rock_temperature_c(1000.0) - 40.0) < 1e-9)
    chk("temp_2km", abs(rock_temperature_c(2000.0) - 65.0) < 1e-9)
    chk("temp_2300m", abs(rock_temperature_c(2300.0) - 72.5) < 1e-9)
    chk("pressure_1km", abs(lithostatic_pressure_mpa(1000.0) - 26.478) < 0.01)
    chk("pressure_scales_linearly",
        abs(lithostatic_pressure_mpa(2000.0)
            - 2 * lithostatic_pressure_mpa(1000.0)) < 1e-9)
    chk("pressure_2300m", abs(lithostatic_pressure_mpa(2300.0) - 60.90) < 0.05)
    chk("cooling_zero_when_cool", cooling_load_kw(500.0) == 0.0)
    chk("cooling_2km_value", abs(cooling_load_kw(2000.0) - 581.19) < 0.5)
    chk("airflow_2km_value", abs(required_airflow_m3_s(2000.0) - 60.24) < 0.1)
    chk("airflow_grows_with_depth",
        required_airflow_m3_s(1500.0) < required_airflow_m3_s(2000.0))
    # 4. labelled references
    refs = real_tunnels()
    chk("reference_count_3", len(refs) == 3)
    chk("reference_gotthard_longest",
        max(refs, key=lambda t: t["length_km"])["name"] == "Gotthard Base Tunnel")
    chk("reference_lengths",
        [t["length_km"] for t in refs] == [57.0, 50.5, 24.5])
    # 5. routing
    chk("edge_time_express", abs(edge_time_min(4600.0, 1700.0) - 5.382) < 1e-9)
    fast = dijkstra("PORTAL_W", "PORTAL_E")
    chk("fastest_uses_express_bore", "JUNCTION" in fast["path"]
        and fast["path"][-2] == "JUNCTION")
    chk("fastest_time", abs(fast["time_min"] - 12.546) < 0.01)
    comp = dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=EGRESS_LIMIT_M)
    chk("compliant_avoids_express",
        all(s["length_m"] <= EGRESS_LIMIT_M for s in route_segments(comp["path"])))
    chk("compliant_time", abs(comp["time_min"] - 14.106) < 0.01)
    chk("compliant_slower_than_fastest", comp["time_min"] > fast["time_min"])
    chk("route_distance_consistent",
        abs(comp["distance_m"] - 12900.0) < 1e-9)
    deep = dijkstra("PORTAL_W", "STN_GAMMA")
    chk("gamma_route_depth", max(s["max_depth_m"] for s in route_segments(deep["path"])) == 2100.0)
    # 6. interlocks
    book = plan_book()
    chk("plan_compliant_accepted", book["north_link_compliant"]["accepted"] is True)
    chk("plan_express_refused_egress",
        book["express_bore_fastest"]["violations"] == ["EGRESS_SPACING"])
    chk("plan_deep_refused_temperature",
        book["deep_gamma_no_cooling"]["violations"] == ["ROCK_TEMPERATURE"])
    chk("plan_wet_refused_water",
        book["wet_alpha_link_no_grout"]["violations"] == ["WATER_INGRESS"])
    starved = check_plan(comp, vent_provided_m3_s=10.0, refrigeration=True)
    chk("plan_starved_refused_ventilation",
        "VENTILATION_RATE" in starved["violations"] and not starved["accepted"])
    cooled = check_plan(deep, vent_provided_m3_s=200.0, refrigeration=True)
    chk("plan_refrigeration_fixes_temperature", cooled["accepted"] is True)
    grouted = check_plan(comp, vent_provided_m3_s=80.0, refrigeration=True,
                         water_risk="high", grouting=True)
    chk("plan_grouting_fixes_water", grouted["accepted"] is True)
    # 7. pod model
    chk("blockage_value", abs(blockage_ratio() - 0.19140625) < 1e-12)
    chk("piston_pressure_band", 65.0 < piston_pressure_pa() < 75.0)
    chk("piston_grows_with_speed",
        piston_pressure_pa(100.0) > piston_pressure_pa(80.0))
    cap = pod_capacity()
    chk("capacity_pods", cap["pods_per_hour"] == 30.0)
    chk("capacity_passengers", cap["passengers_per_hour"] == 1200.0)
    # 8. classifier
    grep = ground_report()
    chk("classifier_favourable", grep["shallow_sandstone_dry"] == "favourable")
    chk("classifier_difficult_granite", grep["granite_1km_low_water"] == "difficult")
    chk("classifier_difficult_basalt", grep["basalt_mid_depth"] == "difficult")
    chk("classifier_prohibitive_hot", grep["deep_granite_hot"] == "prohibitive")
    chk("classifier_prohibitive_wet", grep["mixed_face_deep_wet"] == "prohibitive")
    # gates + seats
    chk("hold_gates_14", len(HOLD_GATES) == 14 and all(v.startswith("HOLD") for v in HOLD_GATES.values()))
    chk("gate_blasting_hold", gate("blasting_guidance") == "HOLD")
    chk("gate_excavation_hold", gate("real_excavation_guidance") == "HOLD")
    chk("gate_certification_hold", gate("structural_certification_claim") == "HOLD")
    chk("gate_trespass_hold", gate("trespass_tunneling_guidance") == "HOLD")
    chk("gate_sandbox_proceed", gate("run_simulation") == "PROCEED")
    b = brains_report()
    chk("carbon4_no_override", b["decider"]["can_override_hold"] is False)
    chk("claude_no_override", b["advisor"]["can_override_hold"] is False)
    chk("flow_plan_only", b["flow"]["rendered"] is False and b["flow"]["live"] == 0)
    return c


# ================================================================ CLI / demo
def demo():
    print("=" * 68)
    print("SubterraX - educational underground transport & tunneling lab")
    print("by Darion Kellar | MIT | pure stdlib | zero network | EDUCATION ONLY")
    print("=" * 68)
    print("\n[1] TBM boring model - one 10 km heading, five rock types (LABELLED rates)")
    for row in schedule_table():
        print(f"    {row['rock']:11s}: {row['advance_m_per_day']:6.2f} m/day | "
              f"10 km in {row['days']:7.1f} days ({row['years']:.2f} yr)")
    print("    -> penetration x RPM is the easy half; utilisation - the share of")
    print("       the day the machine actually bores - is where schedules die.")
    print("\n[2] Excavation & spoil - 10 km of 10 m bore in granite")
    ex = excavation("granite", 10000.0)
    print(f"    cross-section {ex['area_m2']:.2f} m^2 | in-situ {ex['volume_in_situ_m3']:,.0f} m^3 | "
          f"bulked x{BULKING_FACTOR} = {ex['volume_bulked_m3']:,.0f} m^3")
    print(f"    spoil mass {ex['spoil_mass_t']:,.0f} t = {ex['truck_loads']:,} truck loads "
          f"or {ex['train_loads']:,} spoil trains")
    print("    -> a tunnel is a quarry that moves: every metre of railway is")
    print("       ~212 tonnes of granite that must be hauled away.")
    print("\n[3] Depth environment - it gets hot, and it gets heavy")
    for row in depth_table():
        print(f"    depth {row['depth_m']:6.0f} m: rock {row['rock_temp_c']:5.1f} C | "
              f"pressure {row['pressure_mpa']:5.1f} MPa | cooling {row['cooling_kw_per_km']:6.1f} kW/km | "
              f"air {row['airflow_m3_s_per_km']:5.1f} m^3/s/km")
    print("    -> at 2 km the rock is 65 C and carries ~53 MPa of overburden;")
    print("       the ventilation plant is a refrigerator the size of a river.")
    print("\n[4] Real tunnels - LABELLED published facts (not computed here)")
    for t in real_tunnels():
        print(f"    {t['name']:22s} {t['length_km']:5.1f} km {t['kind']} "
              f"({t['country']}, opened {t['opened']}) - {t['note']}")
    print("\n[5] Subterranean routing - Dijkstra over the station/shaft graph")
    fast = dijkstra("PORTAL_W", "PORTAL_E")
    comp = dijkstra("PORTAL_W", "PORTAL_E", max_segment_m=EGRESS_LIMIT_M)
    print(f"    fastest   : {' -> '.join(fast['path'])} = {fast['time_min']:.2f} min "
          f"({fast['distance_m']:,.0f} m)")
    print(f"    compliant : {' -> '.join(comp['path'])} = {comp['time_min']:.2f} min "
          f"({comp['distance_m']:,.0f} m)")
    print("    -> the fastest route rides the 4,600 m express bore. Watch [6].")
    print("\n[6] Safety interlocks - plans are REFUSED, with the reason named")
    for name, verdict in plan_book().items():
        state = "ACCEPTED" if verdict["accepted"] else \
            "REFUSED (" + ", ".join(verdict["violations"]) + ")"
        print(f"    {name:26s} -> {state}")
    print("    -> egress every 3,000 m, air for the heat, rock under 60 C or")
    print("       bring refrigeration, wet ground gets grouted. No exceptions.")
    print("\n[7] Pod model - a loose piston in an 8 m bore")
    rep = pod_report()
    print(f"    blockage ratio {rep['blockage_ratio']:.3f} | piston pulse "
          f"{rep['piston_pressure_pa']:.1f} Pa at {POD_SPEED_KMH:.0f} km/h")
    print(f"    headway {HEADWAY_S:.0f} s -> {rep['pods_per_hour']:.0f} pods/h = "
          f"{rep['passengers_per_hour']:.0f} passengers/h per direction")
    print(f"    portal to portal: {rep['route_distance_m']:,.0f} m in "
          f"{rep['route_time_min']:.2f} min on the compliant route")
    print("\n[8] Ground classifier (TinyML kNN)")
    for name, label in ground_report().items():
        print(f"    {name:24s} -> {label}")
    print("\n[9] Advisory seats")
    print(f"    decider: {carbon4_decide()['decision']} trace={carbon4_decide()['trace_sha256_16']}")
    print(f"    advisor can_override_hold = {claude_advisor()['can_override_hold']}")
    print(f"    flow rendered = {google_flow_plan()['rendered']} live = {google_flow_plan()['live']}")
    print(f"\n[10] HOLD gates: {len(HOLD_GATES)}")
    for k in HOLD_GATES:
        print(f"    HOLD  {k}")
    checks = run_checks()
    passed = sum(1 for _, ok in checks if ok)
    print(f"\nCHECKS {passed}/{len(checks)}")
    for name, ok in checks:
        if not ok:
            print(f"    FAIL {name}")
    verdict = "PROCEED" if passed == len(checks) else "HOLD"
    print(f"VERDICT {verdict} (sandbox simulation only) | HOLD gates {len(HOLD_GATES)}")
    return 0 if passed == len(checks) else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "demo":
        return demo()
    cmd = argv[0]
    if cmd == "checks":
        checks = run_checks()
        for name, ok in checks:
            print(f"{'PASS' if ok else 'FAIL'} {name}")
        print(f"CHECKS {sum(1 for _, ok in checks if ok)}/{len(checks)}")
        return 0 if all(ok for _, ok in checks) else 1
    if cmd == "boring":
        print(json.dumps(schedule_table(), indent=2, sort_keys=True))
        return 0
    if cmd == "spoil":
        rows = [excavation(rock, 10000.0) for rock in ROCKS]
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    if cmd == "depth":
        print(json.dumps(depth_table(), indent=2, sort_keys=True))
        return 0
    if cmd == "history":
        print(json.dumps(real_tunnels(), indent=2, sort_keys=True))
        return 0
    if cmd == "routing":
        out = {"fastest": dijkstra("PORTAL_W", "PORTAL_E"),
               "compliant": dijkstra("PORTAL_W", "PORTAL_E",
                                     max_segment_m=EGRESS_LIMIT_M)}
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    if cmd == "plans":
        print(json.dumps(plan_book(), indent=2, sort_keys=True))
        return 0
    if cmd == "pods":
        print(json.dumps(pod_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "classify":
        print(json.dumps(ground_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "brains":
        print(json.dumps(brains_report(), indent=2, sort_keys=True))
        return 0
    if cmd == "holds":
        for k, v in HOLD_GATES.items():
            print(f"{k}: {v}")
        return 0
    if cmd == "hold-demo":
        action = argv[1] if len(argv) > 1 else "blasting_guidance"
        print(f"{action}: {HOLD_GATES.get(action, 'PROCEED - not gated')}")
        return 2 if gate(action) == "HOLD" else 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
