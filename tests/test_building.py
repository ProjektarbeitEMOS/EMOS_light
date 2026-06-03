"""Tests fuer das Gebaeudemodell der Gebaeudegruppe (Mai 2026).

Bezugskonfiguration aus dem XLSX-Lehrbeispiel:
    l=15, b=10, h=10, A_F=125, U=0.2/0.9/0.4, Lueftung 0.17,
    Estrich c=1070 ρ=2000 d=0.06

Wichtig — Modellabweichung gegenueber XLSX:
    Die XLSX rechnet C_Gebaeude = C_Estrich + C_Wand. EMOS Light
    vernachlaessigt die Wand als Speicher (Modellentscheidung Mai 2026)
    und rechnet nur mit C_Estrich. UA-Werte und P_Verlust sind unveraendert,
    aber τ und t_aus skalieren mit dem Faktor C_Estrich/(C_Estrich+C_Wand)
    = 5.35/12.85 ≈ 0.416 gegenueber den XLSX-Werten.
"""

import pytest

from emos_light.components.building import Building


@pytest.fixture
def lehrbeispiel() -> Building:
    """Genau die Konfig aus dem XLSX, damit τ/t_aus/Q numerisch passen."""
    cfg = {
        "enabled": True, "heated_area_m2": 150,
        "length_m": 15.0, "width_m": 10.0, "height_m": 10.0,
        "window_area_m2": 125.0,
        "u_value_wall_w_m2_k": 0.2,
        "u_value_window_w_m2_k": 0.9,
        "u_value_roof_floor_w_m2_k": 0.4,
        "ventilation_loss_w_m3_k": 0.17,
        "screed_thickness_m": 0.06,
        "screed_density_kg_m3": 2000.0,
        "screed_specific_heat_j_kg_k": 1070.0,
        "reference_temp_c": 22.0,
        "comfort_min_temp_c": 21.0,
    }
    return Building("test", cfg)


# ---------------------------------------------------------------------------
# Geometrie und abgeleitete Groessen
# ---------------------------------------------------------------------------

def test_wall_areas(lehrbeispiel: Building):
    assert lehrbeispiel.wall_area_gross_m2 == pytest.approx(500.0)
    assert lehrbeispiel.wall_area_net_m2 == pytest.approx(375.0)
    assert lehrbeispiel.floor_plan_area_m2 == pytest.approx(150.0)
    assert lehrbeispiel.building_volume_m3 == pytest.approx(1500.0)


def test_ua_values(lehrbeispiel: Building):
    """Trans-UA und Lueft-UA aus XLSX (Sheet 1)."""
    assert lehrbeispiel.transmission_ua_w_per_k == pytest.approx(247.5)
    assert lehrbeispiel.ventilation_ua_w_per_k == pytest.approx(255.0)
    assert lehrbeispiel.total_ua_w_per_k == pytest.approx(502.5)


def test_capacities(lehrbeispiel: Building):
    """C_Estrich + C_Wand wie XLSX, aber total_capacity nur Estrich (EMOS Light)."""
    assert lehrbeispiel.screed_capacity_kwh_per_k == pytest.approx(5.35, abs=0.001)
    assert lehrbeispiel.wall_capacity_kwh_per_k == pytest.approx(7.5, abs=0.001)
    # EMOS-Light-Modell: total_capacity = nur Estrich
    assert lehrbeispiel.total_capacity_kwh_per_k == pytest.approx(5.35, abs=0.001)


# ---------------------------------------------------------------------------
# Verlustleistung, Speicherenergie, Zeitkonstante (XLSX-Werte)
# ---------------------------------------------------------------------------

# τ-Werte: XLSX hat C_Gebaeude (Estrich+Wand). EMOS-Light-Modell rechnet
# nur mit C_Estrich, daher τ skaliert mit 5.35/12.85 ≈ 0.416.

@pytest.mark.parametrize("t_in,p_xls,tau_efh", [
    (22.0, -1507.5, -3.5489220563847428),
    (22.5, -1256.25, -4.2587064676616917),
    (23.0, -1005.0,  -5.3233830845771148),
    (23.5, -753.75,  -7.0978441127694856),
    (24.0, -502.5,   -10.6467661691542297),
])
def test_loss_and_tau_t_aussen_25(lehrbeispiel: Building, t_in, p_xls, tau_efh):
    """Sheet 1 (T_aussen=25): P_Verlust wie XLSX, τ = C_Estrich / P."""
    assert lehrbeispiel.total_loss_w(t_in, 25.0) == pytest.approx(p_xls, abs=0.01)
    assert lehrbeispiel.time_constant_h(t_in, 25.0) == pytest.approx(tau_efh, abs=0.001)


@pytest.mark.parametrize("t_out,p_xls,tau_efh", [
    (18.0, 2512.5, 2.1293532338308458),
    (17.0, 3015.0, 1.7744610281923714),
    (16.0, 3517.5, 1.5209665955934613),
])
def test_loss_and_tau_t_innen_23(lehrbeispiel: Building, t_out, p_xls, tau_efh):
    """Sheet 2 (T_innen=23): P_Verlust wie XLSX, τ skaliert mit C_Estrich."""
    assert lehrbeispiel.total_loss_w(23.0, t_out) == pytest.approx(p_xls, abs=0.01)
    assert lehrbeispiel.time_constant_h(23.0, t_out) == pytest.approx(tau_efh, abs=0.001)


@pytest.mark.parametrize("t_in,q_xls", [
    (22.0, 0.0),
    (22.1, 0.535),    # 5.35 kWh/K · 0.1 K
    (22.5, 2.675),
    (23.0, 5.350),
    (23.5, 8.025),
    (24.0, 10.700),
])
def test_stored_energy(lehrbeispiel: Building, t_in, q_xls):
    """Q_Gebaeude (in der XLSX-Konvention nur Estrich)."""
    assert lehrbeispiel.stored_energy_kwh(t_in) == pytest.approx(q_xls, abs=0.001)


@pytest.mark.parametrize("t_in,t_aus_efh", [
    (22.0, -3.5489220563847428),
    (22.5, -6.3880597014925362),
    (23.0, -10.6467661691542297),
    (23.5, -17.7446102819237161),
    (24.0, -31.9402985074626784),
])
def test_cooldown_time(lehrbeispiel: Building, t_in, t_aus_efh):
    """t_aus = C_Estrich·(T_in - T_min)/P_Verlust mit T_min=21."""
    assert lehrbeispiel.cooldown_time_h(t_in, 25.0) == pytest.approx(t_aus_efh, abs=0.001)


# ---------------------------------------------------------------------------
# Default-Verhalten (typisches EFH ohne explizite Geometrie)
# ---------------------------------------------------------------------------

def test_default_efh_geometry():
    """Mit nur heated_area=150 m² muessen sinnvolle Defaults entstehen."""
    b = Building("efh", {"enabled": True, "heated_area_m2": 150})
    # h=2.5 (Standardgeschoss)
    assert b.height_m == pytest.approx(2.5)
    # l, b ~ sqrt(150) ≈ 12.25
    assert 11.0 < b.length_m < 13.0
    assert 11.0 < b.width_m < 13.0
    # Fenster ~15% der Bruttowandflaeche
    assert b.window_area_m2 == pytest.approx(0.15 * b.wall_area_gross_m2)
    # UA muss > 0 sein und < als das XLSX-Lehrbeispiel (kleineres Volumen)
    assert 0 < b.total_ua_w_per_k < 502.5
