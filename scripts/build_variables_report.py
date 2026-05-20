"""Erzeugt eine PDF-Uebersicht aller MILP-Variablen pro Komponente.

Pro Komponente: Konfigurations-Inputs, Entscheidungsvariablen,
beigesteuerte Constraints, im Ergebnis zurueckgegebene Groessen.
"""

import io
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
    Table, TableStyle, KeepTogether,
)
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT


# ----------------------------------------------------------------------
# Equation rendering
# ----------------------------------------------------------------------

def eq_image(latex: str, fontsize: int = 12, dpi: int = 220) -> Image:
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.patch.set_alpha(0.0)
    fig.text(0, 0, f"${latex}$", fontsize=fontsize, color="black")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi,
                bbox_inches="tight", pad_inches=0.05, transparent=True)
    plt.close(fig)
    buf.seek(0)
    from PIL import Image as PILImage
    pil = PILImage.open(buf)
    w_pt = pil.size[0] * 72.0 / dpi
    h_pt = pil.size[1] * 72.0 / dpi
    buf.seek(0)
    img = Image(buf, width=w_pt, height=h_pt)
    img.hAlign = "LEFT"
    return img


# ----------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------

styles = getSampleStyleSheet()

styles.add(ParagraphStyle(
    name="BodyDE", parent=styles["BodyText"], alignment=TA_JUSTIFY,
    fontSize=10, leading=13.5, spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="H1", parent=styles["Heading1"], fontSize=18, leading=22,
    spaceBefore=0, spaceAfter=8, textColor=colors.HexColor("#0b3d91"),
))
styles.add(ParagraphStyle(
    name="H2", parent=styles["Heading2"], fontSize=13, leading=16,
    spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#143f7a"),
))
styles.add(ParagraphStyle(
    name="Cell", parent=styles["BodyText"], fontSize=8.5, leading=11,
    alignment=TA_LEFT, spaceAfter=0,
))
styles.add(ParagraphStyle(
    name="CellMono", parent=styles["BodyText"], fontName="Courier",
    fontSize=8.5, leading=11, alignment=TA_LEFT, spaceAfter=0,
))
styles.add(ParagraphStyle(
    name="Caption", parent=styles["BodyText"], fontSize=8.5, leading=11,
    textColor=colors.HexColor("#555"), alignment=TA_JUSTIFY, spaceAfter=8,
))


def P(text, style="BodyDE"):
    return Paragraph(text, styles[style])


def cell(text, mono=False):
    return Paragraph(text, styles["CellMono" if mono else "Cell"])


def H1(text):
    return Paragraph(text, styles["H1"])


def H2(text):
    return Paragraph(text, styles["H2"])


# ----------------------------------------------------------------------
# Table builders
# ----------------------------------------------------------------------

HEADER_BG = colors.HexColor("#0b3d91")
SUBHEADER_BG = colors.HexColor("#e8eef9")
ROW_ALT = colors.HexColor("#f5f7fc")


def make_table(header, rows, col_widths):
    """Standardtabelle mit blauer Header-Zeile."""
    data = [header] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaa")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    t.setStyle(TableStyle(style))
    return t


def vars_table(rows):
    """Tabelle: Variablenname | Symbol | Typ | Bereich | Bedeutung"""
    header = [
        cell("<b>Variable (Code)</b>"),
        cell("<b>Symbol</b>"),
        cell("<b>Typ</b>"),
        cell("<b>Wertebereich</b>"),
        cell("<b>Bedeutung</b>"),
    ]
    table_rows = []
    for code, sym, typ, rng, mean in rows:
        table_rows.append([
            cell(code, mono=True),
            cell(sym),
            cell(typ),
            cell(rng),
            cell(mean),
        ])
    return make_table(
        header, table_rows,
        [3.5 * cm, 2.4 * cm, 2.0 * cm, 3.4 * cm, 5.7 * cm],
    )


def config_table(rows):
    """Tabelle: Parameter | Default | Bedeutung"""
    header = [cell("<b>Konfigurationsparameter</b>"),
              cell("<b>Default</b>"),
              cell("<b>Bedeutung</b>")]
    table_rows = [
        [cell(name, mono=True), cell(default, mono=True), cell(desc)]
        for name, default, desc in rows
    ]
    return make_table(header, table_rows,
                      [5.5 * cm, 2.0 * cm, 9.5 * cm])


def constr_table(rows):
    """Tabelle: Constraint-Name | Aussage"""
    header = [cell("<b>Constraint</b>"), cell("<b>Aussage</b>")]
    table_rows = [
        [cell(name, mono=True), cell(desc)]
        for name, desc in rows
    ]
    return make_table(header, table_rows, [5.5 * cm, 11.5 * cm])


def output_table(rows):
    """Tabelle: Ergebnisfeld | Einheit | Bedeutung"""
    header = [cell("<b>Ergebnisfeld</b>"),
              cell("<b>Einheit</b>"),
              cell("<b>Bedeutung</b>")]
    table_rows = [
        [cell(name, mono=True), cell(unit), cell(desc)]
        for name, unit, desc in rows
    ]
    return make_table(header, table_rows, [5.5 * cm, 2.0 * cm, 9.5 * cm])


# ----------------------------------------------------------------------
# Page header / footer
# ----------------------------------------------------------------------

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666"))
    canvas.drawString(2 * cm, 1.2 * cm,
                      "EMOS Light — Variablen- und Komponenten-Uebersicht")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Seite {doc.page}")
    if doc.page > 1:
        canvas.setStrokeColor(colors.HexColor("#bbb"))
        canvas.setLineWidth(0.4)
        canvas.line(2 * cm, A4[1] - 1.6 * cm, A4[0] - 2 * cm, A4[1] - 1.6 * cm)
    canvas.restoreState()


# ----------------------------------------------------------------------
# Cover and intro
# ----------------------------------------------------------------------

def build_cover():
    return [
        Spacer(1, 4 * cm),
        Paragraph("EMOS Light",
                  ParagraphStyle("CovTop", parent=styles["Title"],
                                 fontSize=32, leading=38,
                                 textColor=colors.HexColor("#0b3d91"),
                                 alignment=1)),
        Spacer(1, 0.4 * cm),
        Paragraph("MILP-Variablen pro Komponente",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=20, leading=24,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.6 * cm),
        Paragraph(
            "Was jede Komponente an Konfigurations-Inputs braucht, "
            "welche Entscheidungs­variablen und Nebenbedingungen sie "
            "in das MILP einbringt und welche Ergebnis­größen "
            "im Output erscheinen.",
            ParagraphStyle("CovSub2", parent=styles["BodyText"],
                           fontSize=11, leading=15,
                           textColor=colors.HexColor("#555"), alignment=1),
        ),
        Spacer(1, 6 * cm),
        Paragraph("Projektarbeit EMOS Light",
                  ParagraphStyle("CovMeta", parent=styles["BodyText"],
                                 fontSize=11, alignment=1,
                                 textColor=colors.HexColor("#444"))),
        Paragraph("Stand: Mai 2026",
                  ParagraphStyle("CovMeta2", parent=styles["BodyText"],
                                 fontSize=10, alignment=1,
                                 textColor=colors.HexColor("#777"))),
        PageBreak(),
    ]


def build_intro():
    out = []
    out.append(H1("Lese-Anleitung"))
    out.append(P(
        "Pro Komponente folgen vier Blöcke:"
    ))
    out.append(P(
        "<b>(1) Konfigurations-Inputs</b> — Felder aus der YAML / dem Dashboard, "
        "die der Nutzer einstellt. Diese werden NICHT optimiert; sie sind "
        "Parameter."
    ))
    out.append(P(
        "<b>(2) Entscheidungs-Variablen</b> — was der Solver für diese "
        "Komponente bestimmen soll. Pro Zeitschritt t = 0, ..., N-1 entsteht "
        "je eine Variable. Bei N=96 (24 h, 15-min) ergeben sich also pro "
        "Variablen-Eintrag 96 einzelne Solver-Variablen."
    ))
    out.append(P(
        "<b>(3) Beigesteuerte Constraints</b> — lineare Ungleichungen "
        "und Gleichungen, die diese Komponente zum Modell beiträgt."
    ))
    out.append(P(
        "<b>(4) Ergebnis-Output</b> — Zeitreihen, die nach erfolgreicher "
        "Lösung im OptimizationResult-Objekt zurückgegeben werden."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(H2("Komponenten-Uebersicht"))
    overview_rows = [
        [cell("PV-Anlage"),       cell("Quelle"),    cell("Erzeugungsprognose (passiv, keine Variablen)")],
        [cell("Batterie"),        cell("Speicher"),  cell("Lade/Entlade/SOC + Logik-Binär")],
        [cell("Wärmepumpe"), cell("Wandler"),   cell("Leistung, SG-Ready 1/2/3/4 (einziger Steuerkanal), hp_on, hp_start, Tageslimit Einschaltvorgaenge")],
        [cell("Estrich (FBH)"),   cell("Speicher"),  cell("Energie + Wärmezufuhr + Q Estrich→Raum")],
        [cell("Pufferspeicher"),  cell("Speicher"),  cell("Energie + Q_in/Q_demand + Legionellen-Binary")],
        [cell("Frischwasserst."), cell("Wandler"),   cell("Bedarfsmodifikator (passiv)")],
        [cell("Wallbox"),         cell("Senke"),     cell("Leistung + Aktiv-Binaer + EV-SOC-Zustandsvariable (Ziel-SOC, 5%/h Fahrverbrauch)")],
        [cell("E-Auto"),          cell("Parameter"), cell("liefert Wallbox-Konfig (passiv)")],
        [cell("Gebäude (Raum)"),  cell("Speicher"),  cell("T_innen-Zustandsvariable + Komfortband-Slacks (MILP seit Mai 2026)")],
        [cell("Netz (Kern)"),     cell("Anschluss"), cell("Bezug/Einspeisung + Binär-Disjunktion")],
    ]
    t = make_table(
        [cell("<b>Komponente</b>"), cell("<b>Rolle</b>"), cell("<b>Variablen-Charakter</b>")],
        overview_rows,
        [4.5 * cm, 3.0 * cm, 9.5 * cm],
    )
    out.append(t)
    out.append(Paragraph(
        "<i>Passiv</i> bedeutet: die Komponente erstellt selbst keine "
        "MILP-Variablen, liefert aber Parameter / Zeitreihen, die in "
        "Constraints anderer Komponenten oder in die Knotenbilanz eingehen.",
        styles["Caption"],
    ))
    out.append(PageBreak())
    return out


# ----------------------------------------------------------------------
# Component sections
# ----------------------------------------------------------------------

def section_grid():
    out = [H1("1. Netz (Kern-Optimierer)")]
    out.append(P(
        "Wird vom Optimierer immer angelegt — unabhängig von den "
        "Komponenten. Modelliert den Hausanschluss als Doppelvariable "
        "Bezug/Einspeisung mit Binär-Disjunktion."
    ))

    out.append(H2("Inputs (aus Konfiguration)"))
    out.append(config_table([
        ("max_grid_power_kw", "25.0",
         "Netzanschlussleistung in kW (Obergrenze fuer Bezug und Einspeisung)."),
        ("prices_ct_kwh[t]", "Zeitreihe",
         "Dynamischer Strompreis je Zeitschritt in ct/kWh (Day-Ahead + Tarif)."),
        ("feed_in_tariff_ct_kwh", "8.2",
         "Einspeiseverguetung (i. d. R. konstant) in ct/kWh."),
        ("household_load_kw[t]", "Zeitreihe",
         "Haushaltslast (P^Last_t in der Knotenbilanz). Quelle: vermessenes "
         "Profil (data/household_profiles, via household.load_profile_id), "
         "eigene CSV oder synthetisches Profil — linear auf "
         "household.annual_consumption_kwh skaliert."),
        ("par14a_enabled / curtailed_steps", "false / []",
         "Optionale Drosselung steuerbarer Verbrauchseinrichtungen."),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Zeitschritt t)"))
    out.append(vars_table([
        ("grid_buy[t]",    "P^buy_t",       "kontinuierlich",
         "[0, max_grid_power_kw]", "Netzbezug in kW"),
        ("grid_sell[t]",   "P^sell_t",      "kontinuierlich",
         "[0, max_grid_power_kw]", "Netzeinspeisung in kW"),
        ("grid_buy_on[t]", "y^buy_t",       "binaer",
         "{0, 1}",                 "1 = Stunde t ist Bezugsstunde"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("grid_buy_link_{t}",
         "P^buy_t ≤ P_max · y^buy_t   (Bezug nur wenn y=1)"),
        ("grid_sell_link_{t}",
         "P^sell_t ≤ P_max · (1 - y^buy_t)   (Einspeisung nur wenn y=0)"),
        ("feed_in_pv_limit_{t}",
         "P^sell_t ≤ P^PV_t   (nur PV darf eingespeist werden)"),
        ("energy_balance_{t}",
         "Knotenbilanz AC: PV + Bezug + Batt-Entl. = Last + Einspeisung + Batt-Lad. + WP + Σ Wallboxen"),
        ("par14a_curtail_{t}",
         "Optional: P^HP_t + Σ P^WB_t ≤ P^14a fuer t ∈ T^14a"),
    ]))

    out.append(H2("Output"))
    out.append(output_table([
        ("grid_buy_kw",  "kW", "Zeitreihe Netzbezug"),
        ("grid_sell_kw", "kW", "Zeitreihe Netzeinspeisung"),
        ("total_cost_eur", "EUR", "Gesamtkosten der Loesung (ohne Alterung)"),
    ]))
    out.append(PageBreak())
    return out


def section_pv():
    out = [H1("2. PV-Anlage (passiv)")]
    out.append(P(
        "Die PV-Anlage wird <b>vor</b> der Optimierung ausgewertet: aus "
        "Standort, Modulparametern und Wetterprognose entsteht eine "
        "Erzeugungs-Zeitreihe P^PV_t, die als Konstante in die Knotenbilanz "
        "eingeht. Sie liefert dem Solver also <b>keine</b> Entscheidungsvariablen."
    ))

    out.append(H2("Inputs (aus Konfiguration)"))
    out.append(config_table([
        ("peak_power_kwp", "10.0", "Peakleistung der Anlage in kWp"),
        ("tilt_deg", "35.0", "Modulneigung in Grad"),
        ("azimuth_deg", "180.0", "Modulausrichtung (180 = Sued)"),
        ("system_efficiency", "0.85", "Systemwirkungsgrad WR + Verkabelung"),
        ("temp_coefficient", "-0.004", "Temperaturkoeffizient pro K"),
        ("noct", "45.0", "Nominal Operating Cell Temperature in C"),
        ("albedo", "0.2", "Bodenreflexion fuer Perez-Modell"),
        ("age_years / degradation_pct_per_year", "0 / 0.5",
         "Modulalterung (mindert Peak)"),
    ]))

    out.append(H2("Entscheidungs-Variablen"))
    out.append(P("<i>Keine</i> — PV-Erzeugung ist eine Eingangs-Zeitreihe."))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(P("<i>Keine</i> direkt; aber Einspeise-Limit "
                 "<font face='Courier'>P^sell_t ≤ P^PV_t</font> wird "
                 "im Kern-Optimierer angesetzt."))

    out.append(H2("Output"))
    out.append(P("PV-Zeitreihe ist Eingang, kein Output. Im "
                 "OptimizationResult dennoch als <font face='Courier'>"
                 "pv_generation_kw</font> mitgefuehrt fuer Visualisierung."))
    out.append(PageBreak())
    return out


def section_battery():
    out = [H1("3. Batteriespeicher")]
    out.append(P(
        "Speicher mit getrennten Lade- und Entladevariablen, SOC-Tracking "
        "und Binär-Disjunktion gegen gleichzeitiges Laden/Entladen."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("capacity_kwh", "10.0", "Brutto-Speicherkapazitaet in kWh"),
        ("max_charge_power_kw", "5.0", "Max. Ladeleistung in kW"),
        ("max_discharge_power_kw", "5.0", "Max. Entladeleistung in kW"),
        ("charge_efficiency", "0.95", "Wirkungsgrad beim Laden"),
        ("discharge_efficiency", "0.95", "Wirkungsgrad beim Entladen"),
        ("min_soc / max_soc", "0.1 / 0.9", "Erlaubtes SoC-Fenster"),
        ("initial_soc", "0.5", "SoC zu t=0"),
        ("replacement_cost_eur_per_kwh", "500.0",
         "Wiederbeschaffungskosten (fuer Alterung)"),
        ("residual_value_pct", "0.0", "Restwert am EOL"),
        ("equivalent_full_cycles", "6000", "Garantierte Aequivalent-Vollzyklen"),
        ("aging_cost_enabled", "true",
         "Alterungskosten in Zielfunktion mit aufnehmen"),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Zeitschritt t)"))
    out.append(vars_table([
        ("batt_charge[t]",     "P^batt,ch_t",  "kontinuierlich",
         "[0, max_charge_power_kw]", "Ladeleistung in kW"),
        ("batt_discharge[t]",  "P^batt,dis_t", "kontinuierlich",
         "[0, max_discharge_power_kw]", "Entladeleistung in kW"),
        ("batt_soc[t]",        "E^batt_t",     "kontinuierlich",
         "[E^min, E^max]", "Energieinhalt in kWh"),
        ("batt_b_charge[t]",   "y^ch_t",       "binaer",
         "{0, 1}", "1 = Laden aktiv"),
        ("batt_b_discharge[t]","y^dis_t",      "binaer",
         "{0, 1}", "1 = Entladen aktiv"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("bat_..._no_simul_{t}",
         "y^ch_t + y^dis_t ≤ 1   (kein gleichzeitiges Laden+Entladen)"),
        ("bat_..._charge_link_{t}",
         "P^batt,ch_t ≤ P_charge_max · y^ch_t"),
        ("bat_..._discharge_link_{t}",
         "P^batt,dis_t ≤ P_discharge_max · y^dis_t"),
        ("bat_..._soc_balance_{t}",
         "E_t = E_{t-1} + η_ch · P_ch_t · Δt - "
         "P_dis_t / η_dis · Δt"),
        ("Zielfunktions-Term",
         "+ (c^age / 2) · Σ (P^ch_t + P^dis_t) Δt   (Alterung)"),
    ]))

    out.append(H2("Output"))
    out.append(output_table([
        ("batt_charge_kw",          "kW",   "Ladeleistung pro Zeitschritt"),
        ("batt_discharge_kw",       "kW",   "Entladeleistung pro Zeitschritt"),
        ("batt_soc_kwh",            "kWh",  "Energieinhalt pro Zeitschritt"),
        ("battery_throughput_kwh",  "kWh",  "Summe |Lade| + |Entlade| ueber Horizont"),
        ("battery_aging_cost_eur",  "EUR",  "Anteilige Alterungskosten der Loesung"),
        ("battery_equivalent_cycles","-",   "Aequivalent-Vollzyklen im Horizont"),
    ]))
    out.append(PageBreak())
    return out


def section_heatpump():
    out = [H1("4. Wärmepumpe")]
    out.append(P(
        "Variable elektrische Leistung mit Modulationsbereich. Seit Mai 2026 "
        "ist SG-Ready (BWP v1.1) der <b>einzige</b> Steuerkanal: vier "
        "Zustaende (1=Zwangsabschaltung, 2=Normal, 3=Einschaltempfehlung, "
        "4=Zwangseinschaltung), genau einer pro Schritt aktiv. y^HP wird "
        "daraus direkt abgeleitet. Zusaetzlich Tageslimit fuer "
        "Einschaltvorgaenge zur Verdichter-Schonung."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("max_electrical_power_kw", "8.0", "Max. elektr. Leistung"),
        ("min_electrical_power_kw", "1.0", "Min. Leistung wenn an (Modulation)"),
        ("flow_temp_heating_c", "35.0", "Vorlauftemp. Heizkreis (FBH)"),
        ("flow_temp_dhw_c", "55.0", "Vorlauftemp. Warmwasser"),
        ("operating_min_temp_c / max_temp_c", "-25 / 43",
         "Aussentemperatur-Betriebsfenster"),
        ("min_run_time_minutes", "15", "Mindestlaufzeit nach Start"),
        ("min_pause_time_minutes", "15", "Mindestpause nach Stopp"),
        ("max_starts_per_day", "8",
         "Max. OFF->ON pro Kalendertag (Verdichter-Schonung; 0 = kein Limit)"),
        ("sg_ready", "true", "SG-Ready-Schnittstelle vorhanden"),
        ("sg_ready_temp_raise_state3_c", "5.0",
         "WW-Soll-Erhoehung in SG3 (Einschaltempfehlung)"),
        ("sg_ready_temp_raise_state4_c", "10.0",
         "WW- + Estrich-Soll-Erhoehung in SG4 (Zwangseinschaltung), >= sg3"),
        ("sg_ready_min_hold_minutes", "10",
         "Mindesthaltezeit fuer SG3/SG4"),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Zeitschritt t)"))
    out.append(vars_table([
        ("hp_on[t]",    "y^HP_t",  "binaer",
         "{0, 1}", "1 = WP an (aus SG-Ready abgeleitet)"),
        ("hp_start[t]", "y^HP,start_t", "binaer",
         "{0, 1}", "OFF->ON-Indikator, geht in Tagessumme"),
        ("hp_power[t]", "P^HP_t",  "kontinuierlich",
         "[0, max_electrical_power_kw]", "Elektrische Gesamtleistung"),
        ("hp_power_floor[t]", "P^HP,Floor_t", "kontinuierlich",
         "[0, max_electrical_power_kw]",
         "Anteil fuer FBH-Pfad (nur wenn beide Senken aktiv)"),
        ("hp_power_ww[t]", "P^HP,WW_t", "kontinuierlich",
         "[0, max_electrical_power_kw]",
         "Anteil fuer WW-Pfad (nur wenn beide Senken aktiv)"),
        ("hp_sg1[t]", "y^SG1_t", "binaer",
         "{0, 1}", "Zwangsabschaltung (EVU-Sperre)"),
        ("hp_sg2[t]", "y^SG2_t", "binaer",
         "{0, 1}", "Normalbetrieb"),
        ("hp_sg3[t]", "y^SG3_t", "binaer",
         "{0, 1}", "Einschaltempfehlung (WW-Boost)"),
        ("hp_sg4[t]", "y^SG4_t", "binaer",
         "{0, 1}", "Zwangseinschaltung (WW + Estrich-Boost)"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("hp_max_power_{t}",   "P^HP_t ≤ P_max · y^HP_t"),
        ("hp_min_power_{t}",   "P^HP_t ≥ P_min · y^HP_t"),
        ("hp_min_run_{t}_{k}", "Mindestlaufzeit: y^HP_t - y^HP_{t-1} ≤ y^HP_{t+k}"),
        ("hp_min_pause_{t}_{k}",
         "Mindestpausenzeit: y^HP_{t-1} - y^HP_t ≤ 1 - y^HP_{t+k}"),
        ("hp_start_link_{t}",
         "y^HP,start_t ≥ y^HP_t - y^HP_{t-1}  (Einschalt-Indikator)"),
        ("hp_max_starts_{day}",
         "Σ_{t in day} y^HP,start_t ≤ N^max,start  (Default 8/Tag)"),
        ("hp_power_split_{t}",
         "P^HP_t = P^HP,Floor_t + P^HP,WW_t   (wenn beide Senken aktiv)"),
        ("heat_to_floor_{t}",
         "Q^Floor,in_t = COP^heiz_t · P^HP,Floor_t"),
        ("heat_to_ww_{t}",
         "Q^WW,in_t = COP^ww_t · P^HP,WW_t"),
        ("sg_one_active_{t}",
         "y^SG1_t + y^SG2_t + y^SG3_t + y^SG4_t = 1  (genau ein Zustand)"),
        ("hp_on_from_sg_{t}",
         "y^HP_t + y^SG1_t = 1  (WP nur per SG1 abschaltbar)"),
        ("sg3_hold_{t}_{k} / sg4_hold_{t}_{k}",
         "Mindesthaltezeiten fuer Einschaltzustaende"),
    ]))

    out.append(H2("Output"))
    out.append(output_table([
        ("hp_power_kw",  "kW",  "Elektrische WP-Leistung pro Zeitschritt"),
        ("sg_ready_state", "1/2/3/4",
         "Resultierender SG-Zustand (1 Aus, 2 Normal, 3 Empfehlung, 4 Zwangsein)"),
        ("hp_starts_per_day", "dict[date,int]",
         "Anzahl OFF->ON-Vorgaenge pro Kalendertag (max max_starts_per_day)"),
        ("hp_starts_count", "int", "Gesamtsumme der Einschaltvorgaenge"),
        ("q_floor_kw",   "kW",  "Thermische Leistung in den Estrich"),
        ("q_ww_kw",      "kW",  "Thermische Leistung in den WW-Speicher"),
    ]))
    out.append(PageBreak())
    return out


def section_underfloor():
    out = [H1("5. Estrich / Fussbodenheizung")]
    out.append(P(
        "Der Estrich ist der einzige thermische Speicher fuer die "
        "Raumheizung — kein separater Heizungs-Pufferspeicher."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("heated_area_m2", "150.0", "Beheizte Flaeche"),
        ("screed_thickness_m", "0.065", "Estrichdicke (Standard 65 mm)"),
        ("screed_density_kg_m3", "2000", "Dichte"),
        ("screed_specific_heat_j_kg_k", "1000", "Spez. Waermekapazitaet"),
        ("floor_surface_coefficient_w_m2_k", "10.0",
         "Waermeuebergang Boden -> Raum"),
        ("supply_temp_max_c", "35.0",
         "Maximale Vorlauftemperatur (begrenzt Q^Floor,max)"),
        ("floor_temp_min_c / max_c", "20.0 / 26.0",
         "Komfortband Bodentemperatur"),
        ("initial_floor_temp_c", "22.0",
         "Anfangstemperatur"),
        ("additional_capacity_kwh_per_k", "0.0",
         "Optional: Lumped-Capacitance fuer Wand+Luft (Gebäude-Speicher)"),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Zeitschritt t)"))
    out.append(vars_table([
        ("floor_energy[t]", "E^Floor_t", "kontinuierlich",
         "[0, total_capacity_kwh]",
         "Energieinhalt Estrich (0 = T_min, max = T_max)"),
        ("q_floor_in[t]", "Q^Floor,in_t", "kontinuierlich",
         "[0, max_thermal_input_kw]",
         "Thermische Leistung WP -> Estrich"),
        ("q_floor_to_room[t]", "Q^Floor→Raum_t", "kontinuierlich",
         "[0, ∞)",
         "Wärmestrom Estrich → Raum (nur mit aktivem Building)"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("floor_energy_balance_{t} (mit Building)",
         "E_t = E_{t-1} + (Q^Floor,in_t - Q^Floor→Raum_t) · Δt"),
        ("floor_energy_balance_{t} (Fallback)",
         "Ohne Building: E_t = E_{t-1} + Q^Floor,in_t · Δt - λ · E_{t-1} · Δt"),
        ("q_floor_to_room_link_{t}",
         "Q^Floor→Raum_t = h·A/1000 · (T_floor[t-1] - T_innen[t-1])  (affine Kopplung)"),
        ("Zusatz im WP-Modul",
         "Kopplung Q^Floor,in_t = COP^heiz_t · P^HP,Floor_t (s. WP)"),
    ]))
    out.append(P(
        "<b>Seit Mai 2026:</b> Mit aktiver Building-Komponente ist "
        "<font face='Courier'>q_floor_to_room</font> eine separate MILP-Variable, "
        "die explizit den Wärmestrom vom Estrich an die Raumluft modelliert. "
        "Sie speist die Raum-Energiebilanz in Building (siehe §10) und schließt "
        "den Kreis: Estrich speichert, Raum verliert. "
        "Ohne Building (Fallback) wird die alte Verlustraten-Bilanz mit λ "
        "verwendet — Boden-Abgabe wird implizit verbucht."
    ))

    out.append(H2("Output"))
    out.append(output_table([
        ("floor_energy_kwh",    "kWh", "Energieinhalt Estrich pro Zeitschritt"),
        ("floor_temp_c",        "C",   "Estrich-Temperatur (aus Energie zurueckgerechnet)"),
        ("q_floor_kw",          "kW",  "Thermische Leistung in den Estrich"),
        ("q_floor_to_room_kw",  "kW",  "Wärmestrom Estrich → Raum (nur mit Building)"),
    ]))
    out.append(PageBreak())
    return out


def section_thermal_storage():
    out = [H1("6. Pufferspeicher (Warmwasser)")]
    out.append(P(
        "Zwei-Zonen-Schichtenspeicher mit geometriebasierter Verlustberechnung. "
        "Das Modell wird auch fuer einen separaten Heizungspuffer verwendbar, "
        "wird aktuell jedoch nur fuer Warmwasser eingesetzt."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("volume_liters", "500.0", "Speichervolumen"),
        ("min_temperature_c / max_temperature_c", "30 / 65",
         "Speichertemperatur-Band"),
        ("comfort_temperature_c", "0.0",
         "Komfort-Mindesttemp. waehrend Komfortperioden"),
        ("comfort_periods", "[]",
         "Liste von Zeitfenstern (start_hour, end_hour)"),
        ("initial_temperature_c", "45.0", "Anfangstemperatur"),
        ("ambient_temperature_c", "20.0", "Umgebung des Speichers (Keller)"),
        ("height_diameter_ratio", "2.5", "Schlankheitsverhaeltnis (fuer Geometrie)"),
        ("insulation_thickness_m", "0.05", "Isolierdicke"),
        ("insulation_conductivity_w_m_k", "0.035", "Lambda PU-Schaum"),
        ("legionella_temp_c", "0",
         "Legionellenschutztemperatur (0 = aus)"),
        ("cold_water_inlet_temp_c", "10.0",
         "Kaltwasserzulauf fuer Nachheizfaktor"),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Zeitschritt t)"))
    out.append(vars_table([
        ("ts_energy_kwh[t]", "E^WW_t", "kontinuierlich",
         "[0, capacity_kwh]",
         "Energieinhalt (0 = T_min, kap = T_max)"),
        ("ts_q_in[t]",       "Q^WW,in_t", "kontinuierlich",
         "[0, ∞)", "Thermische Leistung von WP"),
        ("ts_q_demand[t]",   "Q^WW,bedarf_t", "kontinuierlich",
         "[0, ∞)", "Waermeentnahme (Brauchwasserbedarf)"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("ts_energy_balance_{t}",
         "E_t = E_{t-1} + (Q_in - Q_demand)Δt - Q^fix Δt - "
         "μ^rel E_{t-1} Δt"),
        ("ww_q_in_link_{t}",
         "Q^WW,in_t = q_ww_t   (Kopplung an WP-Pfad)"),
        ("ww_demand_fix_{t}",
         "Q^WW,bedarf_t + s^WW_t = φ^FWS · Brauchwasserbedarf_t"),
        ("ww_min_energy_schedule_{t}",
         "E_t ≥ E^min_t   (zeit-abhaengige Mindestenergie)"),
        ("ww_sg_ready_cap_{t}",
         "E_t ≤ capacity + ΔE^SG3 · y^SG3_t   (dynamische Obergrenze)"),
        ("..._legionella_*",
         "Optional: einmal pro Tag E_t ≥ Legionellen-Energie"),
    ]))

    out.append(H2("Output"))
    out.append(output_table([
        ("ww_storage_energy_kwh", "kWh", "Energieinhalt Speicher"),
        ("ww_storage_temp_c",     "C",   "Speichertemperatur (zurueckgerechnet)"),
        ("q_ww_kw",               "kW",  "Waermezufuhr von WP"),
    ]))
    out.append(PageBreak())
    return out


def section_fws():
    out = [H1("7. Frischwasserstation (passiv)")]
    out.append(P(
        "Wandelt den Brauchwasserbedarf des Haushalts (kW Warmwasser am Hahn) "
        "in eine Speicherentnahme um, berücksichtigt dabei "
        "Wärmetauscher-Wirkungsgrad und Kaltwasser-Mischung."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("target_hot_water_temp_c", "50.0", "Solltemperatur am Hahn"),
        ("cold_water_inlet_temp_c", "10.0", "Kaltwassertemperatur"),
        ("heat_exchanger_efficiency", "0.90", "Wirkungsgrad Plattenwaermetauscher"),
        ("min_storage_temp_for_dhw_c", "55.0",
         "Speichermindesttemperatur fuer Warmwasserbereitung"),
    ]))

    out.append(H2("Entscheidungs-Variablen"))
    out.append(P("<i>Keine.</i>"))

    out.append(H2("Beitrag zum Modell"))
    out.append(P(
        "Liefert Faktor φ^FWS, mit dem der Brauchwasserbedarf in "
        "Speicherentnahme umgerechnet wird "
        "(<font face='Courier'>calculate_storage_demand</font>). "
        "Geht dann in <font face='Courier'>ww_demand_fix_{t}</font> ein."
    ))

    out.append(H2("Output"))
    out.append(P("Keine eigenen Felder; Effekt in <font face='Courier'>"
                 "ww_storage_energy_kwh</font> und Q^WW,bedarf sichtbar."))
    out.append(PageBreak())
    return out


def section_wallbox():
    out = [H1("8. Wallbox")]
    out.append(P(
        "Pro aktive Wallbox <i>w</i> wird ein eigener Variablenblock erzeugt. "
        "Mehrere Wallboxen koexistieren als unabhängige Bloecke. Seit Mai "
        "2026 fuehrt die Wallbox eine explizite EV-SOC-Zustandsvariable "
        "mit Fahrverbrauch waehrend Abwesenheit; das Ziel-SOC-Constraint "
        "greift exakt zur Abfahrtszeit (statt nur als globale Mindest-"
        "Ladeenergie ueber den Horizont)."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("max_power_kw", "11.0", "Max. Ladeleistung der Wallbox"),
        ("min_power_kw", "4.2",  "Min. Ladeleistung wenn aktiv"),
        ("phases", "3", "1 oder 3 (begrenzt min/max)"),
        ("ev_battery_capacity_kwh", "60.0", "Akkukapazitaet des Fahrzeugs"),
        ("current_soc / target_soc", "0.30 / 0.80",
         "Aktueller SOC bei Optimierungs-Start und Ziel-SOC zur Abfahrt"),
        ("max_soc", "1.0", "Obergrenze des EV-Akkus (Hardware-Schutz)"),
        ("min_range_enabled", "true",
         "Schalter fuer das harte Ziel-SOC-Constraint zur Abfahrt"),
        ("charge_only_below_percentile_pct", "100.0",
         "Preisperzentil-Filter; bei min_range_enabled nur informativ, "
         "sonst hartes Ladeverbot in teuren Stunden"),
        ("driving_loss_pct_per_hour", "5.0",
         "Fahrverbrauch waehrend Abwesenheit (% von Kapazitaet/h)"),
        ("arrival_hour / departure_hour", "17 / 7",
         "EV-Anwesenheitsfenster"),
        ("charging_efficiency", "0.92", "Ladewirkungsgrad"),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Wallbox w, pro Zeitschritt t)"))
    out.append(vars_table([
        ("wb_<name>_power[t]", "P^WB,w_t", "kontinuierlich",
         "[0, max_power_kw]", "Ladeleistung Wallbox w"),
        ("wb_<name>_on[t]",    "y^WB,w_t", "binaer",
         "{0, 1}", "1 = Wallbox w laedt aktiv"),
        ("wb_<name>_soc[t]",   "SOC^EV,w_t", "kontinuierlich",
         "[0, max_soc · ev_battery_capacity_kwh]",
         "EV-SOC in kWh (Zustandsvariable, seit Mai 2026)"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("wb_<name>_max_power_{t}",
         "P^WB,w_t ≤ P_max · y^WB,w_t"),
        ("wb_<name>_min_power_{t}",
         "P^WB,w_t ≥ P_min · y^WB,w_t"),
        ("wb_<name>_ev_absent_{t}",
         "P^WB,w_t = 0 fuer t ausserhalb der EV-Anwesenheit"),
        ("wb_<name>_soc_balance_{t}",
         "SOC^EV,w_{t+1} = SOC^EV,w_t + η · P^WB,w_t · Δt   (anwesend)"),
        ("wb_<name>_soc_drain_{t}",
         "SOC^EV,w_{t+1} = SOC^EV,w_t - ℓ^drive   (abwesend, 5%/h-Verbrauch)"),
        ("wb_<name>_target_soc_at_{t_dep}",
         "SOC^EV,w_{t_dep} ≥ SOC^ziel · E^EV,kap   (HART, nur wenn min_range_enabled)"),
        ("wb_<name>_price_filter_{t}",
         "P^WB,w_t = 0 fuer t in teure-Stunden-Menge   "
         "(nur wenn min_range_enabled=False, sonst informativ)"),
    ]))

    out.append(H2("Output"))
    out.append(output_table([
        ("wallbox_power_kw[<name>]", "kW",
         "Zeitreihe Ladeleistung pro Wallbox"),
        ("ev_soc_kwh[<name>]", "kWh",
         "EV-SOC-Trajektorie pro Wallbox (gestrichelt waehrend Abwesenheit)"),
    ]))
    out.append(PageBreak())
    return out


def section_ev():
    out = [H1("9. E-Auto (passiv)")]

    out.append(P(
        "Das E-Auto-Komponentenmodell ist ein Container fuer Akku- und "
        "Fahrprofil-Daten. Es liefert die Konfiguration fuer die "
        "verknüpfte Wallbox und erzeugt selbst keine Solver-Variablen."
    ))
    out.append(config_table([
        ("battery_capacity_kwh", "58.0", "Akkukapazitaet"),
        ("current_soc / target_soc", "0.30 / 0.80", "SoC-Werte"),
        ("min_range_km / consumption_kwh_per_100km", "150 / 16.0",
         "Reichweite + Verbrauch -> Ziel-SoC"),
        ("arrival_hour / departure_hour", "17 / 7", "Anwesenheitsfenster"),
        ("min_range_enabled", "true",
         "Garantierte Mindestreichweite zur Abfahrt (an/aus)"),
        ("charge_only_below_percentile_pct", "100",
         "Strompreis-Perzentil zum Laden (relative Anwesenheit)"),
        ("onboard_charger_kw", "11.0", "Maximale AC-Ladeleistung"),
        ("linked_wallbox", "Wallbox 1", "Zuordnung zur Wallbox"),
    ]))
    out.append(P(
        "<b>Variablenbeitrag:</b> keine. Werte werden vor der Optimierung in "
        "die zugeordnete Wallbox-Config kopiert ("
        "<font face='Courier'>get_wallbox_config()</font>). Die Perzentil-"
        "Steuerung und die Mindestreichweite werden anschließend von der "
        "Wallbox als Constraints umgesetzt."
    ))
    out.append(PageBreak())
    return out


def section_building():
    out = [H1("10. Gebäude (MILPComponent seit Mai 2026)")]
    out.append(P(
        "Bis April 2026 war Gebäude eine rein passive Parameterquelle "
        "(Heizlast und additional_capacity_kwh_per_k). Seit Mai 2026 ist "
        "die <b>Raumlufttemperatur T_innen</b> eine eigene MILP-Zustands"
        "variable mit eigener Energiebilanz und Komfortband-Slacks. "
        "Damit wird der Wärmestrom Estrich → Raum → Außen explizit modelliert "
        "und nicht mehr durch eine Verlustrate auf dem Estrich "
        "verschleiert (siehe §5 Fallback-Modus)."
    ))

    out.append(H2("Inputs"))
    out.append(config_table([
        ("heated_area_m2", "150.0", "Wohnflaeche"),
        ("length_m / width_m / height_m", "15 / 10 / 2.5",
         "Geometrie für UA-Berechnung"),
        ("window_area_m2", "auto",
         "Fensterfläche (None -> ~15 % der Wandfläche)"),
        ("u_value_wall / window / roof_floor", "0.2 / 0.9 / 0.4",
         "U-Werte W/(m²·K)"),
        ("ventilation_loss_w_m3_k", "0.17",
         "Spezifischer Lüftungsverlust"),
        ("indoor_temp_c", "21.0",
         "Anfangs-Raumtemperatur T_innen[0]"),
        ("comfort_temp_min_c / comfort_temp_max_c", "21 / 24",
         "Komfortband (Soft-Constraint mit Slack-Penalty)"),
        ("screed_*", "...",
         "Estrichparameter für C_Estrich (kombiniert mit FBH)"),
    ]))

    out.append(H2("Entscheidungs-Variablen (pro Zeitschritt t)"))
    out.append(vars_table([
        ("t_innen[t]", "T^innen_t", "kontinuierlich",
         "[T_min−10, T_max+10] °C",
         "Raumlufttemperatur (Zustandsvariable)"),
        ("t_innen_slack_low[t]", "s^low_t", "kontinuierlich",
         "[0, ∞)",
         "Unterschreitung des Komfortbands"),
        ("t_innen_slack_high[t]", "s^high_t", "kontinuierlich",
         "[0, ∞)",
         "Überschreitung des Komfortbands"),
    ]))

    out.append(H2("Beigesteuerte Constraints"))
    out.append(constr_table([
        ("room_balance_{t}",
         "C_room · (T_innen[t] − T_innen[t-1]) = (Q^Floor→Raum_t − Q^Verlust_t) · Δt"),
        ("q_loss_link_{t}",
         "Q^Verlust_t = UA/1000 · (T_innen[t-1] − T_aussen[t])  (explizites Euler)"),
        ("comfort_lower_{t}",
         "T_innen[t] + s^low_t ≥ T^min_komfort"),
        ("comfort_upper_{t}",
         "T_innen[t] − s^high_t ≤ T^max_komfort"),
    ]))
    out.append(P(
        "Die Slack-Variablen werden in der Zielfunktion mit "
        "<b>UNMET_HEAT_PENALTY_CT = 500 ct/kWh</b> bestraft — deutlich "
        "über jedem realen Strompreis, sodass das Komfortband nur dann "
        "verletzt wird, wenn das Problem sonst infeasible wäre."
    ))

    out.append(H2("Output"))
    out.append(output_table([
        ("indoor_temp_c", "C",   "Raumtemperatur T_innen pro Zeitschritt"),
        ("heat_loss_kw",  "kW",  "Wärmeverlust Raum → Außen (UA·ΔT/1000)"),
        ("q_floor_to_room_kw", "kW",
         "Wärmestrom Estrich → Raum (auch in §5 ausgewiesen)"),
    ]))
    return out


# ----------------------------------------------------------------------
# Document assembly
# ----------------------------------------------------------------------

def build_pdf(out_path: str):
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=2.0 * cm,
        bottomMargin=1.8 * cm,
        title="EMOS Light - MILP-Variablen pro Komponente",
        author="EMOS Light Projektteam",
    )

    story = []
    story += build_cover()
    story += build_intro()
    story += section_grid()
    story += section_pv()
    story += section_battery()
    story += section_heatpump()
    story += section_underfloor()
    story += section_thermal_storage()
    story += section_fws()
    story += section_wallbox()
    story += section_ev()
    story += section_building()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "MILP_Variablen_Bericht.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
