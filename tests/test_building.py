"""Tests fuer das Gebaeudemodell der Gebaeudegruppe (Mai 2026).

Validiert die Berechnungen gegen das Lehrbeispiel im XLSX-Sheet
"Bestimmung und Bedeutung 𝜏" (Bezugskonfiguration: l=15, b=10, h=10,
A_F=125, U=0.2/0.9/0.4, Lueftung 0.17, Estrich c=1070 ρ=2000 d=0.06).
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
    """C_Estrich + C_Wand entsprechen den XLSX-Werten 5350 + 7500 Wh/K."""
    assert lehrbeispiel.screed_capacity_kwh_per_k == pytest.approx(5.35, abs=0.001)
    assert lehrbeispiel.wall_capacity_kwh_per_k == pytest.approx(7.5, abs=0.001)
    assert lehrbeispiel.total_capacity_kwh_per_k == pytest.approx(12.85, abs=0.001)


# ---------------------------------------------------------------------------
# Verlustleistung, Speicherenergie, Zeitkonstante (XLSX-Werte)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("t_in,p_xls,tau_xls", [
    (22.0, -1507.5, -8.524046434494196),
    (22.5, -1256.25, -10.228855721393035),
    (23.0, -1005.0,  -12.786069651741293),
    (23.5, -753.75,  -17.04809286898839),
    (24.0, -502.5,   -25.572139303482587),
])
def test_loss_and_tau_t_aussen_25(lehrbeispiel: Building, t_in, p_xls, tau_xls):
    """Sheet 1 des XLSX: T_aussen=25 const, T_innen variiert."""
    assert lehrbeispiel.total_loss_w(t_in, 25.0) == pytest.approx(p_xls, abs=0.01)
    assert lehrbeispiel.time_constant_h(t_in, 25.0) == pytest.approx(tau_xls, abs=0.001)


@pytest.mark.parametrize("t_out,p_xls,tau_xls", [
    (18.0, 2512.5, 5.114427860696518),
    (17.0, 3015.0, 4.262023217247098),
    (16.0, 3517.5, 3.6531627576403696),
])
def test_loss_and_tau_t_innen_23(lehrbeispiel: Building, t_out, p_xls, tau_xls):
    """Sheet 2 des XLSX: T_innen=23 const, T_aussen variiert."""
    assert lehrbeispiel.total_loss_w(23.0, t_out) == pytest.approx(p_xls, abs=0.01)
    assert lehrbeispiel.time_constant_h(23.0, t_out) == pytest.approx(tau_xls, abs=0.001)


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


@pytest.mark.parametrize("t_in,t_aus_xls", [
    (22.0, -8.524046434494196),
    (22.5, -15.343283582089553),
    (23.0, -25.572139303482587),
    (23.5, -42.62023217247098),
    (24.0, -76.71641791044776),
])
def test_cooldown_time(lehrbeispiel: Building, t_in, t_aus_xls):
    """t_aus = C_Gebaeude·(T_in - T_min)/P_Verlust mit T_min=21."""
    assert lehrbeispiel.cooldown_time_h(t_in, 25.0) == pytest.approx(t_aus_xls, abs=0.001)


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
