"""EMOS Light – Streamlit Dashboard

Energiemanagement fuer Neubau mit Waermepumpe, Fussbodenheizung
und Frischwassersystem.

Starten mit: streamlit run app.py
"""

import datetime
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import yaml
from plotly.subplots import make_subplots


# Datei, in der wir importierte Configs zwischenparken, damit sie einen
# vollstaendigen Browser-Reload ueberleben (Session-State und Widget-
# State werden dabei verworfen). Beim naechsten Start liest die App
# diese Datei, uebernimmt sie als Config und loescht sie wieder. So
# starten alle Widgets nach dem Import garantiert mit den neuen
# Werten — Streamlits interner Widget-Cache hat keine Chance,
# alte Slider-Positionen "durchzureichen".
_PENDING_IMPORT_PATH = (
    Path(tempfile.gettempdir()) / "emos_light_pending_import.yaml"
)

from emos_light.core.config import load_config, DEFAULT_CONFIG, WALLBOX_DEFAULT, EV_DEFAULT, PV_SURFACE_DEFAULT
from emos_light.core.config import _deep_merge as _config_deep_merge
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    load_input_data,
    build_time_series_input,
)
from emos_light.data.profiles import parse_csv_load_profile, forecast_load_profile, get_csv_info
from emos_light.data.prices import get_surcharges_summary
from emos_light.optimization.baseline import calculate_baseline_cost, run_baseline
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
def _merge_with_defaults(user_yaml: dict | None) -> dict:
    """Importierte/wiederhergestellte Config IMMER mit DEFAULT_CONFIG mergen.

    Sorgt dafuer, dass nach dem Import keine Top-Level-Sektion fehlt —
    sonst crasht das Sidebar-Rendering spaeter mit ``KeyError`` (z.B.
    bei ``config["hot_water_storage"]["enabled"]``, wenn der User
    eine schlanke YAML ohne diese Sektion hochgeladen hat). Nutzt den
    rekursiven ``_deep_merge`` aus emos_light.core.config — gleiches
    Verhalten wie ``load_config(path)``.
    """
    import copy as _copy
    base = _copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(user_yaml, dict):
        return base
    merged = _config_deep_merge(base, user_yaml)
    # Wallbox-Liste sauber mit Defaults pro Eintrag mergen
    if "wallboxes" in user_yaml and isinstance(user_yaml["wallboxes"], list):
        merged["wallboxes"] = [
            _config_deep_merge(WALLBOX_DEFAULT, wb)
            for wb in user_yaml["wallboxes"]
        ]
    return merged


if "config" not in st.session_state:
    config_path = Path("config/default_config.yaml")
    # Hat der letzte Session-Run einen Import angestossen, der dann
    # einen Browser-Reload getriggert hat? Dann liegt die importierte
    # Config in der Pending-Datei — uebernehmen, danach loeschen.
    if _PENDING_IMPORT_PATH.exists():
        try:
            with _PENDING_IMPORT_PATH.open("r", encoding="utf-8") as f:
                pending_yaml = yaml.safe_load(f)
            # Defense-in-Depth: auch wenn die Pending-Datei ueblicherweise
            # vom Import-Block geschrieben wird (bereits vollstaendig),
            # filtern wir hier nochmal durch DEFAULT_CONFIG. Damit
            # ueberleben auch alte Pending-Dateien aus frueheren Versionen
            # oder schlanke YAMLs ohne alle Sektionen.
            st.session_state.config = _merge_with_defaults(pending_yaml)
        finally:
            try:
                _PENDING_IMPORT_PATH.unlink()
            except OSError:
                pass
    elif config_path.exists():
        st.session_state.config = load_config(config_path)
    else:
        st.session_state.config = load_config(None)

# Skip-Render-Zwischenrunde nach Config-Import.
#
# Hintergrund: Streamlits Widget-State-Cache ist nach einem Import
# hartnaeckig — selbst nach `del st.session_state[key]` plus Rerun
# zeigen Slider und Checkboxen gelegentlich noch die Werte von vor
# dem Import. Der Trick "PV-Toggle aus + ein" funktioniert, weil die
# Widgets dabei fuer einen Render-Cycle aus dem DOM verschwinden und
# Streamlit ihren State erst dann wirklich verwirft.
#
# Wir mimen dieses Verhalten: nach Import setzen wir
# `_remount_step = 1` und rerun. Im naechsten Run greift dieser
# Block sofort am Anfang, setzt `_remount_step = 2` und ruft
# `st.rerun()` auf — die Sidebar wird in diesem Run nie betreten,
# Streamlit raeumt den Widget-State der nicht-gerenderten Widgets
# auf. Der dritte Run rendert dann normal, alle Widgets initialisieren
# sich aus der frischen Config.
_remount_step = st.session_state.pop("_remount_step", 0)
if _remount_step == 1:
    st.session_state["_remount_step"] = 2
    st.rerun()

if "result" not in st.session_state:
    st.session_state.result = None

# Widget-Generation: jeder Widget-Key bekommt ein "_g{N}"-Suffix.
# Beim Config-Import inkrementieren wir N -> alle Keys sind neu ->
# Streamlit instanziiert alle Widgets frisch und liest ihren
# Default-Wert aus der gerade importierten Config. Standard-Streamlit-
# Pattern zum erzwungenen Reset des Widget-State, weil
# `del st.session_state[key]` allein nicht zuverlaessig die intern
# gecachten Widget-Werte loescht.
if "_widget_gen" not in st.session_state:
    st.session_state["_widget_gen"] = 0


def _wkey(name: str) -> str:
    """Suffix einen Widget-Key mit der aktuellen Generation.

    Verwendung an JEDER `key=`-Stelle in Eingabe-Widgets im Sidebar-
    Konfigurationsbereich. Buttons (z.B. "Optimierung starten") brauchen
    es nicht zwingend, sind aber konsistent suffixiert.

    Eigener Session-State (Flags wie `_wb_add`, Listen wie
    `pv_surfaces`) NICHT suffixieren — die werden manuell verwaltet
    und beim Import durch den KEEP_KEYS-Reset abgeraeumt.
    """
    return f"{name}_g{st.session_state.get('_widget_gen', 0)}"


# ================================================================
# Sidebar
# ================================================================
with st.sidebar:
    st.header("Konfiguration")

    # Debug-Inspector (temporaer; bitte zeigen, wenn Bugs beim Import
    # auftreten): macht den abgeleiteten State sichtbar. Wenn z.B.
    # nach Import die importierten Werte nicht in der UI auftauchen,
    # zeigt dieser Block, ob das Problem auf Python-Seite (Config
    # falsch geladen) oder Frontend-Seite (Streamlit-Widget-Cache)
    # liegt.
    with st.expander("Debug-Info (State-Inspector)", expanded=False):
        cfg_pv = st.session_state.get("config", {}).get("pv", {})
        surfaces_in_cfg = cfg_pv.get("surfaces", [])
        st.write({
            "_widget_gen": st.session_state.get("_widget_gen"),
            "_remount_step": st.session_state.get("_remount_step"),
            "_imported_config_id": st.session_state.get("_imported_config_id"),
            "pv.enabled (config)": cfg_pv.get("enabled"),
            "pv.surfaces (config)": [
                {"name": s.get("name"), "kwp": s.get("kwp"),
                 "az": s.get("azimuth_deg"), "tilt": s.get("tilt_deg")}
                for s in surfaces_in_cfg
            ],
            "pv_surfaces (session_state)": st.session_state.get("pv_surfaces"),
        })

    # Import
    # Der File-Uploader bekommt ebenfalls einen versionierten Key.
    # Konsequenz: nach Inkrement von `_widget_gen` (im Import-Block)
    # erscheint im Browser ein FRISCHER File-Uploader ohne hochgeladene
    # Datei. Damit verhindern wir, dass dieselbe Datei in der naechsten
    # Render-Runde erneut den Import-Block triggert und wir koennen
    # gleich nach dem Import den anderen Widgets sauber neu rendern.
    config_file = st.file_uploader(
        "YAML-Konfiguration importieren",
        type=["yaml", "yml"],
        key=_wkey("config_uploader"),
    )
    # Persistenter UX-Anker: nach dem Import wird der File-Uploader
    # absichtlich remountet (neuer Widget-Key) und ist daher leer.
    # Damit der User trotzdem sieht, welche YAML aktuell aktiv ist,
    # zeigen wir den Dateinamen als kleine Caption unter dem Widget.
    _imported_name = st.session_state.get("_imported_config_name")
    if _imported_name:
        col_info, col_clear = st.columns([4, 1])
        col_info.caption(f"📄 Importiert: **{_imported_name}**")
        if col_clear.button(
            "✕", key=_wkey("clear_import_marker"),
            help="Anzeige loeschen (aendert die geladene Konfiguration nicht)",
        ):
            del st.session_state["_imported_config_name"]
            st.session_state.pop("_imported_config_id", None)
            st.rerun()
    if config_file is not None:
        # Datei-ID: stabil ueber rerun, eindeutig pro Upload. Damit
        # erkennen wir, dass derselbe Upload nach einem rerun schon
        # importiert wurde, und vermeiden eine Endlosschleife.
        file_id = getattr(config_file, "file_id", None) or config_file.name
        if st.session_state.get("_imported_config_id") != file_id:
            try:
                user_yaml = yaml.safe_load(config_file)
                # Vollstaendigen, mit Defaults gemergter Config bauen —
                # selbst wenn die hochgeladene YAML einzelne Sektionen
                # auslaesst (z.B. nur ``pv`` und ``battery``), bekommen
                # wir trotzdem ein vollstaendiges Dict zurueck. Spart
                # uns spaeter Sidebar-KeyErrors.
                base_config = _merge_with_defaults(user_yaml)

                # Drei-Phasen-Import:
                #
                # Phase 1 (jetzt): Config in Session-State schreiben,
                #   in eine Pending-Datei spiegeln (Safety-Net, falls
                #   der User die Seite manuell refresht), alle anderen
                #   Session-Keys abraeumen, und einen Skip-Render-
                #   Cycle anstossen.
                # Phase 2 (naechster Run): der `_remount_step`-Handler
                #   am Skript-Anfang fuehrt einen Rerun aus, OHNE die
                #   Sidebar zu rendern. Streamlit verwirft dabei den
                #   Widget-State der Slider/Checkboxen, weil sie
                #   nicht im Render-Baum auftauchen.
                # Phase 3 (uebernaechster Run): alle Widgets werden
                #   frisch aus der neuen Config initialisiert.
                st.session_state.config = base_config
                with _PENDING_IMPORT_PATH.open("w", encoding="utf-8") as f:
                    yaml.safe_dump(
                        base_config, f, allow_unicode=True, sort_keys=False,
                    )
                # Alle Non-Config-Keys abraeumen (abgeleiteter State
                # wie pv_surfaces, transiente Flags, gecachte Solver-
                # Ergebnisse). ``_imported_config_name`` ist eine reine
                # Anzeige-Variable und ueberlebt die Cleanup-Runde, damit
                # die UI weiter sehen kann, welche Datei aktiv ist
                # (der File-Uploader selbst wird ja absichtlich
                # remountet und ist nach dem Import leer).
                KEEP_KEYS = {
                    "config", "_imported_config_id",
                    "_imported_config_name", "_widget_gen",
                }
                for key in list(st.session_state.keys()):
                    if key not in KEEP_KEYS:
                        del st.session_state[key]
                # Widget-Generation hochzaehlen (Defense-in-Depth:
                # Schluessel sind im naechsten Render-Lauf neu).
                st.session_state["_widget_gen"] = (
                    st.session_state.get("_widget_gen", 0) + 1
                )
                st.session_state["_imported_config_id"] = file_id
                st.session_state["_imported_config_name"] = config_file.name
                # Skip-Render-Cycle starten.
                st.session_state["_remount_step"] = 1
                st.success("Konfiguration geladen — wende an ...")

                # Zusaetzlich versuchen wir einen vollstaendigen
                # Browser-Reload via JS. Streamlits Komponenten-Iframe
                # hat zwar standardmaessig kein `allow-top-navigation`
                # und blockiert reines `window.parent.location.reload()`,
                # aber `same-origin` ist erlaubt — manche Browser/
                # Streamlit-Versionen lassen den Reload damit doch durch.
                # Wenn er greift, laedt die App die Pending-Datei sauber
                # neu. Wenn nicht, faellt der Skip-Render-Mechanismus an.
                components.html(
                    """
                    <script>
                    (function() {
                        var attempts = [
                            function() { window.parent.location.reload(); },
                            function() { window.top.location.reload(); },
                            function() { window.parent.location.href = window.parent.location.href; },
                        ];
                        for (var i = 0; i < attempts.length; i++) {
                            try { attempts[i](); return; } catch(e) { /* try next */ }
                        }
                        console.warn("Streamlit reload failed — Sandbox blockt window.parent.");
                    })();
                    </script>
                    """,
                    height=0,
                )
                st.rerun()
            except Exception as e:
                st.error(f"Fehler: {e}")

    # Export
    config_yaml = yaml.dump(
        st.session_state.config,
        default_flow_style=False, allow_unicode=True, sort_keys=False,
    )
    st.download_button(
        "Konfiguration exportieren (.yaml)",
        data=config_yaml,
        file_name="emos_light_config.yaml",
        mime="application/x-yaml",
    )

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
        ["Day-Ahead (MILP)", "MPC (rollierend)", "Baseline (regelbasiert)"],
    )
    mpc_execute_hours = 1
    total_horizon_h = general.get("optimization_horizon_hours", 48)
    # mpc_horizon_hours = None → MPCController nutzt dynamischen Day-Ahead-
    # Horizont (vor 13 Uhr bis Tagesende heute, ab 13 Uhr bis Tagesende morgen).
    mpc_horizon_hours = None
    if opt_mode == "MPC (rollierend)":
        mpc_execute_hours = st.slider("MPC Ausfuehrungsfenster (h)", 1, 6, 1)
        st.info(
            "ℹ️ **Day-Ahead-Horizont:** Der MPC-Vorhersagehorizont wird "
            "automatisch aus der aktuellen Ortszeit abgeleitet — analog "
            "zur EPEX-SPOT-Preisveroeffentlichung:\n\n"
            "- **Vor 13 Uhr** Ortszeit → Horizont bis Tagesende **heute** "
            "(morgige Preise noch nicht verfuegbar)\n"
            "- **Ab 13 Uhr** Ortszeit → Horizont bis Tagesende **morgen**\n\n"
            "Das Fenster ist nie laenger als die hinterlegten Preisdaten."
        )
        n_windows = int(np.ceil(total_horizon_h / mpc_execute_hours))
        st.caption(f"MPC: bis zu {n_windows} Fenster a {mpc_execute_hours}h Ausfuehrung")

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
    horizon_hours = general.get("optimization_horizon_hours", 48)
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
    _loc_container = st.container(key=_wkey("location_section"))
    with _loc_container, st.expander("Standort & Netz", expanded=True):
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

    # §14a EnWG — Netzdrosselung (Testszenario)
    _par14a_container = st.container(key=_wkey("par14a_section"))
    with _par14a_container, st.expander("§14a Netzdrosselung (Test)", expanded=False):
        par14a = config.setdefault("par14a", {})
        par14a["enabled"] = st.checkbox(
            "Netzdrosselung simulieren",
            value=bool(par14a.get("enabled", False)),
            help="Simuliert eine §14a-EnWG-Dimmung: der Netzbetreiber "
                 "begrenzt im gewaehlten Zeitfenster die Summe der "
                 "steuerbaren Lasten (Waermepumpe, Wallbox) auf eine "
                 "reduzierte Leistung. Nur zum Testen der Funktion.",
        )
        par14a_on = bool(par14a["enabled"])
        pc1, pc2, pc3 = st.columns(3)
        par14a["curtailment_kw"] = pc1.number_input(
            "Drossel-Leistung (kW)", 0.0, 30.0,
            float(par14a.get("curtailment_kw", 4.2)), 0.1,
            help="Obergrenze fuer die Summe der steuerbaren Lasten "
                 "waehrend der Drosselung. §14a-Mindestwert: 4,2 kW.",
            disabled=not par14a_on,
        )
        par14a["curtail_start_hour"] = int(pc2.number_input(
            "Beginn (Uhr)", 0, 23,
            int(par14a.get("curtail_start_hour", 17)), 1,
            disabled=not par14a_on,
        ))
        par14a["curtail_end_hour"] = int(pc3.number_input(
            "Ende (Uhr)", 0, 24,
            int(par14a.get("curtail_end_hour", 20)), 1,
            disabled=not par14a_on,
        ))
        if par14a_on:
            s, e = par14a["curtail_start_hour"], par14a["curtail_end_hour"]
            if s == e:
                st.warning(
                    "Beginn = Ende: kein Drosselfenster aktiv "
                    "(die Drosselung greift dann nicht)."
                )
            else:
                fenster = (
                    f"{s:02d}:00–{e:02d}:00 Uhr" if s < e
                    else f"{s:02d}:00–24:00 + 00:00–{e:02d}:00 Uhr"
                )
                st.caption(
                    f"⚡ Drosselung auf **{par14a['curtailment_kw']:.1f} kW** "
                    f"im Fenster **{fenster}** (taeglich). "
                    "Betrifft Waermepumpe und Wallbox; Komfort darf der "
                    "Solver dafuer weich verletzen (Slack)."
                )

    # Stromtarif
    _tariff_container = st.container(key=_wkey("tariff_section"))
    with _tariff_container, st.expander("Dynamischer Stromtarif", expanded=False):
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
    # Versionierter Container: bei Inkrement von `_widget_gen` aendert
    # sich der Container-Key -> Streamlits Frontend unmountet den
    # gesamten DOM-Subtree (inkl. aller PV/Batterie-Widgets) und mountet
    # ihn neu. Das ist ein staerkerer Hebel als nur Widget-Keys zu
    # tauschen, weil React den ganzen Subtree als neu sieht.
    _pv_batt_container = st.container(key=_wkey("pv_batt_section"))
    with _pv_batt_container, st.expander("PV-Anlage & Batterie", expanded=False):
        col_pv, col_batt = st.columns(2)

        with col_pv:
            st.markdown("**PV-Anlage**")
            config["pv"]["enabled"] = st.checkbox("PV aktiviert", value=config["pv"].get("enabled", True), key=_wkey("pv_en"))
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
                    surf["name"] = st.text_input("Name", surf.get("name", f"Dachflaeche {si+1}"), key=_wkey(f"pv_s_{si}_name"))
                    surf["kwp"] = st.number_input("Leistung (kWp)", 0.1, 100.0, float(surf.get("kwp", 5.0)), 0.5, key=_wkey(f"pv_s_{si}_kwp"))
                    surf["azimuth_deg"] = st.slider("Azimut", 0, 360, int(surf.get("azimuth_deg", 180)), key=_wkey(f"pv_s_{si}_az"))
                    surf["tilt_deg"] = st.slider("Neigung", 0, 90, int(surf.get("tilt_deg", 30)), key=_wkey(f"pv_s_{si}_tilt"))
                    total_kwp += surf["kwp"]
                    if len(surfaces) > 1:
                        if st.button("Flaeche entfernen", key=_wkey(f"pv_s_{si}_rm")):
                            surfaces.pop(si)
                            for k in [kk for kk in st.session_state if kk.startswith("pv_s_")]:
                                del st.session_state[k]
                            st.rerun()
                    st.divider()

                st.caption(f"Gesamt: **{total_kwp:.1f} kWp** ({len(surfaces)} Flaeche(n))")
                if st.button("+ PV-Flaeche hinzufuegen", key=_wkey("add_pv_surface")):
                    new_surface = PV_SURFACE_DEFAULT.copy()
                    new_surface["name"] = f"Dachflaeche {len(surfaces) + 1}"
                    surfaces.append(new_surface)
                    st.rerun()

                config["pv"]["surfaces"] = surfaces
                config["pv"]["peak_power_kwp"] = total_kwp

                # -------- Ertragsprognose-Modell --------
                # Modell ist fest auf Perez (1990) anisotrop gestellt — Sieger
                # aus dem internen Vergleich gegen Liu&Jordan, EMOS_iso und
                # HTW PVprog (siehe "PV Prognose Tool angepasst/FORECASTS.md":
                # nRMSE 11.08 % unkalibriert, 8.77 % mit datenbasierter
                # Kalibrierung k). Kein Selector mehr, damit Anwender nicht
                # unbeabsichtigt auf das schlechtere isotrope Modell wechseln.
                config["pv"]["transposition_model"] = "perez"
                st.caption(
                    "📡 **Ertragsprognose:** Perez (1990) anisotrop mit "
                    "Spencer-Sonnenstand und Kasten-Luftmasse — bestes "
                    "wetterbasiertes Modell aus dem internen Vergleich. "
                    "Optionale Anlagen-Kalibrierung (`pv.k_calibration`) "
                    "ueber das Standalone-Tool _PV Prognose Tool angepasst/_."
                )

        with col_batt:
            st.markdown("**Batteriespeicher**")
            config["battery"]["enabled"] = st.checkbox("Batterie aktiviert", value=config["battery"].get("enabled", True), key=_wkey("batt_en"))
            if config["battery"]["enabled"]:
                config["battery"]["capacity_kwh"] = st.number_input("Kapazitaet (kWh)", 1.0, 200.0, float(config["battery"]["capacity_kwh"]), 1.0)
                config["battery"]["max_charge_power_kw"] = st.number_input("Max. Ladeleistung (kW)", 0.5, 50.0, float(config["battery"]["max_charge_power_kw"]), 0.5)
                config["battery"]["max_discharge_power_kw"] = st.number_input("Max. Entladeleistung (kW)", 0.5, 50.0, float(config["battery"]["max_discharge_power_kw"]), 0.5)
                soc_range = st.slider("SOC-Bereich (%)", 0, 100, (int(config["battery"]["min_soc"]*100), int(config["battery"]["max_soc"]*100)))
                config["battery"]["min_soc"] = soc_range[0] / 100
                config["battery"]["max_soc"] = soc_range[1] / 100
                config["battery"]["initial_soc"] = st.slider("Start-SOC (%)", soc_range[0], soc_range[1], int(config["battery"]["initial_soc"]*100)) / 100

                # Alterungskosten (PDF Speichergruppe)
                st.markdown("**Alterungskosten (Zyklus-Verschleiss)**")
                config["battery"]["aging_cost_enabled"] = st.checkbox(
                    "Alterungskosten beruecksichtigen",
                    value=config["battery"].get("aging_cost_enabled", True),
                    key=_wkey("bat_aging_en"),
                )
                config["battery"]["replacement_cost_eur_per_kwh"] = st.number_input(
                    "Wiederbeschaffungswert (EUR/kWh)",
                    100.0, 1500.0,
                    float(config["battery"].get("replacement_cost_eur_per_kwh", 500.0)),
                    50.0,
                    key=_wkey("bat_repl_cost"),
                )
                config["battery"]["equivalent_full_cycles"] = int(st.number_input(
                    "Aequivalent-Vollzyklen bis EOL",
                    1000, 15000,
                    int(config["battery"].get("equivalent_full_cycles", 6000)),
                    500,
                    key=_wkey("bat_efc"),
                ))
                config["battery"]["residual_value_pct"] = st.number_input(
                    "Restwert am Lebensende (0-1)",
                    0.0, 0.5,
                    float(config["battery"].get("residual_value_pct", 0.0)),
                    0.05,
                    key=_wkey("bat_residual"),
                )

                from emos_light.components.battery import Battery as _Bat
                _bat = _Bat("bat_preview", config["battery"])
                st.caption(
                    f"Nutzkapazitaet: **{_bat.usable_capacity_kwh:.1f} kWh** | "
                    f"eta_rt: **{_bat.roundtrip_efficiency*100:.0f}%** | "
                    f"Alterungskosten: **{_bat.aging_cost_ct_per_kwh:.1f} ct/kWh**"
                )

    # Waermepumpe & SG-Ready
    _hp_container = st.container(key=_wkey("hp_section"))
    with _hp_container, st.expander("Waermepumpe & SG-Ready", expanded=False):
        st.caption(f"Modell: {config['heat_pump'].get('model', 'Vaillant aroTHERM plus VWL 105/8.1 A')}")
        config["heat_pump"]["enabled"] = st.checkbox("WP aktiviert", value=config["heat_pump"].get("enabled", True), key=_wkey("hp_en"))
        if config["heat_pump"]["enabled"]:
            hp_col1, hp_col2 = st.columns(2)
            config["heat_pump"]["max_electrical_power_kw"] = hp_col1.number_input("Max. el. Leistung (kW)", 1.0, 30.0, float(config["heat_pump"]["max_electrical_power_kw"]), 0.5)
            config["heat_pump"]["min_electrical_power_kw"] = hp_col2.number_input("Min. el. Leistung (kW)", 0.5, 5.0, float(config["heat_pump"].get("min_electrical_power_kw", 1.0)), 0.5)
            hp_col3, hp_col4 = st.columns(2)
            config["heat_pump"]["flow_temp_heating_c"] = hp_col3.number_input(
                "VL-Temp Heizkreis (C)", 25.0, 55.0,
                float(config["heat_pump"].get("flow_temp_heating_c", 35.0)), 1.0,
                help="Vorlauftemperatur FBH — bestimmt COP Heizung (niedrig = besser)",
            )
            config["heat_pump"]["flow_temp_dhw_c"] = hp_col4.number_input(
                "VL-Temp Warmwasser (C)", 45.0, 70.0,
                float(config["heat_pump"].get("flow_temp_dhw_c", 55.0)), 1.0,
                help="Vorlauftemperatur WW-Bereitung — bestimmt COP WW",
            )

            config["heat_pump"]["max_starts_per_day"] = int(st.number_input(
                "Max. Einschaltvorgaenge pro Tag",
                min_value=0, max_value=48,
                value=int(config["heat_pump"].get("max_starts_per_day", 8)),
                step=1, key=_wkey("hp_max_starts"),
                help=(
                    "Verdichter-Schonung: jedes OFF->ON belastet den "
                    "Verdichter. Umschalten zwischen Heizkreis und WW "
                    "zaehlt nicht, solange die WP an bleibt. "
                    "0 = keine Begrenzung."
                ),
            ))

            config["heat_pump"]["sg_ready"] = st.checkbox(
                "SG-Ready aktiviert (BWP v1.1)",
                value=config["heat_pump"].get("sg_ready", True),
                key=_wkey("sg_en"),
                help=(
                    "Vier Schaltzustaende nach Vaillant Elektro-Kompendium:\n"
                    "1 = Zwangsabschaltung, 2 = Normal,\n"
                    "3 = Einschaltempfehlung (WW-Boost), "
                    "4 = Zwangseinschaltung (WW + Pufferspeicher-Boost)."
                ),
            )
            if config["heat_pump"]["sg_ready"]:
                sg_col1, sg_col2 = st.columns(2)
                config["heat_pump"]["sg_ready_temp_raise_state3_c"] = sg_col1.number_input(
                    "Zustand 3: WW-Sollwert-Ueberhoehung (K)", 0.0, 20.0,
                    float(config["heat_pump"].get("sg_ready_temp_raise_state3_c", 5.0)),
                    1.0,
                    help=(
                        "Einmalige WW-Speicherladung mit angehobenem Sollwert. "
                        "Estrich bleibt unveraendert (Pufferspeicher wird bei "
                        "sg3 ohne Waermeanforderung nicht beladen)."
                    ),
                )
                config["heat_pump"]["sg_ready_temp_raise_state4_c"] = sg_col2.number_input(
                    "Zustand 4: Pufferspeicher-Offset (K)", 0.0, 20.0,
                    float(config["heat_pump"].get("sg_ready_temp_raise_state4_c", 10.0)),
                    1.0,
                    help=(
                        "Zwangseinschaltung: WW + Estrich-Pufferspeicher werden "
                        "ueberhoeht. Muss > Zustand-3-Wert sein (BWP v1.1)."
                    ),
                )
                config["heat_pump"]["sg_ready_min_hold_minutes"] = int(st.number_input(
                    "Min. Haltezeit SG-Zustand (min)", 0, 60,
                    int(config["heat_pump"].get("sg_ready_min_hold_minutes", 10)), 5,
                    key=_wkey("sg_min_hold"),
                    help="Mindestdauer, fuer die ein Nicht-Normal-Zustand gehalten wird.",
                ))

    # WW-Speicher & Frischwasserstation
    _ww_container = st.container(key=_wkey("ww_section"))
    with _ww_container, st.expander("WW-Speicher & Frischwasserstation", expanded=False):
        col_ww, col_fws = st.columns(2)
        with col_ww:
            st.markdown("**Warmwasserspeicher**")
            config["hot_water_storage"]["enabled"] = st.checkbox("WW-Speicher aktiviert", value=config["hot_water_storage"].get("enabled", True), key=_wkey("ww_en"))
            if config["hot_water_storage"]["enabled"]:
                config["hot_water_storage"]["volume_liters"] = st.number_input("Volumen (L)", 50, 2000, int(config["hot_water_storage"]["volume_liters"]), 50)
                ww_temp = st.slider(
                    "Temp.-Bereich (C)", 30, 90,
                    (int(config["hot_water_storage"]["min_temperature_c"]),
                     int(config["hot_water_storage"]["max_temperature_c"])),
                    key=_wkey("ww_temp"),
                )
                config["hot_water_storage"]["min_temperature_c"] = float(ww_temp[0])
                config["hot_water_storage"]["max_temperature_c"] = float(ww_temp[1])

                # Komforttemperatur
                config["hot_water_storage"]["comfort_temperature_c"] = st.number_input(
                    "Komforttemperatur (C)", float(ww_temp[0]), float(ww_temp[1]),
                    float(config["hot_water_storage"].get("comfort_temperature_c", 55.0)), 1.0,
                    help="Mindesttemperatur waehrend Komfort-Zeitraeumen",
                )
                st.caption(f"Mindesttemp.: **{ww_temp[0]} C** (immer) | Komforttemp.: **{config['hot_water_storage']['comfort_temperature_c']:.0f} C** (in Komfort-Zeitraeumen)")

                # Komfort-Zeitraeume
                st.markdown("**Komfort-Zeitraeume** (Speicher wird auf Komforttemp. gehalten)")
                comfort_periods = config["hot_water_storage"].get("comfort_periods", [
                    {"start_hour": 5, "end_hour": 9},
                    {"start_hour": 17, "end_hour": 22},
                ])
                new_periods = []
                for i, period in enumerate(comfort_periods):
                    cp_col1, cp_col2, cp_col3 = st.columns([2, 2, 1])
                    start_h = cp_col1.number_input(f"Von (Uhr)", 0, 23, int(period.get("start_hour", 6)), key=_wkey(f"cp_start_{i}"))
                    end_h = cp_col2.number_input(f"Bis (Uhr)", 0, 24, int(period.get("end_hour", 22)), key=_wkey(f"cp_end_{i}"))
                    remove = cp_col3.checkbox("X", key=_wkey(f"cp_rm_{i}"), help="Zeitraum entfernen")
                    if not remove:
                        new_periods.append({"start_hour": start_h, "end_hour": end_h})
                if st.button("+ Zeitraum hinzufuegen", key=_wkey("add_cp")):
                    new_periods.append({"start_hour": 12, "end_hour": 14})
                config["hot_water_storage"]["comfort_periods"] = new_periods

                from emos_light.components.thermal_storage import ThermalStorage as _TS
                _ww = _TS("ww_preview", config["hot_water_storage"])
                st.caption(f"Kapazitaet: **{_ww.capacity_kwh:.1f} kWh** | Verlust (50%): **{_ww.standby_loss_w_at_mean:.0f} W**")

        with col_fws:
            st.markdown("**Frischwasserstation**")
            config["fresh_water_station"]["enabled"] = st.checkbox("FWS aktiviert", value=config["fresh_water_station"].get("enabled", True), key=_wkey("fws_en"))
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
    _bldg_container = st.container(key=_wkey("building_section"))
    with _bldg_container, st.expander("Fussbodenheizung & Gebaeude", expanded=False):
        col_ufh, col_bldg = st.columns(2)
        with col_ufh:
            st.markdown("**Fussbodenheizung**")
            config["underfloor_heating"]["enabled"] = st.checkbox("FBH aktiviert", value=config["underfloor_heating"].get("enabled", True), key=_wkey("ufh_en"))
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
                    key=_wkey("floor_temp"),
                )
                config["underfloor_heating"]["floor_temp_min_c"] = float(floor_temp[0])
                config["underfloor_heating"]["floor_temp_max_c"] = float(floor_temp[1])

                from emos_light.components.underfloor_heating import UnderfloorHeating as _UFH
                # Modell EMOS Light (Mai 2026): nur der Estrich als Speicher,
                # Wand und Luft werden bewusst vernachlaessigt.
                _ufh = _UFH("ufh_preview", config["underfloor_heating"])
                st.caption(
                    f"C_Estrich: **{_ufh.capacity_kwh_per_k:.2f} kWh/K** | "
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
            config["building"]["heated_area_m2"] = st.number_input(
                "Beheizte Flaeche (m²)", 30, 500,
                int(config["building"]["heated_area_m2"]), 10,
            )
            config["building"]["num_occupants"] = st.number_input("Bewohner", 1, 10, int(config["building"]["num_occupants"]))

            # Geometrie-Eingaben (Gebaeudegruppe Mai 2026)
            geo_col1, geo_col2, geo_col3 = st.columns(3)
            config["building"]["length_m"] = geo_col1.number_input(
                "Laenge l (m)", 5.0, 50.0,
                float(config["building"].get("length_m", 15.0)), 0.5,
            )
            config["building"]["width_m"] = geo_col2.number_input(
                "Breite b (m)", 5.0, 50.0,
                float(config["building"].get("width_m", 10.0)), 0.5,
            )
            config["building"]["height_m"] = geo_col3.number_input(
                "Hoehe h (m)", 2.0, 15.0,
                float(config["building"].get("height_m", 2.5)), 0.1,
            )
            # Fensterflaeche: optional manuell, sonst 15%-Heuristik
            cur_window = config["building"].get("window_area_m2")
            wall_gross_preview = (
                2 * config["building"]["height_m"]
                * (config["building"]["length_m"] + config["building"]["width_m"])
            )
            window_default = (
                float(cur_window) if cur_window is not None else 0.15 * wall_gross_preview
            )
            config["building"]["window_area_m2"] = st.number_input(
                "Fensterflaeche A_F (m²)", 0.0, 500.0,
                window_default, 1.0,
                help="Default: 15 % der Bruttowandflaeche (typisch fuer EFH).",
            )

            # U-Werte (Gebaeudegruppe-Defaults)
            uw_col1, uw_col2, uw_col3 = st.columns(3)
            config["building"]["u_value_wall_w_m2_k"] = uw_col1.number_input(
                "U Wand W/(m²K)", 0.05, 2.0,
                float(config["building"].get("u_value_wall_w_m2_k", 0.2)), 0.05,
            )
            config["building"]["u_value_window_w_m2_k"] = uw_col2.number_input(
                "U Fenster W/(m²K)", 0.5, 5.0,
                float(config["building"].get("u_value_window_w_m2_k", 0.9)), 0.1,
            )
            config["building"]["u_value_roof_floor_w_m2_k"] = uw_col3.number_input(
                "U Dach+Boden W/(m²K)", 0.1, 2.0,
                float(config["building"].get("u_value_roof_floor_w_m2_k", 0.4)), 0.05,
            )

            t_col1, t_col2 = st.columns(2)
            config["building"]["reference_temp_c"] = t_col1.number_input(
                "Referenztemperatur T_ref (°C)", 15.0, 25.0,
                float(config["building"].get("reference_temp_c", 22.0)), 0.5,
                help="Bezugstemperatur fuer die Speicherenergie Q_Gebaeude.",
            )
            config["building"]["comfort_min_temp_c"] = t_col2.number_input(
                "Komfort-Untergrenze T_min (°C)", 14.0, 22.0,
                float(config["building"].get("comfort_min_temp_c", 21.0)), 0.5,
                help="Wenn das Gebaeude unter T_min faellt, wird die WP "
                     "spaetestens hier wieder eingeschaltet.",
            )

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

            # Live-Vorschau: UA, C_Estrich, tau, t_aus
            # (Wand wird im Modell als Speicher bewusst vernachlaessigt.)
            _bldg = _B("bldg_preview", config["building"])
            ua_trans = _bldg.transmission_ua_w_per_k
            ua_lueft = _bldg.ventilation_ua_w_per_k
            ua_total = _bldg.total_ua_w_per_k
            c_estrich = _bldg.screed_capacity_kwh_per_k

            st.caption(
                f"**UA**: Trans **{ua_trans:.0f}** + Lueft **{ua_lueft:.0f}** "
                f"= **{ua_total:.0f} W/K**  |  "
                f"**C_Estrich**: **{c_estrich:.2f} kWh/K**  "
                f"_(Wand vernachlaessigt — siehe Modellannahme)_"
            )

            # Beispielszenarien fuer tau und t_aus
            t_in_ref = float(config["building"].get("reference_temp_c", 22.0))
            t_out_examples = [-10.0, 0.0, 10.0]
            tau_str = "  |  ".join(
                f"T_a={ta:>4.0f}°C → τ={_bldg.time_constant_h(t_in_ref, ta):.1f} h, "
                f"t_aus={_bldg.cooldown_time_h(t_in_ref, ta):.1f} h"
                for ta in t_out_examples
            )
            st.caption(f"**Bei T_innen={t_in_ref}°C:**  {tau_str}")

    # Verbrauch
    _cons_container = st.container(key=_wkey("consumption_section"))
    with _cons_container, st.expander("Verbrauch", expanded=False):
        from emos_light.data.household_profiles import list_profiles, get_profile_label

        # Personenanzahl + Jahresverbrauch
        v_col1, v_col2, v_col3 = st.columns(3)

        profiles = list_profiles()  # [(id, label, base_annual_kwh), ...]
        profile_ids = [pid for pid, _, _ in profiles]
        profile_labels = [lbl for _, lbl, _ in profiles]

        current_pid = config["household"].get("load_profile_id", profile_ids[0])
        if current_pid not in profile_ids:
            current_pid = profile_ids[0]
        current_idx = profile_ids.index(current_pid)

        chosen_label = v_col1.selectbox(
            "Personenanzahl (Lastprofil)",
            profile_labels,
            index=current_idx,
            help="Vermessenes Lastprofil je Haushaltskonstellation. Wird linear "
                 "auf den eingestellten Jahresverbrauch skaliert. Profile sind "
                 "ohne Waermepumpenanteil.",
        )
        chosen_pid = profile_ids[profile_labels.index(chosen_label)]
        config["household"]["load_profile_id"] = chosen_pid

        config["household"]["annual_consumption_kwh"] = v_col2.number_input(
            "Jahresstromverbrauch (kWh)",
            500, 50000,
            int(config["household"]["annual_consumption_kwh"]), 500,
            help="Zielwert. Das gewaehlte Profil wird linear auf diesen "
                 "Jahresverbrauch hoch- oder runterskaliert.",
        )

        # Hinweis auf Original-Jahreswert des gewaehlten Profils
        base_annual = next(
            (ann for pid, _, ann in profiles if pid == chosen_pid), 0.0
        )
        if base_annual > 0:
            scale = config["household"]["annual_consumption_kwh"] / base_annual
            v_col3.metric(
                "Skalierungsfaktor",
                f"{scale:.2f} ×",
                help=f"Profil-Original: {base_annual:.0f} kWh/a "
                     f"({chosen_label})",
            )

        # Waermebedarfe darunter in eigener Zeile
        h_col1, h_col2 = st.columns(2)
        h_col1.metric("Heizwaerme (kWh/a)", config["heat_demand"]["annual_heating_kwh"])
        h_col2.metric("Warmwasser (kWh/a)", config["heat_demand"]["annual_hot_water_kwh"])

    # E-Mobilitaet
    # Versionierter Container (siehe PV-Sektion): forciert das frische
    # Mounten aller Wallbox/EV-Widgets nach Config-Import.
    _em_container = st.container(key=_wkey("emobility_section"))
    with _em_container, st.expander("E-Mobilitaet", expanded=False):
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
                wb["enabled"] = st.checkbox(f"{wb.get('name', f'Wallbox {i+1}')} aktiviert", value=wb.get("enabled", False), key=_wkey(f"wb_{i}_en"))
                if wb["enabled"]:
                    wb["name"] = st.text_input("Name", wb.get("name", f"Wallbox {i+1}"), key=_wkey(f"wb_{i}_name"))
                    wb["max_power_kw"] = st.number_input("Max. Ladeleistung (kW)", 1.4, 22.0, float(wb["max_power_kw"]), 0.5, key=_wkey(f"wb_{i}_power"))
                if st.button("Wallbox entfernen", key=_wkey(f"wb_{i}_rm")):
                    st.session_state["_wb_rm_idx"] = i
                    st.rerun()
                st.divider()

            if st.button("+ Wallbox hinzufuegen", key=_wkey("add_wb")):
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
                ev["enabled"] = st.checkbox(f"{ev.get('name', f'E-Auto {i+1}')} aktiviert", value=ev.get("enabled", False), key=_wkey(f"ev_{i}_en"))
                if ev["enabled"]:
                    ev["name"] = st.text_input("Name", ev.get("name", f"E-Auto {i+1}"), key=_wkey(f"ev_{i}_name"))
                    ev["battery_capacity_kwh"] = st.number_input("Akkukapazitaet (kWh)", 10.0, 200.0, float(ev.get("battery_capacity_kwh", 58.0)), 5.0, key=_wkey(f"ev_{i}_cap"))
                    ev["current_soc"] = st.slider("Aktueller SOC (%)", 0, 100, int(ev.get("current_soc", 0.3)*100), key=_wkey(f"ev_{i}_soc")) / 100
                    ev["consumption_kwh_per_100km"] = st.number_input(
                        "Verbrauch (kWh/100km)", 5.0, 40.0,
                        float(ev.get("consumption_kwh_per_100km", 16.0)), 0.5,
                        key=_wkey(f"ev_{i}_cons"),
                        help="Realer Fahrverbrauch inkl. Ladeverluste. Typ.: Kleinwagen ~14, Kompakt ~16, Mittelklasse ~18, SUV ~21 kWh/100km.",
                    )

                    # ---- Mindestreichweite (garantiertes Ladeziel) ----
                    st.info(
                        "ℹ️ **Hinweis zur Mindestreichweite:** "
                        "Das garantierte Laden auf eine vorgegebene Reichweite "
                        "setzt voraus, dass Fahrzeug und Wallbox den aktuellen "
                        "Ladezustand (SOC) miteinander kommunizieren — "
                        "ueblicherweise ueber ISO 15118 oder herstellerspezifische "
                        "Protokolle. Steht diese Kommunikation nicht zur Verfuegung, "
                        "deaktivieren Sie die Mindestreichweite. Das Fahrzeug wird "
                        "dann ausschliesslich im konfigurierten unteren Strompreis-"
                        "Perzentil mit voller Leistung geladen."
                    )
                    ev["min_range_enabled"] = st.checkbox(
                        "Mindestreichweite garantieren",
                        value=bool(ev.get("min_range_enabled", True)),
                        key=_wkey(f"ev_{i}_minrange_en"),
                        help=(
                            "An: bis Abfahrt wird mindestens die unten "
                            "konfigurierte Reichweite garantiert. "
                            "Aus: keine Garantie — das Fahrzeug laedt nur "
                            "im Strompreis-Perzentil unten."
                        ),
                    )
                    ev["min_range_km"] = st.number_input(
                        "Mindestreichweite (km)", 0.0, 500.0,
                        float(ev.get("min_range_km", 150.0)), 10.0,
                        key=_wkey(f"ev_{i}_range"),
                        disabled=not ev["min_range_enabled"],
                    )
                    if ev["min_range_enabled"]:
                        target_soc = min(
                            1.0,
                            ev["min_range_km"] * ev.get("consumption_kwh_per_100km", 16.0)
                            / 100 / ev["battery_capacity_kwh"],
                        )
                        ev["target_soc"] = max(ev["current_soc"], target_soc)
                        st.caption(f"Ziel-SOC: **{ev['target_soc']*100:.0f}%**")
                    else:
                        # Ohne Mindestreichweite: target_soc auf current_soc,
                        # damit energy_needed_kwh = 0 — relevant fuer Logs/KPIs.
                        ev["target_soc"] = ev["current_soc"]
                        st.caption(
                            "_Mindestreichweite ist deaktiviert — Ziel-SOC "
                            "wird nicht erzwungen._"
                        )

                    ev_col1, ev_col2 = st.columns(2)
                    # 0..24 erlaubt — 24 bedeutet "Mitternacht" und ist semantisch
                    # gleichwertig zu 0 (z.B. Ankunft 18 / Abfahrt 24 = anwesend
                    # 18:00..23:59).
                    ev["arrival_hour"] = ev_col1.number_input(
                        "Ankunft (h)", 0, 24,
                        int(ev.get("arrival_hour", 17)), key=_wkey(f"ev_{i}_arr"),
                    )
                    ev["departure_hour"] = ev_col2.number_input(
                        "Abfahrt (h)", 0, 24,
                        int(ev.get("departure_hour", 7)), key=_wkey(f"ev_{i}_dep"),
                    )
                    ev["driving_loss_pct_per_hour"] = st.number_input(
                        "Fahrverbrauch (% SOC / h Abwesenheit)",
                        min_value=0.0, max_value=50.0,
                        value=float(ev.get("driving_loss_pct_per_hour", 5.0)),
                        step=0.5,
                        key=_wkey(f"ev_{i}_drv_loss"),
                        help=(
                            "Pro Stunde Abwesenheit verliert der Akku diesen "
                            "Anteil der Kapazitaet (Pendelverbrauch). Bei 60 "
                            "kWh und 5 %/h entspricht das 3 kWh/h ≈ 15 kWh/"
                            "100km bei 60 km/h. Der Wert wird auch an die "
                            "verlinkte Wallbox weitergereicht."
                        ),
                    )

                    wb_names = [wb.get("name") for wb in config.get("wallboxes", []) if wb.get("enabled")]
                    if wb_names:
                        linked = ev.get("linked_wallbox", wb_names[0])
                        idx = wb_names.index(linked) if linked in wb_names else 0
                        ev["linked_wallbox"] = st.selectbox("Wallbox", wb_names, index=idx, key=_wkey(f"ev_{i}_wb"))

                    # ---- Preisgesteuerte Ladestrategie (Strompreis-Perzentil) ----
                    st.info(
                        "ℹ️ **Hinweis zur Bezugsgroesse:** Das Perzentil bezieht "
                        "sich auf den Strompreis **innerhalb der Anwesenheits"
                        "stunden Ihres Fahrzeugs** — nicht auf den ganzen Tag. "
                        "Bei 25 % wird also in den guenstigsten 25 % der Stunden "
                        "geladen, in denen das Auto an der Wallbox steht. "
                        "Dadurch sind immer Lade-Slots verfuegbar, auch wenn die "
                        "Anwesenheit zufaellig in eine teure Tageszeit faellt."
                    )
                    pct_default = float(ev.get("charge_only_below_percentile_pct", 100.0))
                    ev["charge_only_below_percentile_pct"] = st.slider(
                        "Strompreis-Perzentil zum Laden (%)",
                        min_value=10, max_value=100,
                        value=int(round(pct_default)),
                        step=5,
                        key=_wkey(f"ev_{i}_pct"),
                        help=(
                            "Erlaubt das Laden nur in den guenstigsten X %% der "
                            "**Anwesenheitsstunden**. 100 %% = keine Beschraen"
                            "kung. Niedrigere Werte = strikter (bei 25 %% darf "
                            "nur in den guenstigsten 25 %% der Anwesenheits"
                            "stunden geladen werden)."
                        ),
                    )
                    if ev["charge_only_below_percentile_pct"] < 100:
                        st.caption(
                            f"→ Laden nur in den **guenstigsten "
                            f"{ev['charge_only_below_percentile_pct']:.0f} %** "
                            f"der Anwesenheitsstunden."
                        )
                    elif not ev["min_range_enabled"]:
                        st.warning(
                            "⚠️ Mindestreichweite aus und Perzentil = 100 %: "
                            "das Fahrzeug wuerde in jedem Anwesenheits-Slot "
                            "mit voller Leistung laden. Empfehlung: Perzentil "
                            "auf < 100 % setzen."
                        )

                if st.button("E-Auto entfernen", key=_wkey(f"ev_{i}_rm")):
                    st.session_state["_ev_rm_idx"] = i
                    st.rerun()
                st.divider()

            if st.button("+ E-Auto hinzufuegen", key=_wkey("add_ev")):
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
                        # Akku-Obergrenze (Akkuschutz / 100 % Default)
                        wb["max_soc"] = ev.get("max_soc", 1.0)
                        wb["arrival_hour"] = ev.get("arrival_hour", 17)
                        wb["departure_hour"] = ev.get("departure_hour", 7)
                        # Mindestreichweite-Garantie (Constraint an/aus)
                        wb["min_range_enabled"] = bool(
                            ev.get("min_range_enabled", True)
                        )
                        # Preissensitive Ladestrategie (Ersatz fuer V2H)
                        wb["charge_only_below_percentile_pct"] = ev.get(
                            "charge_only_below_percentile_pct", 100.0
                        )
                        # Fahrverbrauch (SOC-Verlust pro Abwesenheitsstunde)
                        wb["driving_loss_pct_per_hour"] = float(
                            ev.get("driving_loss_pct_per_hour", 5.0)
                        )


# ================================================================
# Tab 2: Eingabedaten
# ================================================================
with tab_input:
    st.subheader("Eingabedaten laden und visualisieren")

    if st.button("Daten laden", type="primary", key=_wkey("load_data")):
        with st.spinner("Lade Daten..."):
            try:
                data = load_input_data(
                    config, opt_date, use_real_data,
                    csv_upload.getvalue() if csv_upload else None,
                    csv_includes_hp,
                )
                st.session_state["input_data"] = data
                eff_h = data.get("horizon_hours", data["num_steps"] * data["step_minutes"] / 60)
                st.success(
                    f"Daten geladen: {data['num_steps']} Zeitschritte "
                    f"({eff_h:.0f} h)"
                )
                # Hinweis, falls der Horizont wegen fehlender
                # Day-Ahead-Preise geschrumpft wurde.
                if data.get("horizon_shrunk"):
                    st.info(
                        f"ℹ️ Day-Ahead-Preise fuer den Folgetag sind noch "
                        f"nicht publiziert (EPEX-SPOT-Auktion laeuft typ. "
                        f"bis ~13 Uhr Ortszeit). Der Horizont wurde von "
                        f"{int(data['configured_horizon_hours'])} h auf "
                        f"{int(eff_h)} h verkuerzt — es wird nur ueber den "
                        f"Zeitraum optimiert, fuer den echte Marktpreise "
                        f"vorliegen."
                    )
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
        # Temperatur und Einstrahlung haben sehr unterschiedliche Bereiche
        # (typ. 0–30 °C vs. 0–1000 W/m²) — daher separate Y-Achsen im
        # gleichen Subplot.
        fig_pv = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            subplot_titles=("Temperatur & Einstrahlung", "PV-Erzeugung"),
            specs=[[{"secondary_y": True}], [{}]],
        )
        fig_pv.add_trace(
            go.Scatter(x=ts, y=data["temp"], name="Temperatur (°C)",
                       line=dict(color="orange")),
            row=1, col=1, secondary_y=False,
        )
        fig_pv.add_trace(
            go.Scatter(x=ts, y=data["ghi"], name="GHI (W/m²)",
                       line=dict(color="gold")),
            row=1, col=1, secondary_y=True,
        )
        fig_pv.add_trace(
            go.Scatter(x=ts, y=data["pv_generation"], name="PV (kW)",
                       fill="tozeroy", line=dict(color="goldenrod")),
            row=2, col=1,
        )
        # Achsen-Titel und sinnvolle Bereiche pro Groesse
        fig_pv.update_yaxes(title_text="Temperatur (°C)",
                            row=1, col=1, secondary_y=False)
        fig_pv.update_yaxes(title_text="GHI (W/m²)", rangemode="tozero",
                            row=1, col=1, secondary_y=True)
        fig_pv.update_yaxes(title_text="PV (kW)", row=2, col=1)
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

    if st.button("Optimierung starten", type="primary", key=_wkey("run_opt")):
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
                # Day-Ahead-Verfuegbarkeit: wenn der Horizont geschrumpft
                # wurde, das Banner einmal hier anzeigen (analog zum
                # Eingabedaten-Tab), damit der Nutzer es auch sieht, wenn
                # er die Optimierung ohne separates "Daten laden" startet.
                if data.get("horizon_shrunk"):
                    st.info(
                        f"ℹ️ Day-Ahead-Preise fuer den Folgetag sind noch "
                        f"nicht publiziert. Optimiere nur ueber "
                        f"{int(data.get('horizon_hours', 24))} h "
                        f"(konfiguriert: {int(data.get('configured_horizon_hours', 48))} h)."
                    )

                # Komponenten und Optimizer erstellen
                components = build_components(config)
                optimizer = build_optimizer(components)

                # Optimierung
                if opt_mode == "Day-Ahead (MILP)":
                    result = optimizer.optimize(inp)
                elif opt_mode == "MPC (rollierend)":
                    mpc = MPCController(optimizer, mpc_horizon_hours, mpc_execute_hours)
                    result = mpc.run_mpc(inp)
                else:  # Baseline
                    result = run_baseline(inp, config)

                # Baseline-Vergleich (entfaellt, wenn Baseline selbst ausgewaehlt)
                if opt_mode == "Baseline (regelbasiert)":
                    result.baseline_cost_eur = result.total_cost_eur
                    result.savings_eur = 0.0
                    result.savings_pct = 0.0
                else:
                    baseline_cost = calculate_baseline_cost(inp, config)
                    result.baseline_cost_eur = baseline_cost
                    if baseline_cost > 0:
                        result.savings_eur = baseline_cost - result.total_cost_eur
                        result.savings_pct = (
                            result.savings_eur / baseline_cost
                        ) * 100

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
        st.markdown(f"### Ergebnisse — {opt_mode}")
        if opt_mode == "Baseline (regelbasiert)":
            st.info(
                "Baseline ist ein **regelbasierter Vergleichsmodus** ohne "
                "Preisoptimierung:\n\n"
                "- **Waermepumpe**: schaltet sich erst ein, wenn eine "
                "**Komfort-Untergrenze** unterschritten wird "
                "(Estrich- oder WW-Speicher-Temperatur, in Komfortzeiten "
                "auch die hoehere Soll-Temperatur). Laeuft dann mit voller "
                "Leistung, bis die Obergrenze erreicht ist. WW-Speicher "
                "hat Vorrang vor Estrich.\n"
                "- **Wallbox**: laedt sofort bei Ankunft mit voller "
                "Leistung, bis das EV abfaehrt — kein Preisfilter.\n"
                "- **Batterie**: laedt PV-Ueberschuss, entlaedt bei "
                "Restbedarf — keine Preisarbitrage.\n\n"
                "Diese naive Strategie dient als Referenz, gegen die "
                "MILP/MPC ihre Einsparung messen."
            )
        kpi_row1 = st.columns(4)
        kpi_row1[0].metric("Gesamtkosten", f"{result.total_cost_eur:.2f} EUR")
        kpi_row1[1].metric("Eigenverbrauch", f"{result.eigenverbrauch_pct:.1f}%")
        kpi_row1[2].metric("Autarkie", f"{result.autarkie_pct:.1f}%")
        if (
            opt_mode != "Baseline (regelbasiert)"
            and result.savings_eur is not None
        ):
            kpi_row1[3].metric(
                "Einsparung",
                f"{result.savings_eur:.2f} EUR ({result.savings_pct:.0f}%)",
            )

        kpi_row2 = st.columns(4)
        kpi_row2[0].metric("Netzbezugskosten", f"{result.grid_buy_cost_eur:.2f} EUR")
        kpi_row2[1].metric("Einspeiseverguetung", f"{result.feed_in_revenue_eur:.2f} EUR")
        kpi_row2[2].metric("PV-Ertrag", f"{result.pv_total_kwh:.1f} kWh")
        kpi_row2[3].metric("Netzbezug", f"{result.grid_buy_total_kwh:.1f} kWh")

        # Batterie-Alterungs-KPIs (PDF Speichergruppe)
        if config.get("battery", {}).get("enabled") and result.battery_throughput_kwh > 0:
            kpi_row3 = st.columns(4)
            kpi_row3[0].metric(
                "Batterie-Durchsatz",
                f"{result.battery_throughput_kwh:.1f} kWh",
            )
            kpi_row3[1].metric(
                "Aequiv. Zyklen heute",
                f"{result.battery_equivalent_cycles:.2f}",
            )
            kpi_row3[2].metric(
                "Alterungskosten heute",
                f"{result.battery_aging_cost_eur:.2f} EUR",
            )
            # Geschaetzte Rest-Lebensdauer in Jahren
            if result.battery_equivalent_cycles > 0:
                efc = float(config["battery"].get("equivalent_full_cycles", 6000))
                years = efc / (result.battery_equivalent_cycles * 365.0)
                kpi_row3[3].metric(
                    "Gesch. Lebensdauer",
                    f"{years:.1f} Jahre",
                )
            else:
                kpi_row3[3].metric("Gesch. Lebensdauer", "-")

        # WP-Einschaltvorgaenge (Verdichter-Schonung — siehe heat_pump.py).
        # Anzeige pro Kalendertag; eine Tagessumme ueber den Horizont waere
        # irrefuehrend, weil das Limit per Tag, nicht pro Horizont gilt.
        if (
            config.get("heat_pump", {}).get("enabled")
            and getattr(result, "hp_starts_per_day", None)
        ):
            max_starts = int(
                config.get("heat_pump", {}).get("max_starts_per_day", 8)
            )
            days = sorted(result.hp_starts_per_day.keys())
            per_day = [result.hp_starts_per_day[d] for d in days]
            with st.container():
                st.markdown(
                    "**WP-Einschaltvorgaenge** "
                    "(Schonung des Verdichters — Umschalten Heizkreis ↔ WW "
                    "zaehlt nicht):"
                )
                cols = st.columns(max(2, len(days)))
                for i, (d, c) in enumerate(zip(days, per_day)):
                    delta_str = (
                        f"max {max_starts}" if max_starts > 0 else "ohne Limit"
                    )
                    cols[i].metric(
                        d.strftime("%d.%m."), f"{c}", delta=delta_str,
                        delta_color="off",
                    )

        # ---- Planungshorizont ----
        # Visualisiert, wie weit die Optimierung in die Zukunft schaut und
        # welcher Teil tatsaechlich umgesetzt wird:
        #   - Day-Ahead/Baseline: ein einziges Fenster ueber den gesamten
        #     Eingangshorizont (z.B. 24 h oder 48 h).
        #   - MPC: pro Iteration ein Balken; dunkler Teil = Ausfuehrung,
        #     hellerer Teil = Planungs-Lookahead. Der dynamische Day-Ahead-
        #     Horizont (vor 13 Uhr Tagesende heute, ab 13 Uhr Tagesende
        #     morgen) ist hier direkt ablesbar.
        if result.planning_windows:
            st.markdown("### Planungshorizont")
            windows = result.planning_windows
            ts_list = list(ts)
            n_steps = len(ts_list)
            step_min_horizon = (
                inp.step_minutes if inp is not None
                else data.get("step_minutes", 15)
            )

            fig_horizon = go.Figure()

            def _ts_at(idx: int):
                """Step-Index in datetime — auch fuer den exklusiven Endindex
                am Datenende (per Schritt-Offset extrapoliert)."""
                if idx < n_steps:
                    return ts_list[idx]
                # Endindex == n_steps: einen Schritt ueber das letzte ts hinaus
                return ts_list[-1] + datetime.timedelta(
                    minutes=step_min_horizon
                )

            for i, w in enumerate(windows):
                start_ts = _ts_at(w["start_step"])
                exec_end_ts = _ts_at(w["exec_end_step"])
                horizon_end_ts = _ts_at(w["horizon_end_step"])
                horizon_h = (
                    horizon_end_ts - start_ts
                ).total_seconds() / 3600.0

                # Ausfuehrungs-Anteil (dunkler Balken)
                fig_horizon.add_trace(go.Scatter(
                    x=[start_ts, exec_end_ts], y=[i, i],
                    mode="lines",
                    line=dict(color="royalblue", width=14),
                    name="Ausfuehrungsfenster",
                    showlegend=(i == 0),
                    hovertemplate=(
                        f"Iter {i + 1}<br>"
                        "Ausfuehrung: %{x|%d.%m %H:%M}<extra></extra>"
                    ),
                ))
                # Planungs-Lookahead (heller Balken, falls vorhanden)
                if w["horizon_end_step"] > w["exec_end_step"]:
                    fig_horizon.add_trace(go.Scatter(
                        x=[exec_end_ts, horizon_end_ts], y=[i, i],
                        mode="lines",
                        line=dict(color="lightblue", width=14),
                        name="Planungs-Lookahead",
                        showlegend=(i == 0),
                        hovertemplate=(
                            f"Iter {i + 1}<br>"
                            f"Horizont: {horizon_h:.1f} h<br>"
                            "Ende: %{x|%d.%m %H:%M}<extra></extra>"
                        ),
                    ))

            # 13:00-Marker (Day-Ahead-Publikation) — pro Tag im Zeitraum.
            # Achtung: ``add_vline`` mit annotation_text rechnet intern
            # einen Mittelwert der x-Koordinaten und scheitert bei
            # datetime-Werten ("int + datetime"). Wir nutzen daher
            # ``add_shape`` + ``add_annotation`` getrennt — beide
            # akzeptieren datetimes problemlos.
            tmin_plot, tmax_plot = ts_list[0], _ts_at(
                max(w["horizon_end_step"] for w in windows)
            )
            day = tmin_plot.date()
            while datetime.datetime.combine(day, datetime.time(0)) <= tmax_plot:
                marker = datetime.datetime.combine(day, datetime.time(13, 0))
                if tmin_plot <= marker <= tmax_plot:
                    fig_horizon.add_shape(
                        type="line",
                        x0=marker, x1=marker,
                        xref="x", yref="paper",
                        y0=0, y1=1,
                        line=dict(color="orange", dash="dash"),
                    )
                    fig_horizon.add_annotation(
                        x=marker, y=1.0,
                        xref="x", yref="paper",
                        text="13:00",
                        showarrow=False,
                        yanchor="bottom",
                        font=dict(color="orange", size=10),
                    )
                day += datetime.timedelta(days=1)

            # Mitternacht-Marker, zur visuellen Tagesgrenze
            day = tmin_plot.date() + datetime.timedelta(days=1)
            while datetime.datetime.combine(day, datetime.time(0)) <= tmax_plot:
                midnight = datetime.datetime.combine(day, datetime.time(0))
                fig_horizon.add_shape(
                    type="line",
                    x0=midnight, x1=midnight,
                    xref="x", yref="paper",
                    y0=0, y1=1,
                    line=dict(color="gray", dash="dot"),
                )
                day += datetime.timedelta(days=1)

            n_win = len(windows)
            fig_horizon.update_layout(
                height=max(160, 80 + 22 * n_win),
                yaxis=dict(
                    title="Iteration",
                    tickmode="array",
                    tickvals=list(range(n_win)),
                    ticktext=[f"#{i + 1}" for i in range(n_win)],
                    autorange="reversed",
                ),
                xaxis=dict(title=""),
                margin=dict(t=30, b=30),
                hovermode="closest",
                showlegend=(n_win <= 1 or opt_mode == "MPC (rollierend)"),
            )
            st.plotly_chart(fig_horizon, use_container_width=True)

            # Caption mit Kennzahlen
            max_horizon_h = max(
                (
                    _ts_at(w["horizon_end_step"]) - _ts_at(w["start_step"])
                ).total_seconds() / 3600.0
                for w in windows
            )
            mode_hint = (
                "Day-Ahead-MILP: ein Fenster ueber den gesamten Horizont."
                if opt_mode == "Day-Ahead (MILP)"
                else (
                    "Baseline: kein Lookahead — die Regel reagiert "
                    "schrittweise auf den Zustand."
                    if opt_mode == "Baseline (regelbasiert)"
                    else f"MPC: {n_win} Iterationen, "
                    f"max. Lookahead {max_horizon_h:.1f} h. "
                    "13:00 = Day-Ahead-Publikation (EPEX SPOT), ab dann "
                    "reicht der MPC-Horizont bis Tagesende **morgen**."
                )
            )
            st.caption(mode_hint)

        # Elektrische Leistungsbilanz
        st.markdown("### Elektrische Leistungsbilanz")
        # Drei Subplots:
        #   Row 1: Leistung (kW)
        #   Row 2: Batterie-SOC (% links, kWh rechts — synchron)
        #   Row 3: EV-SOC pro Wallbox (nur sichtbar wenn mind. ein EV aktiv)
        # Plot-Aufbau setzt das EV-SOC-Subplot immer mit auf, damit die
        # Layout-Indizes stabil bleiben — wir blenden den Plot dynamisch ein.
        wb_traces = list(result.wallbox_power_kw.items())
        has_evs = len(wb_traces) > 0
        if has_evs:
            fig_el = make_subplots(
                rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                subplot_titles=("Leistung (kW)", "Batterie SOC", "E-Auto SOC"),
                row_heights=[0.55, 0.225, 0.225],
                specs=[[{}], [{"secondary_y": True}], [{"secondary_y": True}]],
            )
        else:
            fig_el = make_subplots(
                rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                subplot_titles=("Leistung (kW)", "Batterie SOC"),
                row_heights=[0.7, 0.3],
                specs=[[{}], [{"secondary_y": True}]],
            )

        if inp is not None:
            fig_el.add_trace(go.Scatter(x=ts, y=inp.pv_generation_kw, name="PV", fill="tozeroy", line=dict(color="gold")), row=1, col=1)
        fig_el.add_trace(go.Scatter(x=ts, y=result.grid_buy_kw, name="Netzbezug", line=dict(color="red")), row=1, col=1)
        fig_el.add_trace(go.Scatter(x=ts, y=-result.grid_sell_kw, name="Einspeisung", line=dict(color="green")), row=1, col=1)
        if len(result.hp_power_kw) > 0:
            fig_el.add_trace(go.Scatter(x=ts, y=result.hp_power_kw, name="WP", line=dict(color="orange")), row=1, col=1)
            # T-abhaengige Max-Leistung als gestrichelte Hilfslinie
            # (Mai 2026): zeigt, dass die WP nicht immer 8 kW kann,
            # sondern nur das, was Kennfeld + Aussentemperatur hergeben.
            if hasattr(result, "hp_max_power_kw") and len(result.hp_max_power_kw) > 0:
                fig_el.add_trace(
                    go.Scatter(
                        x=ts, y=result.hp_max_power_kw,
                        name="WP max (T-abh.)",
                        line=dict(color="orange", dash="dash", width=1),
                        opacity=0.6,
                    ),
                    row=1, col=1,
                )
        for wb_name, wb_arr in result.wallbox_power_kw.items():
            fig_el.add_trace(go.Scatter(x=ts, y=wb_arr, name=f"WB {wb_name}", line=dict(color="cyan")), row=1, col=1)
        if inp is not None:
            fig_el.add_trace(go.Scatter(x=ts, y=inp.household_load_kw, name="Haushalt", line=dict(color="blue", dash="dot")), row=1, col=1)

        if len(result.batt_soc_kwh) > 0:
            capacity_kwh = float(config["battery"]["capacity_kwh"])
            # SOC in % zeichnen (primaere Achse links). Die sekundaere Achse
            # rechts wird parallel auf [0, capacity_kwh] gesetzt, sodass die
            # gleiche Kurve auch in kWh ablesbar ist.
            soc_pct = (result.batt_soc_kwh / capacity_kwh) * 100.0 if capacity_kwh > 0 else result.batt_soc_kwh * 0
            fig_el.add_trace(
                go.Scatter(
                    x=ts, y=soc_pct, name="Batterie SOC",
                    fill="tozeroy", line=dict(color="purple"),
                    hovertemplate=(
                        "%{x|%H:%M}<br>"
                        "SOC: %{y:.1f} %<br>"
                        "= %{customdata:.2f} kWh<extra></extra>"
                    ),
                    customdata=result.batt_soc_kwh,
                ),
                row=2, col=1, secondary_y=False,
            )
            # Achsen: links %, rechts kWh — beide synchron auf [0, max]
            fig_el.update_yaxes(
                title_text="SOC (%)", range=[0, 100],
                row=2, col=1, secondary_y=False,
            )
            fig_el.update_yaxes(
                title_text="SOC (kWh)", range=[0, capacity_kwh],
                row=2, col=1, secondary_y=True,
            )

        # --- EV-SOC-Trajektorien (Row 3) ---
        # Bevorzugt nutzen wir die explizite SOC-Trajektorie aus dem
        # Result (``result.ev_soc_kwh[name]``) — sowohl MILP als auch
        # Baseline fuehren den SOC inzwischen als Zustandsvariable bzw.
        # Tracker mit (inkl. 5 %/h Verlust waehrend Abwesenheit). Ohne
        # diese Trajektorie (alte Ergebnisse, externe Quellen) fallen
        # wir auf Power-Integration zurueck.
        if has_evs:
            dt_h_plot = data["step_minutes"] / 60.0
            steps_per_hour = max(1, 60 // data["step_minutes"])
            n_steps = len(ts)
            # Wallbox.__init__ normalisiert Namen (Leerzeichen/Bindestriche zu '_'),
            # daher kann der Result-Key vom Originalnamen abweichen.
            def _safe(n: str) -> str:
                return n.replace(" ", "_").replace("-", "_")
            # Mapping: linked_wallbox-Name (Original) → EV-Eintrag
            ev_by_wb: dict = {}
            for ev in config.get("electric_vehicles", []):
                if ev.get("enabled"):
                    ev_by_wb[ev.get("linked_wallbox")] = ev
            # Pro Wallbox SOC integrieren
            ev_palette = ["cyan", "deepskyblue", "lightskyblue", "steelblue"]
            ref_capacity: float | None = None
            soc_trajectories = getattr(result, "ev_soc_kwh", {}) or {}
            for wi, (wb_result_name, wb_power) in enumerate(wb_traces):
                # Originale Wallbox-Cfg ueber safe-Name finden
                wb_cfg = next(
                    (w for w in config.get("wallboxes", [])
                     if _safe(w.get("name", "")) == wb_result_name),
                    {},
                )
                ev_cfg = ev_by_wb.get(wb_cfg.get("name"), {})
                cap = float(ev_cfg.get("battery_capacity_kwh",
                                       wb_cfg.get("ev_battery_capacity_kwh", 60.0)))
                eff = float(wb_cfg.get("charging_efficiency", 0.92))
                soc0 = float(ev_cfg.get("current_soc",
                                        wb_cfg.get("current_soc", 0.3)))
                arrival = int(wb_cfg.get("arrival_hour", 17))
                departure = int(wb_cfg.get("departure_hour", 7))

                # Anwesenheitsmaske (gleiche Konvention wie Wallbox._is_ev_present)
                presence = np.array([
                    (arrival <= ((t // steps_per_hour) % 24) < departure)
                    if arrival <= departure
                    else (
                        ((t // steps_per_hour) % 24) >= arrival
                        or ((t // steps_per_hour) % 24) < departure
                    )
                    for t in range(n_steps)
                ])

                if wb_result_name in soc_trajectories:
                    # Explizite Trajektorie aus dem Optimizer/Baseline —
                    # zeigt Lade- UND Verlustphasen (5 %/h waehrend
                    # Abwesenheit) durchgehend.
                    soc_kwh = np.asarray(
                        soc_trajectories[wb_result_name], dtype=float,
                    )
                else:
                    # Fallback: Power-Integration, nur waehrend Anwesenheit
                    soc_kwh = np.full(n_steps, np.nan)
                    e = soc0 * cap
                    for t in range(n_steps):
                        if presence[t]:
                            e = min(cap, e + wb_power[t] * dt_h_plot * eff)
                            soc_kwh[t] = e
                soc_pct = (soc_kwh / cap) * 100.0 if cap > 0 else soc_kwh * 0
                color = ev_palette[wi % len(ev_palette)]

                # Linien-Split: durchgezogen wenn EV anwesend, gestrichelt
                # wenn unterwegs. Transition-Punkte landen in BEIDEN
                # Arrays, sodass die Linien nahtlos ineinandergreifen
                # (sonst klafft eine Luecke zwischen letztem present-Punkt
                # und erstem absent-Punkt).
                solid_y = np.where(presence, soc_pct, np.nan)
                dashed_y = np.where(~presence, soc_pct, np.nan)
                # boundary stitching: an jeder Mask-Aenderung beide Arrays
                # an genau diesem Index sichtbar machen
                for t in range(1, n_steps):
                    if presence[t] != presence[t - 1]:
                        solid_y[t] = soc_pct[t]
                        dashed_y[t] = soc_pct[t]

                hovertpl = (
                    "%{x|%H:%M}<br>"
                    "SOC: %{y:.1f} %<br>"
                    "= %{customdata:.2f} kWh<extra></extra>"
                )

                # Anwesend (solid)
                fig_el.add_trace(
                    go.Scatter(
                        x=ts, y=solid_y,
                        name=f"EV SOC ({wb_name})",
                        line=dict(color=color),
                        connectgaps=False,
                        hovertemplate=hovertpl,
                        customdata=soc_kwh,
                    ),
                    row=3, col=1, secondary_y=False,
                )
                # Unterwegs (dashed) — gleiche Farbe, gleiche Legend-Group
                # damit der User per Legend-Klick beide gemeinsam ein-/
                # ausblenden kann; Trace selbst nicht in der Legende.
                fig_el.add_trace(
                    go.Scatter(
                        x=ts, y=dashed_y,
                        name=f"EV SOC ({wb_name}) — Fahrt",
                        line=dict(color=color, dash="dash"),
                        legendgroup=f"ev_soc_{wb_name}",
                        showlegend=False,
                        connectgaps=False,
                        hovertemplate=hovertpl,
                        customdata=soc_kwh,
                    ),
                    row=3, col=1, secondary_y=False,
                )
                if ref_capacity is None:
                    ref_capacity = cap
            fig_el.update_yaxes(
                title_text="SOC (%)", range=[0, 100],
                row=3, col=1, secondary_y=False,
            )
            if len(wb_traces) == 1:
                # Nur 1 EV → kWh-Achse synchron sinnvoll
                fig_el.update_yaxes(
                    title_text="SOC (kWh)",
                    range=[0, ref_capacity],
                    row=3, col=1, secondary_y=True,
                )
            else:
                # Mehrere EVs mit ggf. verschiedenen Kapazitaeten → kWh-Achse
                # waere mehrdeutig; wir verstecken sie.
                fig_el.update_yaxes(
                    visible=False,
                    row=3, col=1, secondary_y=True,
                )

        fig_el.update_layout(
            height=600 if has_evs else 500,
            margin=dict(t=40),
        )
        st.plotly_chart(fig_el, use_container_width=True)

        # Thermische Uebersicht
        st.markdown("### Thermische Uebersicht")
        # Raumtemperatur ist seit Mai 2026 eine MILP-Zustandsvariable
        # (nur befuellt, wenn Building aktiviert ist).
        has_room = len(result.indoor_temp_c) > 0
        has_floor = len(result.floor_temp_c) > 0
        has_ww = len(result.ww_storage_temp_c) > 0
        n_thermal_rows = int(has_room) + int(has_floor) + int(has_ww) + 1

        fig_th = make_subplots(
            rows=n_thermal_rows, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            subplot_titles=(
                (["Raumtemperatur (C)"] if has_room else [])
                + (["Estrich-Temperatur (C)"] if has_floor else [])
                + (["WW-Speicher-Temperatur (C)"] if has_ww else [])
                + ["Waermestroeme (kW)"]
            ),
        )

        row_idx = 1
        if has_room:
            building_cfg = config.get("building", {})
            indoor_init = building_cfg.get("indoor_temp_c", 21.0)
            comfort_min = building_cfg.get("comfort_temp_min_c",
                                           building_cfg.get("comfort_min_temp_c", 21.0))
            comfort_max = building_cfg.get("comfort_temp_max_c", indoor_init + 3.0)
            fig_th.add_trace(go.Scatter(
                x=ts, y=result.indoor_temp_c, name="T_innen",
                line=dict(color="tomato", width=2),
            ), row=row_idx, col=1)
            # Wandtemperatur T_W (3-Speicher-Modell, ETH Juni 2026) — der
            # traege Speicher zwischen Raum und Aussenluft. Nur vorhanden,
            # wenn der Wandknoten aktiv ist.
            if len(result.wall_temp_c) > 0:
                fig_th.add_trace(go.Scatter(
                    x=ts, y=result.wall_temp_c, name="T_Wand",
                    line=dict(color="sienna", width=1, dash="dot"),
                ), row=row_idx, col=1)
            fig_th.add_hline(
                y=comfort_min, line_dash="dash", line_color="gray",
                annotation_text=f"Komfort min {comfort_min:.0f} C",
                row=row_idx, col=1,
            )
            fig_th.add_hline(
                y=comfort_max, line_dash="dash", line_color="gray",
                annotation_text=f"Komfort max {comfort_max:.0f} C",
                row=row_idx, col=1,
            )
            row_idx += 1
        if has_floor:
            ufh_cfg = config.get("underfloor_heating", {})
            fig_th.add_trace(go.Scatter(x=ts, y=result.floor_temp_c, name="Estrich", fill="tozeroy", line=dict(color="purple")), row=row_idx, col=1)
            fig_th.add_hline(y=ufh_cfg.get("floor_temp_min_c", 20), line_dash="dash", line_color="gray", row=row_idx, col=1)
            fig_th.add_hline(y=ufh_cfg.get("floor_temp_max_c", 26), line_dash="dash", line_color="gray", row=row_idx, col=1)
            row_idx += 1

        if has_ww:
            ww_cfg = config.get("hot_water_storage", {})
            fig_th.add_trace(go.Scatter(x=ts, y=result.ww_storage_temp_c, name="WW-Speicher", fill="tozeroy", line=dict(color="steelblue")), row=row_idx, col=1)
            fig_th.add_hline(y=ww_cfg.get("min_temperature_c", 40), line_dash="dash", line_color="red", annotation_text="Minimum", row=row_idx, col=1)

            # Komfortband als Shading anzeigen
            comfort_temp = ww_cfg.get("comfort_temperature_c", 0)
            comfort_periods = ww_cfg.get("comfort_periods", [])
            if comfort_temp > 0 and comfort_periods and len(ts) > 0:
                import datetime
                comfort_min_temps = []
                for t_stamp in ts:
                    hour = t_stamp.hour + t_stamp.minute / 60.0 if hasattr(t_stamp, 'hour') else 0
                    in_comfort = False
                    for cp in comfort_periods:
                        s, e = cp.get("start_hour", 0), cp.get("end_hour", 24)
                        if s <= e:
                            in_comfort = in_comfort or (s <= hour < e)
                        else:
                            in_comfort = in_comfort or (hour >= s or hour < e)
                    comfort_min_temps.append(comfort_temp if in_comfort else ww_cfg.get("min_temperature_c", 40))
                fig_th.add_trace(go.Scatter(
                    x=ts, y=comfort_min_temps, name="Min-Temp (Komfort)",
                    mode="lines", line=dict(color="orange", width=1, dash="dot"),
                    fill=None,
                ), row=row_idx, col=1)
            row_idx += 1

        if len(result.q_floor_kw) > 0:
            fig_th.add_trace(go.Scatter(x=ts, y=result.q_floor_kw, name="Q FBH (WP -> Estrich)", fill="tozeroy", line=dict(color="orange")), row=row_idx, col=1)
        if len(result.q_ww_kw) > 0:
            fig_th.add_trace(go.Scatter(x=ts, y=result.q_ww_kw, name="Q WW (WP -> Speicher)", fill="tonexty", line=dict(color="cyan")), row=row_idx, col=1)
        # q_floor_to_room und heat_loss (Mai 2026) ohne Fuellung, sonst
        # ueberdecken sie die WP-Waermestroeme oben.
        if len(result.q_floor_to_room_kw) > 0:
            fig_th.add_trace(go.Scatter(
                x=ts, y=result.q_floor_to_room_kw, name="Q Estrich -> Raum",
                line=dict(color="tomato", width=1.5),
            ), row=row_idx, col=1)
        if len(result.heat_loss_kw) > 0:
            fig_th.add_trace(go.Scatter(
                x=ts, y=result.heat_loss_kw, name="Q Verlust (Raum -> Aussen)",
                line=dict(color="dimgray", width=1.5, dash="dot"),
            ), row=row_idx, col=1)
        # Solare + interne Raumgewinne Q_g,R (Gebaeudegruppe Juni 2026)
        if len(result.room_gain_kw) > 0:
            fig_th.add_trace(go.Scatter(
                x=ts, y=result.room_gain_kw, name="Q Gewinn (solar + intern)",
                line=dict(color="goldenrod", width=1.5),
            ), row=row_idx, col=1)

        fig_th.update_layout(height=150 * n_thermal_rows + 100, margin=dict(t=40))
        st.plotly_chart(fig_th, use_container_width=True)

        # SG-Ready Zustand (BWP v1.1) — vier Schaltzustaende:
        #  1 = Zwangsabschaltung   (K1:K2 = 1:0)
        #  2 = Normalbetrieb       (K1:K2 = 0:0)
        #  3 = Einschaltempfehlung (K1:K2 = 0:1, WW-Boost)
        #  4 = Zwangseinschaltung  (K1:K2 = 1:1, WW + Pufferspeicher-Boost)
        # Panel wird immer gerendert, wenn SG-Ready in der Config
        # aktiviert ist und das Result eine Zustandsreihe enthaelt —
        # auch wenn der Solver durchgehend Zustand 2 waehlt (typisch
        # ausserhalb der Heizsaison). Eine Caption macht den Solver-
        # Befund explizit, damit der User nicht im Dunkeln tappt.
        sg_enabled = config.get("heat_pump", {}).get("sg_ready", False)
        if sg_enabled and len(result.sg_ready_state) > 0:
            st.markdown("### SG-Ready Zustand (BWP v1.1)")
            states_arr = np.asarray(result.sg_ready_state, dtype=int)
            # Plot mit Step-Shape "hv" — diskrete Zustaende, Stufen halten
            # bis zum naechsten Wechsel. Farben pro Zustand: rot Abschaltung,
            # neutral Normal, hellblau Einschaltempfehlung, dunkelblau
            # Zwangseinschaltung. Damit fallen einzelne Spikes selbst bei
            # kurzer Dauer sofort ins Auge.
            state_color = {
                1: "#d62728",   # rot
                2: "#7f7f7f",   # grau
                3: "#1f77b4",   # blau
                4: "#08306b",   # dunkelblau
            }
            state_name = {
                1: "Abschaltung",
                2: "Normal",
                3: "Einschaltempf.",
                4: "Zwangseinsch.",
            }
            fig_sg = go.Figure()
            # Eine durchgehende Step-Linie als Hintergrund
            fig_sg.add_trace(go.Scatter(
                x=ts, y=states_arr,
                mode="lines",
                line=dict(color="#cccccc", width=1, shape="hv"),
                showlegend=False,
                hoverinfo="skip",
            ))
            # Pro Zustand 1/3/4 eine farbige Marker-Serie nur an den
            # Punkten, an denen dieser Zustand aktiv ist. Macht auch
            # einzelne Schritte deutlich sichtbar.
            for s in (1, 3, 4):
                mask = states_arr == s
                if mask.sum() == 0:
                    continue
                fig_sg.add_trace(go.Scatter(
                    x=[ts[i] for i, m in enumerate(mask) if m],
                    y=[s] * int(mask.sum()),
                    mode="markers",
                    marker=dict(
                        color=state_color[s], size=10, symbol="square",
                    ),
                    name=f"{s} {state_name[s]}",
                    hovertemplate=(
                        f"Zustand {s} — {state_name[s]}<br>"
                        "%{x|%d.%m %H:%M}<extra></extra>"
                    ),
                ))
            # Optionale "Normal"-Marker fuer Komplettheit, klein und grau
            mask2 = states_arr == 2
            if mask2.sum() > 0:
                fig_sg.add_trace(go.Scatter(
                    x=[ts[i] for i, m in enumerate(mask2) if m],
                    y=[2] * int(mask2.sum()),
                    mode="markers",
                    marker=dict(color=state_color[2], size=4, symbol="circle"),
                    name="2 Normal", showlegend=True,
                    hovertemplate="Zustand 2 — Normal<br>%{x|%d.%m %H:%M}<extra></extra>",
                ))
            fig_sg.update_layout(
                yaxis=dict(
                    tickvals=[1, 2, 3, 4],
                    ticktext=[
                        "1 Abschaltung",
                        "2 Normal",
                        "3 Einschaltempf.",
                        "4 Zwangseinsch.",
                    ],
                    range=[0.5, 4.5],
                ),
                height=260,
                margin=dict(t=30),
                hovermode="closest",
            )
            st.plotly_chart(fig_sg, use_container_width=True)

            # Solver-Befund als Caption: welche Zustaende wurden wie lange
            # gewaehlt? Zeigt insbesondere, wenn durchgehend Normalbetrieb
            # gewaehlt wurde — sonst wirkt das Panel "kaputt" (leere
            # Variation), obwohl der Solver es bewusst entschieden hat.
            import collections as _coll
            counts = _coll.Counter(int(v) for v in states_arr)
            total = sum(counts.values())
            step_min = (
                inp.step_minutes if inp is not None
                else data.get("step_minutes", 15)
            )
            labels = {
                1: "Zwangsabschaltung",
                2: "Normalbetrieb",
                3: "Einschaltempfehlung",
                4: "Zwangseinschaltung",
            }
            parts = [
                f"**{labels[s]}**: {counts[s] * step_min / 60:.1f} h "
                f"({counts[s] / total * 100:.0f} %)"
                for s in (1, 2, 3, 4) if counts[s] > 0
            ]
            if counts[2] == total:
                st.caption(
                    "ℹ️ Der Solver entschied sich ueber den gesamten "
                    "Horizont fuer Normalbetrieb (Zustand 2). Typisch "
                    "ausserhalb der Heizsaison oder bei sehr "
                    "gleichmaessigem Strompreisprofil — kein Anreiz "
                    "fuer eine Speicher-Ueberhoehung."
                )
            else:
                st.caption(" · ".join(parts))

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
            # Preis-Achse: immer bei 0 ct beginnen, damit Lade-/Entlade-
            # Entscheidungen relativ zum echten Nullpunkt lesbar sind.
            # rangemode="tozero" laesst die Range bei negativen Preisen
            # automatisch nach unten erweitern (also bis zum echten Minimum).
            fig_overlay.update_yaxes(
                title_text="ct/kWh", rangemode="tozero", secondary_y=True,
            )
            st.plotly_chart(fig_overlay, use_container_width=True)
