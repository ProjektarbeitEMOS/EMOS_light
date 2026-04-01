"""EMOS Light – Streamlit Dashboard

Energiemanagement fuer Neubau mit Waermepumpe, Fussbodenheizung
und Frischwassersystem.

Starten mit: streamlit run app.py
"""

import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml
from plotly.subplots import make_subplots

from emos_light.core.config import load_config, DEFAULT_CONFIG, WALLBOX_DEFAULT, EV_DEFAULT, PV_SURFACE_DEFAULT
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    load_input_data,
    build_time_series_input,
)
from emos_light.data.profiles import parse_csv_load_profile, forecast_load_profile, get_csv_info
from emos_light.data.prices import get_surcharges_summary
from emos_light.optimization.baseline import calculate_baseline_cost
from emos_light.optimization.mpc import MPCController


# ================================================================
# Seiten-Konfiguration
# ================================================================
st.set_page_config(
    page_title="EMOS Light – Neubau-Optimierung",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ EMOS Light – Energiemanagement Neubau")
st.caption("Waermepumpe | Fussbodenheizung | Frischwassersystem | Dynamischer Strompreis")


# ================================================================
# Session State
# ================================================================
if "config" not in st.session_state:
    config_path = Path("config/default_config.yaml")
    if config_path.exists():
        st.session_state.config = load_config(config_path)
    else:
        st.session_state.config = load_config(None)

if "result" not in st.session_state:
    st.session_state.result = None


# ================================================================
# Sidebar
# ================================================================
with st.sidebar:
    st.header("Konfiguration")

    config_file = st.file_uploader("YAML-Konfiguration laden", type=["yaml", "yml"])
    if config_file is not None:
        try:
            user_yaml = yaml.safe_load(config_file)
            base_config = load_config(None)
            for key, val in user_yaml.items():
                if key in base_config and isinstance(val, dict) and isinstance(base_config[key], dict):
                    base_config[key].update(val)
                else:
                    base_config[key] = val
            st.session_state.config = base_config
            st.success("Konfiguration geladen!")
        except Exception as e:
            st.error(f"Fehler: {e}")

    config = st.session_state.config
    general = config["general"]

    st.divider()

    opt_date = st.date_input(
        "Optimierungsdatum",
        value=datetime.date.today() + datetime.timedelta(days=1),
    )
    use_real_data = st.checkbox("Echte Daten (API)", value=False)

    st.divider()

    # Lastgang-Import
    st.subheader("Lastgang-Import")
    csv_upload = st.file_uploader(
        "Strom-Lastgang (CSV)", type=["csv", "txt"],
        help="CSV mit Zeitstempel und Leistung/Verbrauch.",
    )
    csv_includes_hp = False
    if csv_upload is not None:
        try:
            csv_df = parse_csv_load_profile(csv_upload.getvalue())
            csv_info = get_csv_info(csv_df)
            st.success(
                f"**{csv_info['num_days']} Tage** erkannt "
                f"({csv_info['start_date'].strftime('%d.%m.%Y')} – "
                f"{csv_info['end_date'].strftime('%d.%m.%Y')})"
            )
        except Exception as e:
            st.error(f"CSV-Fehler: {e}")
            csv_upload = None

        if csv_upload is not None:
            csv_includes_hp = st.checkbox(
                "Lastgang enthaelt Waermepumpe", value=False,
            )

    # Optimierungsmodus
    opt_mode = st.radio(
        "Optimierungsmodus",
        ["Day-Ahead (MILP)", "MPC (rollierend)"],
    )
    mpc_execute_hours = 1
    total_horizon_h = general.get("optimization_horizon_hours", 24)
    mpc_horizon_hours = total_horizon_h
    if opt_mode == "MPC (rollierend)":
        mpc_execute_hours = st.slider("MPC Ausfuehrungsfenster (h)", 1, 6, 1)
        mpc_horizon_hours = st.slider(
            "MPC Vorhersagehorizont (h)", 2, int(total_horizon_h),
            min(6, int(total_horizon_h)),
        )
        n_windows = int(np.ceil(total_horizon_h / mpc_execute_hours))
        st.caption(f"MPC: {n_windows} Fenster a {mpc_execute_hours}h")

    st.divider()

    # Komponentenstatus
    st.subheader("Aktive Komponenten")
    components_status = {
        "PV-Anlage": config.get("pv", {}).get("enabled", False),
        "Batterie": config.get("battery", {}).get("enabled", False),
        "Waermepumpe": config.get("heat_pump", {}).get("enabled", False),
        "Fussbodenheizung": config.get("underfloor_heating", {}).get("enabled", False),
        "WW-Speicher": config.get("hot_water_storage", {}).get("enabled", False),
        "Frischwasser": config.get("fresh_water_station", {}).get("enabled", False),
        "Wallbox": any(wb.get("enabled", False) for wb in config.get("wallboxes", [])),
        "E-Auto": any(ev.get("enabled", False) for ev in config.get("electric_vehicles", [])),
    }
    for name, active in components_status.items():
        icon = "+" if active else "-"
        st.write(f"[{icon}] {name}")

    step_minutes = general.get("time_step_minutes", 15)
    horizon_hours = general.get("optimization_horizon_hours", 24)
    num_steps = int(horizon_hours * 60 / step_minutes)
    st.caption(f"Zeitschritt: {step_minutes} min | Horizont: {horizon_hours}h ({num_steps} Schritte)")


# ================================================================
# Tabs
# ================================================================
tab_config, tab_input, tab_optimize = st.tabs([
    "Setup konfigurieren",
    "Eingabedaten",
    "Optimierung",
])


# ================================================================
# Tab 1: Konfig-Editor
# ================================================================
with tab_config:
    st.subheader("Anlagenkonfiguration bearbeiten")

    # Standort & Netz
    with st.expander("Standort & Netz", expanded=True):
        loc_col1, loc_col2 = st.columns(2)
        general["latitude"] = loc_col1.number_input(
            "Breitengrad", -90.0, 90.0, float(general.get("latitude", 49.33)), 0.01,
        )
        general["longitude"] = loc_col2.number_input(
            "Laengengrad", -180.0, 180.0, float(general.get("longitude", 12.11)), 0.01,
        )
        net_col1, net_col2 = st.columns(2)
        general["max_grid_power_kw"] = net_col1.number_input(
            "Max. Netzleistung (kW)", 5.0, 100.0, float(general["max_grid_power_kw"]), 1.0,
        )
        general["feed_in_tariff_ct_kwh"] = net_col2.number_input(
            "Einspeiseverguetung (ct/kWh)", 0.0, 99.0, float(general["feed_in_tariff_ct_kwh"]), 0.1,
        )

    # Stromtarif
    with st.expander("Dynamischer Stromtarif", expanded=False):
        tariff = config.get("tariff", {})
        tariff_preset = st.selectbox(
            "Anbieter-Vorlage",
            ["Benutzerdefiniert", "Tibber", "Ostrom", "aWATTar", "1KOMMA5"],
        )
        presets = {
            "Tibber": {"provider_markup_ct_kwh": 2.15, "monthly_base_fee_eur": 5.99},
            "Ostrom": {"provider_markup_ct_kwh": 0.0, "monthly_base_fee_eur": 6.00},
            "aWATTar": {"provider_markup_ct_kwh": 1.5, "monthly_base_fee_eur": 14.0},
            "1KOMMA5": {"provider_markup_ct_kwh": 0.0, "monthly_base_fee_eur": 14.48},
        }
        if tariff_preset in presets:
            for k, v in presets[tariff_preset].items():
                tariff[k] = v

        t_col1, t_col2 = st.columns(2)
        tariff["provider_markup_ct_kwh"] = t_col1.number_input("Anbieter-Aufschlag (ct/kWh)", 0.0, 10.0, float(tariff.get("provider_markup_ct_kwh", 2.15)), 0.01)
        tariff["grid_fee_ct_kwh"] = t_col2.number_input("Netzentgelt (ct/kWh)", 0.0, 20.0, float(tariff.get("grid_fee_ct_kwh", 9.26)), 0.01)
        tariff["electricity_tax_ct_kwh"] = t_col1.number_input("Stromsteuer (ct/kWh)", 0.0, 5.0, float(tariff.get("electricity_tax_ct_kwh", 2.05)), 0.01)
        tariff["concession_fee_ct_kwh"] = t_col2.number_input("Konzessionsabgabe (ct/kWh)", 0.0, 5.0, float(tariff.get("concession_fee_ct_kwh", 1.66)), 0.01)

        surcharges = (
            tariff.get("provider_markup_ct_kwh", 0)
            + tariff.get("grid_fee_ct_kwh", 0)
            + tariff.get("concession_fee_ct_kwh", 0)
            + tariff.get("electricity_tax_ct_kwh", 0)
            + tariff.get("kwkg_surcharge_ct_kwh", 0)
            + tariff.get("stromnev_surcharge_ct_kwh", 0)
            + tariff.get("offshore_surcharge_ct_kwh", 0)
        )
        st.caption(f"Summe Aufschlaege (netto): {surcharges:.2f} ct/kWh | Brutto (inkl. {tariff.get('vat_pct', 19)}% MwSt.): {surcharges * (1 + tariff.get('vat_pct', 19)/100):.2f} ct/kWh")

    # PV & Batterie
    with st.expander("PV-Anlage & Batterie", expanded=False):
        col_pv, col_batt = st.columns(2)

        with col_pv:
            st.markdown("**PV-Anlage**")
            config["pv"]["enabled"] = st.checkbox("PV aktiviert", value=config["pv"].get("enabled", True), key="pv_en")
            if config["pv"]["enabled"]:
                if "pv_surfaces" not in st.session_state:
                    existing = config["pv"].get("surfaces", [])
                    if existing:
                        st.session_state.pv_surfaces = [s.copy() for s in existing]
                    else:
                        st.session_state.pv_surfaces = [{
                            "name": "Dachflaeche 1",
                            "kwp": config["pv"].get("peak_power_kwp", 12.0),
                            "azimuth_deg": config["pv"].get("azimuth_deg", 180),
                            "tilt_deg": config["pv"].get("tilt_deg", 30),
                        }]

                surfaces = st.session_state.pv_surfaces
                total_kwp = 0.0
                for si, surf in enumerate(surfaces):
                    st.markdown(f"**{surf.get('name', f'Flaeche {si+1}')}**")
                    surf["name"] = st.text_input("Name", surf.get("name", f"Dachflaeche {si+1}"), key=f"pv_s_{si}_name")
                    surf["kwp"] = st.number_input("Leistung (kWp)", 0.1, 100.0, float(surf.get("kwp", 5.0)), 0.5, key=f"pv_s_{si}_kwp")
                    surf["azimuth_deg"] = st.slider("Azimut", 0, 360, int(surf.get("azimuth_deg", 180)), key=f"pv_s_{si}_az")
                    surf["tilt_deg"] = st.slider("Neigung", 0, 90, int(surf.get("tilt_deg", 30)), key=f"pv_s_{si}_tilt")
                    total_kwp += surf["kwp"]
                    if len(surfaces) > 1:
                        if st.button("Flaeche entfernen", key=f"pv_s_{si}_rm"):
                            surfaces.pop(si)
                            for k in [kk for kk in st.session_state if kk.startswith("pv_s_")]:
                                del st.session_state[k]
                            st.rerun()
                    st.divider()

                st.caption(f"Gesamt: **{total_kwp:.1f} kWp** ({len(surfaces)} Flaeche(n))")
                if st.button("+ PV-Flaeche hinzufuegen", key="add_pv_surface"):
                    new_surface = PV_SURFACE_DEFAULT.copy()
                    new_surface["name"] = f"Dachflaeche {len(surfaces) + 1}"
                    surfaces.append(new_surface)
                    st.rerun()

                config["pv"]["surfaces"] = surfaces
                config["pv"]["peak_power_kwp"] = total_kwp

        with col_batt:
            st.markdown("**Batteriespeicher**")
            config["battery"]["enabled"] = st.checkbox("Batterie aktiviert", value=config["battery"].get("enabled", True), key="batt_en")
            if config["battery"]["enabled"]:
                config["battery"]["capacity_kwh"] = st.number_input("Kapazitaet (kWh)", 1.0, 200.0, float(config["battery"]["capacity_kwh"]), 1.0)
                config["battery"]["max_charge_power_kw"] = st.number_input("Max. Ladeleistung (kW)", 0.5, 50.0, float(config["battery"]["max_charge_power_kw"]), 0.5)
                config["battery"]["max_discharge_power_kw"] = st.number_input("Max. Entladeleistung (kW)", 0.5, 50.0, float(config["battery"]["max_discharge_power_kw"]), 0.5)
                soc_range = st.slider("SOC-Bereich (%)", 0, 100, (int(config["battery"]["min_soc"]*100), int(config["battery"]["max_soc"]*100)))
                config["battery"]["min_soc"] = soc_range[0] / 100
                config["battery"]["max_soc"] = soc_range[1] / 100
                config["battery"]["initial_soc"] = st.slider("Start-SOC (%)", soc_range[0], soc_range[1], int(config["battery"]["initial_soc"]*100)) / 100

    # Waermepumpe & SG-Ready
    with st.expander("Waermepumpe & SG-Ready", expanded=False):
        config["heat_pump"]["enabled"] = st.checkbox("WP aktiviert", value=config["heat_pump"].get("enabled", True), key="hp_en")
        if config["heat_pump"]["enabled"]:
            hp_col1, hp_col2 = st.columns(2)
            config["heat_pump"]["max_electrical_power_kw"] = hp_col1.number_input("Max. el. Leistung (kW)", 1.0, 30.0, float(config["heat_pump"]["max_electrical_power_kw"]), 0.5)
            config["heat_pump"]["cop_nominal"] = hp_col2.number_input("COP (nominal)", 2.0, 6.0, float(config["heat_pump"]["cop_nominal"]), 0.1)
            config["heat_pump"]["cop_reference_temp_c"] = hp_col1.number_input("COP-Referenztemp. (C)", -10.0, 20.0, float(config["heat_pump"]["cop_reference_temp_c"]), 1.0)

            config["heat_pump"]["sg_ready"] = st.checkbox("SG-Ready aktiviert", value=config["heat_pump"].get("sg_ready", True), key="sg_en")
            if config["heat_pump"]["sg_ready"]:
                sg_col1, sg_col2 = st.columns(2)
                config["heat_pump"]["sg_ready_temp_raise_state3_c"] = sg_col1.number_input(
                    "State 3: Temp-Erhoehung (K)", 0.0, 15.0,
                    float(config["heat_pump"].get("sg_ready_temp_raise_state3_c", 5.0)), 1.0,
                )
                config["heat_pump"]["sg_ready_temp_raise_state4_c"] = sg_col2.number_input(
                    "State 4: Temp-Erhoehung (K)", 0.0, 20.0,
                    float(config["heat_pump"].get("sg_ready_temp_raise_state4_c", 10.0)), 1.0,
                )

    # WW-Speicher & Frischwasserstation
    with st.expander("WW-Speicher & Frischwasserstation", expanded=False):
        col_ww, col_fws = st.columns(2)
        with col_ww:
            st.markdown("**Warmwasserspeicher**")
            config["hot_water_storage"]["enabled"] = st.checkbox("WW-Speicher aktiviert", value=config["hot_water_storage"].get("enabled", True), key="ww_en")
            if config["hot_water_storage"]["enabled"]:
                config["hot_water_storage"]["volume_liters"] = st.number_input("Volumen (L)", 50, 2000, int(config["hot_water_storage"]["volume_liters"]), 50)
                ww_temp = st.slider(
                    "Temp.-Bereich (C)", 30, 90,
                    (int(config["hot_water_storage"]["min_temperature_c"]),
                     int(config["hot_water_storage"]["max_temperature_c"])),
                    key="ww_temp",
                )
                config["hot_water_storage"]["min_temperature_c"] = float(ww_temp[0])
                config["hot_water_storage"]["max_temperature_c"] = float(ww_temp[1])

                from emos_light.components.thermal_storage import ThermalStorage as _TS
                _ww = _TS("ww_preview", config["hot_water_storage"])
                st.caption(f"Kapazitaet: **{_ww.capacity_kwh:.1f} kWh** | Verlust (50%): **{_ww.standby_loss_w_at_mean:.0f} W**")

        with col_fws:
            st.markdown("**Frischwasserstation**")
            config["fresh_water_station"]["enabled"] = st.checkbox("FWS aktiviert", value=config["fresh_water_station"].get("enabled", True), key="fws_en")
            if config["fresh_water_station"]["enabled"]:
                config["fresh_water_station"]["target_hot_water_temp_c"] = st.number_input(
                    "Ziel-Warmwassertemp. (C)", 40.0, 60.0,
                    float(config["fresh_water_station"]["target_hot_water_temp_c"]), 1.0,
                )
                config["fresh_water_station"]["heat_exchanger_efficiency"] = st.slider(
                    "WT-Wirkungsgrad", 0.70, 0.98,
                    float(config["fresh_water_station"]["heat_exchanger_efficiency"]), 0.01,
                )
                config["fresh_water_station"]["min_storage_temp_for_dhw_c"] = st.number_input(
                    "Min. Speichertemp. fuer WW (C)", 45.0, 70.0,
                    float(config["fresh_water_station"]["min_storage_temp_for_dhw_c"]), 1.0,
                )

    # Fussbodenheizung & Gebaeude
    with st.expander("Fussbodenheizung & Gebaeude", expanded=False):
        col_ufh, col_bldg = st.columns(2)
        with col_ufh:
            st.markdown("**Fussbodenheizung**")
            config["underfloor_heating"]["enabled"] = st.checkbox("FBH aktiviert", value=config["underfloor_heating"].get("enabled", True), key="ufh_en")
            if config["underfloor_heating"]["enabled"]:
                config["underfloor_heating"]["heated_area_m2"] = st.number_input("Beheizte Flaeche (m2)", 30.0, 500.0, float(config["underfloor_heating"]["heated_area_m2"]), 10.0)
                config["underfloor_heating"]["screed_thickness_m"] = st.number_input(
                    "Estrichdicke (cm)", 3.0, 12.0,
                    float(config["underfloor_heating"]["screed_thickness_m"]) * 100, 0.5,
                ) / 100.0
                floor_temp = st.slider(
                    "Komfort-Temperaturband (C)", 18, 30,
                    (int(config["underfloor_heating"]["floor_temp_min_c"]),
                     int(config["underfloor_heating"]["floor_temp_max_c"])),
                    key="floor_temp",
                )
                config["underfloor_heating"]["floor_temp_min_c"] = float(floor_temp[0])
                config["underfloor_heating"]["floor_temp_max_c"] = float(floor_temp[1])

                from emos_light.components.underfloor_heating import UnderfloorHeating as _UFH
                _ufh = _UFH("ufh_preview", config["underfloor_heating"])
                st.caption(
                    f"Therm. Kapazitaet: **{_ufh.capacity_kwh_per_k:.1f} kWh/K** | "
                    f"Nutzbar: **{_ufh.total_capacity_kwh:.0f} kWh** | "
                    f"Verlustrate: **{_ufh.loss_rate_per_h:.3f}/h**"
                )

        with col_bldg:
            st.markdown("**Gebaeude (Neubau)**")
            building_types = {"neubau_enev": "Neubau EnEV (50)", "kfw55": "KfW55 (35)", "kfw40": "KfW40 (25)", "passivhaus": "Passivhaus (15)"}
            config["building"]["building_type"] = st.selectbox(
                "Gebaeudestandard",
                list(building_types.keys()),
                index=list(building_types.keys()).index(config["building"].get("building_type", "kfw55")),
                format_func=lambda x: building_types[x],
            )
            config["building"]["heated_area_m2"] = st.number_input("Beheizte Flaeche (m2)", 30, 500, int(config["building"]["heated_area_m2"]), 10)
            config["building"]["num_occupants"] = st.number_input("Bewohner", 1, 10, int(config["building"]["num_occupants"]))

            from emos_light.components.building import Building as _B
            std = _B.BUILDING_STANDARDS.get(config["building"]["building_type"], 35)
            config["building"]["specific_heat_demand_kwh_m2a"] = std
            config["building"]["annual_heating_kwh"] = int(config["building"]["heated_area_m2"] * std)
            config["heat_demand"]["annual_heating_kwh"] = config["building"]["annual_heating_kwh"]
            config["heat_demand"]["annual_hot_water_kwh"] = int(config["building"]["num_occupants"] * 2.0 * 365)
            config["building"]["annual_hot_water_kwh"] = config["heat_demand"]["annual_hot_water_kwh"]

            st.caption(
                f"Heizwaerme: **{config['building']['annual_heating_kwh']} kWh/a** | "
                f"Warmwasser: **{config['heat_demand']['annual_hot_water_kwh']} kWh/a**"
            )

    # Verbrauch
    with st.expander("Verbrauch", expanded=False):
        v_col1, v_col2, v_col3 = st.columns(3)
        config["household"]["annual_consumption_kwh"] = v_col1.number_input(
            "Jahresstromverbrauch (kWh)", 500, 50000, int(config["household"]["annual_consumption_kwh"]), 500,
        )
        v_col2.metric("Heizwaerme (kWh/a)", config["heat_demand"]["annual_heating_kwh"])
        v_col3.metric("Warmwasser (kWh/a)", config["heat_demand"]["annual_hot_water_kwh"])

    # E-Mobilitaet
    with st.expander("E-Mobilitaet", expanded=False):
        col_wb, col_ev = st.columns(2)

        with col_wb:
            st.markdown("**Wallboxen**")
            wallboxes = config.get("wallboxes", [])

            if st.session_state.get("_wb_add"):
                new_wb = WALLBOX_DEFAULT.copy()
                new_wb["name"] = f"Wallbox {len(wallboxes) + 1}"
                new_wb["enabled"] = True
                config.setdefault("wallboxes", []).append(new_wb)
                wallboxes = config["wallboxes"]
                st.session_state["_wb_add"] = False

            wb_rm_idx = st.session_state.get("_wb_rm_idx")
            if wb_rm_idx is not None and 0 <= wb_rm_idx < len(wallboxes):
                wallboxes.pop(wb_rm_idx)
                st.session_state["_wb_rm_idx"] = None
                for k in [kk for kk in st.session_state if kk.startswith("wb_")]:
                    del st.session_state[k]
                st.rerun()

            for i, wb in enumerate(wallboxes):
                wb["enabled"] = st.checkbox(f"{wb.get('name', f'Wallbox {i+1}')} aktiviert", value=wb.get("enabled", False), key=f"wb_{i}_en")
                if wb["enabled"]:
                    wb["name"] = st.text_input("Name", wb.get("name", f"Wallbox {i+1}"), key=f"wb_{i}_name")
                    wb["max_power_kw"] = st.number_input("Max. Ladeleistung (kW)", 1.4, 22.0, float(wb["max_power_kw"]), 0.5, key=f"wb_{i}_power")
                if st.button("Wallbox entfernen", key=f"wb_{i}_rm"):
                    st.session_state["_wb_rm_idx"] = i
                    st.rerun()
                st.divider()

            if st.button("+ Wallbox hinzufuegen", key="add_wb"):
                st.session_state["_wb_add"] = True
                st.rerun()

        with col_ev:
            st.markdown("**E-Autos**")
            evs = config.get("electric_vehicles", [])

            if st.session_state.get("_ev_add"):
                new_ev = EV_DEFAULT.copy()
                new_ev["name"] = f"E-Auto {len(evs) + 1}"
                new_ev["enabled"] = True
                config.setdefault("electric_vehicles", []).append(new_ev)
                evs = config["electric_vehicles"]
                st.session_state["_ev_add"] = False

            ev_rm_idx = st.session_state.get("_ev_rm_idx")
            if ev_rm_idx is not None and 0 <= ev_rm_idx < len(evs):
                evs.pop(ev_rm_idx)
                st.session_state["_ev_rm_idx"] = None
                for k in [kk for kk in st.session_state if kk.startswith("ev_")]:
                    del st.session_state[k]
                st.rerun()

            for i, ev in enumerate(evs):
                ev["enabled"] = st.checkbox(f"{ev.get('name', f'E-Auto {i+1}')} aktiviert", value=ev.get("enabled", False), key=f"ev_{i}_en")
                if ev["enabled"]:
                    ev["name"] = st.text_input("Name", ev.get("name", f"E-Auto {i+1}"), key=f"ev_{i}_name")
                    ev["battery_capacity_kwh"] = st.number_input("Akkukapazitaet (kWh)", 10.0, 200.0, float(ev.get("battery_capacity_kwh", 58.0)), 5.0, key=f"ev_{i}_cap")
                    ev["current_soc"] = st.slider("Aktueller SOC (%)", 0, 100, int(ev.get("current_soc", 0.3)*100), key=f"ev_{i}_soc") / 100
                    ev["min_range_km"] = st.number_input("Mindestreichweite (km)", 0.0, 500.0, float(ev.get("min_range_km", 150.0)), 10.0, key=f"ev_{i}_range")
                    target_soc = min(1.0, ev["min_range_km"] * ev.get("consumption_kwh_per_100km", 16.0) / 100 / ev["battery_capacity_kwh"])
                    ev["target_soc"] = max(ev["current_soc"], target_soc)
                    st.caption(f"Ziel-SOC: **{ev['target_soc']*100:.0f}%**")

                    ev_col1, ev_col2 = st.columns(2)
                    ev["arrival_hour"] = ev_col1.number_input("Ankunft (h)", 0, 23, int(ev.get("arrival_hour", 17)), key=f"ev_{i}_arr")
                    ev["departure_hour"] = ev_col2.number_input("Abfahrt (h)", 0, 23, int(ev.get("departure_hour", 7)), key=f"ev_{i}_dep")

                    wb_names = [wb.get("name") for wb in config.get("wallboxes", []) if wb.get("enabled")]
                    if wb_names:
                        linked = ev.get("linked_wallbox", wb_names[0])
                        idx = wb_names.index(linked) if linked in wb_names else 0
                        ev["linked_wallbox"] = st.selectbox("Wallbox", wb_names, index=idx, key=f"ev_{i}_wb")

                if st.button("E-Auto entfernen", key=f"ev_{i}_rm"):
                    st.session_state["_ev_rm_idx"] = i
                    st.rerun()
                st.divider()

            if st.button("+ E-Auto hinzufuegen", key="add_ev"):
                st.session_state["_ev_add"] = True
                st.rerun()

        # EV-Daten an Wallboxen weitergeben
        for ev in config.get("electric_vehicles", []):
            if ev.get("enabled"):
                for wb in config.get("wallboxes", []):
                    if wb.get("name") == ev.get("linked_wallbox"):
                        wb["ev_battery_capacity_kwh"] = ev.get("battery_capacity_kwh", 58.0)
                        wb["current_soc"] = ev.get("current_soc", 0.3)
                        wb["target_soc"] = ev.get("target_soc", 0.8)
                        wb["arrival_hour"] = ev.get("arrival_hour", 17)
                        wb["departure_hour"] = ev.get("departure_hour", 7)


# ================================================================
# Tab 2: Eingabedaten
# ================================================================
with tab_input:
    st.subheader("Eingabedaten laden und visualisieren")

    if st.button("Daten laden", type="primary", key="load_data"):
        with st.spinner("Lade Daten..."):
            try:
                data = load_input_data(
                    config, opt_date, use_real_data,
                    csv_upload.getvalue() if csv_upload else None,
                    csv_includes_hp,
                )
                st.session_state["input_data"] = data
                st.success(f"Daten geladen: {data['num_steps']} Zeitschritte")
            except Exception as e:
                st.error(f"Fehler beim Laden: {e}")

    if "input_data" in st.session_state:
        data = st.session_state["input_data"]
        ts = data["timestamps"]
        hours = [t.hour + t.minute / 60 for t in ts]

        # Strompreise
        st.markdown("### Strompreise")
        fig_price = go.Figure()
        fig_price.add_trace(go.Scatter(x=ts, y=data["spot_prices"], name="Boersenpreis", line=dict(color="blue")))
        fig_price.add_trace(go.Scatter(x=ts, y=data["prices"], name="Endverbraucherpreis", line=dict(color="red")))
        fig_price.update_layout(yaxis_title="ct/kWh", height=300, margin=dict(t=30))
        st.plotly_chart(fig_price, use_container_width=True)

        price_cols = st.columns(3)
        price_cols[0].metric("Min", f"{data['prices'].min():.1f} ct/kWh")
        price_cols[1].metric("Mittel", f"{data['prices'].mean():.1f} ct/kWh")
        price_cols[2].metric("Max", f"{data['prices'].max():.1f} ct/kWh")

        # Wetter & PV
        st.markdown("### Wetter & PV-Prognose")
        fig_pv = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                               subplot_titles=("Temperatur & Einstrahlung", "PV-Erzeugung"))
        fig_pv.add_trace(go.Scatter(x=ts, y=data["temp"], name="Temperatur (C)", line=dict(color="orange")), row=1, col=1)
        fig_pv.add_trace(go.Scatter(x=ts, y=data["ghi"], name="GHI (W/m2)", line=dict(color="gold"), yaxis="y2"), row=1, col=1)
        fig_pv.add_trace(go.Scatter(x=ts, y=data["pv_generation"], name="PV (kW)", fill="tozeroy", line=dict(color="goldenrod")), row=2, col=1)
        fig_pv.update_layout(height=400, margin=dict(t=40))
        st.plotly_chart(fig_pv, use_container_width=True)

        pv_daily = float(np.sum(data["pv_generation"]) * data["step_minutes"] / 60)
        st.metric("PV-Tagesertrag", f"{pv_daily:.1f} kWh")

        # Verbrauchsprofile
        st.markdown("### Verbrauchsprofile")
        fig_load = go.Figure()
        fig_load.add_trace(go.Scatter(x=ts, y=data["household_load"], name="Haushalt", line=dict(color="blue")))
        fig_load.add_trace(go.Scatter(x=ts, y=data["heating_demand"], name="Heizwaerme", line=dict(color="red")))
        fig_load.add_trace(go.Scatter(x=ts, y=data["hw_demand"], name="Warmwasser", line=dict(color="cyan")))
        fig_load.update_layout(yaxis_title="kW", height=300, margin=dict(t=30))
        st.plotly_chart(fig_load, use_container_width=True)

        load_cols = st.columns(3)
        load_cols[0].metric("Haushalt", f"{float(np.sum(data['household_load']) * data['step_minutes']/60):.1f} kWh")
        load_cols[1].metric("Heizwaerme", f"{float(np.sum(data['heating_demand']) * data['step_minutes']/60):.1f} kWh")
        load_cols[2].metric("Warmwasser", f"{float(np.sum(data['hw_demand']) * data['step_minutes']/60):.1f} kWh")


# ================================================================
# Tab 3: Optimierung
# ================================================================
with tab_optimize:
    st.subheader("Optimierung starten")

    if st.button("Optimierung starten", type="primary", key="run_opt"):
        with st.spinner("Optimiere..."):
            try:
                # Daten laden (falls nicht bereits geladen)
                data = load_input_data(
                    config, opt_date, use_real_data,
                    csv_upload.getvalue() if csv_upload else None,
                    csv_includes_hp,
                )
                st.session_state["input_data"] = data
                inp = build_time_series_input(config, data)

                # Komponenten und Optimizer erstellen
                components = build_components(config)
                optimizer = build_optimizer(components)

                # Optimierung
                if opt_mode == "Day-Ahead (MILP)":
                    result = optimizer.optimize(inp)
                else:
                    mpc = MPCController(optimizer, mpc_horizon_hours, mpc_execute_hours)
                    result = mpc.run_mpc(inp)

                # Baseline
                baseline_cost = calculate_baseline_cost(inp, config)
                result.baseline_cost_eur = baseline_cost
                if baseline_cost > 0:
                    result.savings_eur = baseline_cost - result.total_cost_eur
                    result.savings_pct = (result.savings_eur / baseline_cost) * 100

                st.session_state.result = result
                st.session_state["opt_inp"] = inp

                if result.success:
                    st.success(f"Optimierung erfolgreich! Loesungszeit: {result.solve_time_s:.1f}s")
                else:
                    st.error(f"Optimierung fehlgeschlagen: {result.solver_status}")

            except Exception as e:
                st.error(f"Fehler: {e}")
                import traceback
                st.code(traceback.format_exc())

    # Ergebnisse anzeigen
    result = st.session_state.result
    if result is not None and result.success:
        inp = st.session_state.get("opt_inp")
        data = st.session_state.get("input_data", {})
        ts = result.timestamps

        # KPI-Karten
        st.markdown("### Ergebnisse")
        kpi_row1 = st.columns(4)
        kpi_row1[0].metric("Gesamtkosten", f"{result.total_cost_eur:.2f} EUR")
        kpi_row1[1].metric("Eigenverbrauch", f"{result.eigenverbrauch_pct:.1f}%")
        kpi_row1[2].metric("Autarkie", f"{result.autarkie_pct:.1f}%")
        if result.savings_eur is not None:
            kpi_row1[3].metric("Einsparung", f"{result.savings_eur:.2f} EUR ({result.savings_pct:.0f}%)")

        kpi_row2 = st.columns(4)
        kpi_row2[0].metric("Netzbezugskosten", f"{result.grid_buy_cost_eur:.2f} EUR")
        kpi_row2[1].metric("Einspeiseverguetung", f"{result.feed_in_revenue_eur:.2f} EUR")
        kpi_row2[2].metric("PV-Ertrag", f"{result.pv_total_kwh:.1f} kWh")
        kpi_row2[3].metric("Netzbezug", f"{result.grid_buy_total_kwh:.1f} kWh")

        # Elektrische Leistungsbilanz
        st.markdown("### Elektrische Leistungsbilanz")
        fig_el = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            subplot_titles=("Leistung (kW)", "Batterie SOC (kWh)"),
            row_heights=[0.7, 0.3],
        )

        if inp is not None:
            fig_el.add_trace(go.Scatter(x=ts, y=inp.pv_generation_kw, name="PV", fill="tozeroy", line=dict(color="gold")), row=1, col=1)
        fig_el.add_trace(go.Scatter(x=ts, y=result.grid_buy_kw, name="Netzbezug", line=dict(color="red")), row=1, col=1)
        fig_el.add_trace(go.Scatter(x=ts, y=-result.grid_sell_kw, name="Einspeisung", line=dict(color="green")), row=1, col=1)
        if len(result.hp_power_kw) > 0:
            fig_el.add_trace(go.Scatter(x=ts, y=result.hp_power_kw, name="WP", line=dict(color="orange")), row=1, col=1)
        for wb_name, wb_arr in result.wallbox_power_kw.items():
            fig_el.add_trace(go.Scatter(x=ts, y=wb_arr, name=f"WB {wb_name}", line=dict(color="cyan")), row=1, col=1)
        if inp is not None:
            fig_el.add_trace(go.Scatter(x=ts, y=inp.household_load_kw, name="Haushalt", line=dict(color="blue", dash="dot")), row=1, col=1)

        if len(result.batt_soc_kwh) > 0:
            fig_el.add_trace(go.Scatter(x=ts, y=result.batt_soc_kwh, name="Batterie SOC", fill="tozeroy", line=dict(color="purple")), row=2, col=1)

        fig_el.update_layout(height=500, margin=dict(t=40))
        st.plotly_chart(fig_el, use_container_width=True)

        # Thermische Uebersicht
        st.markdown("### Thermische Uebersicht")
        has_floor = len(result.floor_temp_c) > 0
        has_ww = len(result.ww_storage_temp_c) > 0
        n_thermal_rows = int(has_floor) + int(has_ww) + 1  # +1 fuer Leistung

        fig_th = make_subplots(
            rows=n_thermal_rows, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            subplot_titles=(
                (["Estrich-Temperatur (C)"] if has_floor else [])
                + (["WW-Speicher-Temperatur (C)"] if has_ww else [])
                + ["WP-Leistungsaufteilung (kW)"]
            ),
        )

        row_idx = 1
        if has_floor:
            ufh_cfg = config.get("underfloor_heating", {})
            fig_th.add_trace(go.Scatter(x=ts, y=result.floor_temp_c, name="Estrich", fill="tozeroy", line=dict(color="purple")), row=row_idx, col=1)
            fig_th.add_hline(y=ufh_cfg.get("floor_temp_min_c", 20), line_dash="dash", line_color="gray", row=row_idx, col=1)
            fig_th.add_hline(y=ufh_cfg.get("floor_temp_max_c", 26), line_dash="dash", line_color="gray", row=row_idx, col=1)
            row_idx += 1

        if has_ww:
            ww_cfg = config.get("hot_water_storage", {})
            fig_th.add_trace(go.Scatter(x=ts, y=result.ww_storage_temp_c, name="WW-Speicher", fill="tozeroy", line=dict(color="steelblue")), row=row_idx, col=1)
            fig_th.add_hline(y=ww_cfg.get("min_temperature_c", 45), line_dash="dash", line_color="red", row=row_idx, col=1)
            fws_cfg = config.get("fresh_water_station", {})
            fig_th.add_hline(y=fws_cfg.get("min_storage_temp_for_dhw_c", 55), line_dash="dot", line_color="orange", row=row_idx, col=1)
            row_idx += 1

        if len(result.q_floor_kw) > 0:
            fig_th.add_trace(go.Scatter(x=ts, y=result.q_floor_kw, name="Q FBH", fill="tozeroy", line=dict(color="orange")), row=row_idx, col=1)
        if len(result.q_ww_kw) > 0:
            fig_th.add_trace(go.Scatter(x=ts, y=result.q_ww_kw, name="Q WW", fill="tonexty", line=dict(color="cyan")), row=row_idx, col=1)

        fig_th.update_layout(height=150 * n_thermal_rows + 100, margin=dict(t=40))
        st.plotly_chart(fig_th, use_container_width=True)

        # SG-Ready Zustand
        if len(result.sg_ready_state) > 0 and np.any(result.sg_ready_state != 2):
            st.markdown("### SG-Ready Zustand")
            sg_colors = {2: "green", 3: "yellow", 4: "red"}
            fig_sg = go.Figure()
            fig_sg.add_trace(go.Scatter(
                x=ts, y=result.sg_ready_state, name="SG-Ready",
                mode="lines", line=dict(color="darkblue", width=2),
                fill="tozeroy",
            ))
            fig_sg.update_layout(
                yaxis=dict(tickvals=[2, 3, 4], ticktext=["Normal", "Empfehlung", "Anlauf"], range=[1.5, 4.5]),
                height=200, margin=dict(t=30),
            )
            st.plotly_chart(fig_sg, use_container_width=True)

        # Preis-Overlay
        if inp is not None:
            st.markdown("### Strompreis vs. Verhalten")
            fig_overlay = make_subplots(specs=[[{"secondary_y": True}]])
            fig_overlay.add_trace(go.Scatter(x=ts, y=inp.prices_ct_kwh, name="Preis (ct/kWh)", line=dict(color="gray", dash="dot")), secondary_y=True)
            fig_overlay.add_trace(go.Scatter(x=ts, y=result.grid_buy_kw, name="Netzbezug", line=dict(color="red")), secondary_y=False)
            if len(result.hp_power_kw) > 0:
                fig_overlay.add_trace(go.Scatter(x=ts, y=result.hp_power_kw, name="WP", line=dict(color="orange")), secondary_y=False)
            fig_overlay.update_layout(height=300, margin=dict(t=30))
            fig_overlay.update_yaxes(title_text="kW", secondary_y=False)
            fig_overlay.update_yaxes(title_text="ct/kWh", secondary_y=True)
            st.plotly_chart(fig_overlay, use_container_width=True)
