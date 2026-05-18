"""Erzeugt eine PDF-Dokumentation der gesamten EMOS Light Codebase.

Teil A: Architektur-Übersicht (Verzeichnisse, Datenfluss, große Module)
Teil B: Modul-Detail (Datei-für-Datei mit Funktionen, Klassen, Constraints)
"""

import io
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
    Table, TableStyle, KeepTogether, Preformatted,
)
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT


# ----------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------

styles = getSampleStyleSheet()

styles.add(ParagraphStyle(
    name="BodyDE", parent=styles["BodyText"], alignment=TA_JUSTIFY,
    fontSize=10, leading=13.5, spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="Part", parent=styles["Heading1"], fontSize=22, leading=28,
    spaceBefore=4, spaceAfter=12, textColor=colors.HexColor("#0b3d91"),
    alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="H1", parent=styles["Heading1"], fontSize=16, leading=20,
    spaceBefore=12, spaceAfter=8, textColor=colors.HexColor("#0b3d91"),
))
styles.add(ParagraphStyle(
    name="H2", parent=styles["Heading2"], fontSize=12.5, leading=16,
    spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#143f7a"),
))
styles.add(ParagraphStyle(
    name="H3", parent=styles["Heading3"], fontSize=11, leading=14,
    spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#333"),
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
styles.add(ParagraphStyle(
    name="TocEntry", parent=styles["BodyText"], fontSize=10, leading=14,
    spaceAfter=2,
))
styles.add(ParagraphStyle(
    name="TocPart", parent=styles["BodyText"], fontSize=11, leading=15,
    spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#0b3d91"),
    fontName="Helvetica-Bold",
))


def P(text, style="BodyDE"):
    return Paragraph(text, styles[style])


def H1(text):
    return Paragraph(text, styles["H1"])


def H2(text):
    return Paragraph(text, styles["H2"])


def H3(text):
    return Paragraph(text, styles["H3"])


def cell(text, mono=False):
    return Paragraph(text, styles["CellMono" if mono else "Cell"])


def code_block(text):
    return Preformatted(
        text,
        ParagraphStyle(
            "Code", fontName="Courier", fontSize=8.5, leading=11,
            leftIndent=10, backColor=colors.HexColor("#f4f6fa"),
            borderColor=colors.HexColor("#dde3f0"), borderWidth=0.4,
            borderPadding=6, spaceAfter=8,
        ),
    )


HEADER_BG = colors.HexColor("#0b3d91")
ROW_ALT = colors.HexColor("#f5f7fc")


def std_table(header, rows, col_widths):
    data = [header] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
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
    ]))
    return t


# ----------------------------------------------------------------------
# Page header / footer
# ----------------------------------------------------------------------

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666"))
    canvas.drawString(2 * cm, 1.2 * cm,
                      "EMOS Light — Codebase-Dokumentation")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Seite {doc.page}")
    if doc.page > 1:
        canvas.setStrokeColor(colors.HexColor("#bbb"))
        canvas.setLineWidth(0.4)
        canvas.line(2 * cm, A4[1] - 1.6 * cm, A4[0] - 2 * cm, A4[1] - 1.6 * cm)
    canvas.restoreState()


# ----------------------------------------------------------------------
# Cover and TOC
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
        Paragraph("Codebase-Dokumentation",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=20, leading=24,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.6 * cm),
        Paragraph(
            "Was wird wo gemacht — Architektur und Modul-Detail",
            ParagraphStyle("CovSub2", parent=styles["BodyText"],
                           fontSize=12, leading=15,
                           textColor=colors.HexColor("#555"),
                           alignment=1),
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


def toc_row(num, title, page):
    return Paragraph(
        f"<b>{num}</b> &nbsp;&nbsp;{title}"
        f"<font color='#888'> &nbsp;.&nbsp;.&nbsp;.&nbsp;.&nbsp;.&nbsp;.&nbsp;.&nbsp;.&nbsp; "
        f"S.&nbsp;{page}</font>",
        styles["TocEntry"],
    )


def build_toc():
    """Statisches Inhaltsverzeichnis. Seitenzahlen siehe Build-Output."""
    out = [Paragraph("Inhaltsverzeichnis", styles["Part"])]

    out.append(Paragraph("Teil A — Architektur-Übersicht", styles["TocPart"]))
    out.append(toc_row("A.1", "Was macht EMOS Light?", 3))
    out.append(toc_row("A.2", "Verzeichnisbaum", 3))
    out.append(toc_row("A.3", "Datenfluss vom Eingang bis zum Ergebnis", 4))
    out.append(toc_row("A.4", "Modul-Schnellüberblick", 5))

    out.append(Paragraph("Teil B — Modul-Detail", styles["TocPart"]))
    out.append(toc_row("B.1",  "app.py — Streamlit-Dashboard", 6))
    out.append(toc_row("B.2",  "main.py — CLI-Einstiegspunkt", 7))
    out.append(toc_row("B.3",  "emos_light/core/ — Konfig, Szenario, Typen", 8))
    out.append(toc_row("B.4",  "emos_light/data/ — Preise, Wetter, Profile, Solar", 9))
    out.append(toc_row("B.5",  "emos_light/components/ — Anlagenmodelle", 11))
    out.append(toc_row("B.6",  "emos_light/optimization/ — Optimierer, MPC, Baseline", 12))
    out.append(toc_row("B.7",  "emos_light/utils/ — KPI-Auswertung", 13))
    out.append(toc_row("B.8",  "scripts/ — PDF-Generatoren", 13))
    out.append(toc_row("B.9",  "config/ — YAML-Konfigurationen", 14))

    out.append(Paragraph("Anhang", styles["TocPart"]))
    out.append(toc_row("C.1", "Konventionen und Datentypen", 15))
    out.append(toc_row("C.2", "Wo erweitere ich was?", 15))

    out.append(PageBreak())
    return out


# ----------------------------------------------------------------------
# Part A — Overview
# ----------------------------------------------------------------------

def part_a_intro():
    return [
        Paragraph("Teil A — Architektur-Übersicht", styles["Part"]),
        H1("A.1 Was macht EMOS Light?"),
        P(
            "EMOS Light ist ein Python-Tool zur kostenoptimierten Steuerung "
            "der Energieversorgung eines Neubaus mit PV, Batterie, "
            "Wärmepumpe, Pufferspeicher, Fußbodenheizung und Wallboxen. "
            "Die Optimierung ist als gemischt-ganzzahliges lineares "
            "Programm (MILP) formuliert, eingebettet entweder in eine "
            "einmalige Day-Ahead-Optimierung oder in einen rollierenden "
            "Model-Predictive-Control-Regler (MPC)."
        ),
        P(
            "Die Bedienung erfolgt entweder über ein Streamlit-Dashboard "
            "(<font face='Courier'>app.py</font>) oder über die Kommando­zeile "
            "(<font face='Courier'>main.py</font>). Beide nutzen denselben "
            "Kern unter <font face='Courier'>emos_light/</font>."
        ),
    ]


def part_a_tree():
    out = [H1("A.2 Verzeichnisbaum")]
    tree = """EMOS_light/
|
|-- app.py                 Streamlit-Dashboard (UI, Plots, Konfig)
|-- main.py                CLI-Einstiegspunkt
|-- requirements.txt       Python-Abhängigkeiten
|-- README.md              Schnellstart-Anleitung
|-- config/
|   `-- default_config.yaml      Default-Setup
|-- data/
|   `-- load_profiles/           4 vermessene CSV-Lastgänge (1J, 15min)
|
|-- emos_light/            Python-Paket (alle Logik)
|   |-- __init__.py
|   |
|   |-- core/              Kern-Module
|   |   |-- config.py            Default-Config + Loader
|   |   |-- scenario.py          Komponenten + Daten zusammensetzen
|   |   `-- types.py             Dataclasses TimeSeriesInput, Result
|   |
|   |-- data/              Eingangsdaten
|   |   |-- prices.py            Day-Ahead, Endverbraucherpreis
|   |   |-- weather.py           Wetterprognose-Abruf
|   |   |-- solar.py             Sonnenstand + Perez-Transposition
|   |   |-- profiles.py          synthetische Last-/Heiz-/WW-Profile
|   |   `-- household_profiles.py  vermessene Haushaltslastprofile
|   |
|   |-- components/        Anlagenmodelle
|   |   |-- base.py              Component (passiv) + MILPComponent (aktiv)
|   |   |-- _milp_helpers.py     wiederverwendbare MILP-Bausteine
|   |   |-- pv.py                PV-System (passiv)
|   |   |-- battery.py           Batteriespeicher (MILP)
|   |   |-- heat_pump.py         Wärmepumpe + COP-Kennfeld + SG-Ready (MILP)
|   |   |-- thermal_storage.py   Pufferspeicher (Zwei-Zonen, MILP)
|   |   |-- underfloor_heating.py  Estrich-Speicher (MILP)
|   |   |-- fresh_water_station.py  Frischwasser-Wandler (passiv)
|   |   |-- wallbox.py           Wallbox (MILP)
|   |   |-- electric_vehicle.py  EV-Datencontainer (passiv)
|   |   `-- building.py          Gebäudeparameter (passiv)
|   |
|   |-- optimization/      Solver
|   |   |-- optimizer.py         MILP-Hauptoptimierer
|   |   |-- mpc.py               Rollierende Wiederholung
|   |   `-- baseline.py          Heuristische Baseline (Vergleich)
|   |
|   `-- utils/
|       |-- kpi.py               Auswertung Autarkie, Eigenverbrauch ...
|       `-- interpolation.py     Bilineare 2D-Interpolation (z.B. COP)
|
`-- scripts/                PDF-Generatoren (Berichte)"""
    out.append(code_block(tree))
    return out


def part_a_dataflow():
    out = [H1("A.3 Datenfluss vom Eingang bis zum Ergebnis")]
    out.append(P(
        "Ein Optimierungslauf durchläuft fünf Stufen — egal ob er aus "
        "der App oder per CLI angestossen wird:"
    ))
    out.append(P(
        "<b>Stufe 1 — Konfiguration laden.</b> "
        "<font face='Courier'>core/config.py</font> liefert eine "
        "Default-Config; optional wird sie aus YAML überschrieben oder "
        "im Dashboard angepasst."
    ))
    out.append(P(
        "<b>Stufe 2 — Komponenten bauen.</b> "
        "<font face='Courier'>core/scenario.build_components()</font> "
        "instanziiert für jede aktivierte Komponente eine Python-Klasse "
        "(<font face='Courier'>PVSystem</font>, <font face='Courier'>"
        "Battery</font>, <font face='Courier'>HeatPump</font>, …)."
    ))
    out.append(P(
        "<b>Stufe 3 — Eingangsdaten laden.</b> "
        "<font face='Courier'>core/scenario.load_input_data()</font> ruft "
        "Day-Ahead-Preise (<font face='Courier'>data/prices.py</font>), "
        "Wetterprognose (<font face='Courier'>data/weather.py</font>) und "
        "PV-Ertrag (<font face='Courier'>data/solar.py</font>) ab und "
        "erzeugt Last- und Wärmebedarfsprofile "
        "(<font face='Courier'>data/profiles.py</font>). Ergebnis: ein "
        "<font face='Courier'>TimeSeriesInput</font>-Objekt mit allen "
        "Zeitreihen für den Horizont (z. B. 24 h x 15 min = 96 Schritte)."
    ))
    out.append(P(
        "<b>Stufe 4 — Optimieren.</b> Der "
        "<font face='Courier'>EMOSLightOptimizer</font> in "
        "<font face='Courier'>optimization/optimizer.py</font> sammelt "
        "von jeder Komponente die Entscheidungs­variablen und "
        "Constraints, fügt Knotenbilanz und Zielfunktion hinzu und "
        "übergibt das Modell an HiGHS (Fallback: CBC)."
    ))
    out.append(P(
        "<b>Stufe 5 — Auswerten.</b> Nach erfolgreicher Lösung extrahiert "
        "der Optimierer alle Variablen als Zeitreihen, "
        "<font face='Courier'>utils/kpi.py</font> berechnet "
        "Autarkie, Eigenverbrauch und Kosten. Das "
        "<font face='Courier'>OptimizationResult</font>-Objekt wird an "
        "die UI oder die CLI zurückgegeben."
    ))
    out.append(Spacer(1, 0.3 * cm))
    flow = """  +-------------+      +-------------+      +---------------+
  | YAML/ UI    | ---> | core/config | ---> | dict[str,Any] |
  +-------------+      +-------------+      +-------+-------+
                                                    |
                                                    v
                                          +---------------------+
                                          | core/scenario       |
                                          |  build_components() |
                                          |  load_input_data()  |
                                          +---------+-----------+
                                                    |
                                  +-----------------+-----------------+
                                  v                                   v
                         components/{pv,battery,...}        TimeSeriesInput
                                  |                                   |
                                  +-----------------+-----------------+
                                                    v
                                          +---------------------+
                                          | optimization/       |
                                          |  EMOSLightOptimizer | ----> HiGHS
                                          +---------+-----------+
                                                    v
                                          OptimizationResult
                                                    |
                                                    v
                                              utils/kpi
                                                    |
                                                    v
                                       App-Plots / CLI-Ausgabe"""
    out.append(code_block(flow))
    return out


def part_a_overview():
    out = [H1("A.4 Modul-Schnellüberblick")]
    rows = [
        [cell("app.py"), cell("905"),
         cell("Streamlit-UI: Konfiguration, Plots, Lauf-Auslösung")],
        [cell("main.py"), cell("100"),
         cell("CLI: --date, --api, --mpc, --dashboard")],
        [cell("core/config.py"), cell("276"),
         cell("Default-Config + YAML-Loader")],
        [cell("core/scenario.py"), cell("261"),
         cell("Komponenten und Eingangsdaten zusammensetzen")],
        [cell("core/types.py"), cell("82"),
         cell("Dataclasses für Eingaben und Ergebnis")],
        [cell("data/prices.py"), cell("190"),
         cell("Day-Ahead + Endverbraucherpreis")],
        [cell("data/weather.py"), cell("~250"),
         cell("Open-Meteo + synthetisches Wetter")],
        [cell("data/solar.py"), cell("541"),
         cell("Sonnenstand, DISC, Perez-Transposition, PV-Ertrag")],
        [cell("data/profiles.py"), cell("503"),
         cell("Synthetische Last-, Heiz- und WW-Profile + CSV-Import")],
        [cell("data/household_profiles.py"), cell("177"),
         cell("Vier vermessene Jahres-Lastgänge mit Resampling + Skalierung")],
        [cell("components/base.py"), cell("60"),
         cell("Component (passiv) + MILPComponent (mit @abstractmethod)")],
        [cell("components/_milp_helpers.py"), cell("196"),
         cell("Wiederverwendbare MILP-Bausteine (8 Helfer-Funktionen)")],
        [cell("components/pv.py"), cell("~190"),
         cell("PV-Anlage mit Perez-Transposition (passiv)")],
        [cell("components/battery.py"), cell("177"),
         cell("Batterie + Alterungskosten-Modell")],
        [cell("components/heat_pump.py"), cell("205"),
         cell("WP + COP-Kennfeld + SG-Ready 1/2/3")],
        [cell("components/thermal_storage.py"), cell("330"),
         cell("Zwei-Zonen-Pufferspeicher")],
        [cell("components/underfloor_heating.py"), cell("145"),
         cell("Estrich-Speicher für FBH")],
        [cell("components/fresh_water_station.py"), cell("~75"),
         cell("Brauchwasserwandler (passiv)")],
        [cell("components/wallbox.py"), cell("125"),
         cell("Wallbox + EV-Anwesenheit")],
        [cell("components/electric_vehicle.py"), cell("105"),
         cell("E-Auto-Datencontainer (passiv)")],
        [cell("components/building.py"), cell("~215"),
         cell("Gebäude-Parameter + shell capacity (passiv)")],
        [cell("optimization/optimizer.py"), cell("495"),
         cell("MILP-Hauptoptimierer (Bilanz, Zielfunktion, HiGHS)")],
        [cell("optimization/mpc.py"), cell("~180"),
         cell("Rollierende Wiederholung mit Zustandsübernahme")],
        [cell("optimization/baseline.py"), cell("~80"),
         cell("Naive Strategie als Vergleich")],
        [cell("utils/kpi.py"), cell("~80"),
         cell("Autarkie, Eigenverbrauch, Kosten-Kennzahlen")],
        [cell("utils/interpolation.py"), cell("56"),
         cell("Bilineare 2D-Interpolation (z.B. COP-Kennfeld)")],
    ]
    t = std_table(
        [cell("<b>Datei</b>"), cell("<b>Zeilen</b>"), cell("<b>Verantwortlich für</b>")],
        rows,
        [6.0 * cm, 1.5 * cm, 9.5 * cm],
    )
    out.append(t)
    out.append(Paragraph(
        "<i>Zeilenzahlen sind Richtwerte. Stand: ca. 7500 Zeilen Python.</i>",
        styles["Caption"],
    ))
    out.append(PageBreak())
    return out


# ----------------------------------------------------------------------
# Part B — Detail
# ----------------------------------------------------------------------

def part_b_intro():
    return [Paragraph("Teil B — Modul-Detail", styles["Part"])]


def part_b_app():
    out = [H1("B.1 app.py — Streamlit-Dashboard")]
    out.append(P(
        "Die UI ist eine einzige Datei (~900 Zeilen) und kombiniert "
        "Konfigurations-Eingaben, Lauf-Auslösung und Ergebnis-Plots in "
        "einer mehrtab-Streamlit-App."
    ))
    out.append(H2("Struktur"))
    out.append(std_table(
        [cell("<b>Block</b>"), cell("<b>Was passiert</b>")],
        [
            [cell("Imports + Page-Config"),
             cell("Streamlit-Layout, Plotly-Subplots, EMOS-Imports")],
            [cell("Sidebar"),
             cell("Datum, API-Quelle (synthetisch / live), Schritt-Auflösung")],
            [cell("Tab 'Konfiguration'"),
             cell("Komponenten-Toggles und alle Parameter (PV, Batterie, "
                  "WP, FBH, WW, Wallbox, E-Auto, Tarif, §14a)")],
            [cell("Tab 'Optimierung'"),
             cell("Knopf 'Optimierung starten' -> ruft scenario.build_* + "
                  "optimizer.optimize() oder mpc.run_mpc()")],
            [cell("Tab 'Ergebnis'"),
             cell("Plotly-Plots für Leistungsflüsse, SOC, Temperaturen, "
                  "Kosten-Tabellen, KPI-Karten")],
            [cell("Speichern/Laden"),
             cell("Konfiguration als YAML herunter-/hochladbar")],
        ],
        [4.5 * cm, 12.5 * cm],
    ))
    out.append(H2("Wichtige Funktionen / Imports"))
    out.append(P(
        "<font face='Courier'>load_config / DEFAULT_CONFIG</font> aus "
        "<font face='Courier'>core/config</font>, "
        "<font face='Courier'>build_components / build_optimizer / "
        "load_input_data / build_time_series_input</font> aus "
        "<font face='Courier'>core/scenario</font>, "
        "<font face='Courier'>EMOSLightOptimizer</font> aus "
        "<font face='Courier'>optimization/optimizer</font>, "
        "<font face='Courier'>MPCController</font> aus "
        "<font face='Courier'>optimization/mpc</font>."
    ))
    out.append(PageBreak())
    return out


def part_b_main():
    out = [H1("B.2 main.py — CLI-Einstiegspunkt")]
    out.append(P(
        "Schlanke Datei (~100 Zeilen). Parsed Argumente, baut Komponenten, "
        "läuft entweder Day-Ahead oder MPC, druckt KPIs."
    ))
    out.append(code_block("""python main.py                    # Morgen, synthetisch
python main.py --date 2026-04-15  # Bestimmtes Datum
python main.py --api              # Live-Daten (EPEX + Open-Meteo)
python main.py --mpc              # MPC-Modus
python main.py --config x.yaml    # Eigene Konfiguration
python main.py --dashboard        # startet Streamlit"""))
    out.append(H2("Ablauf"))
    out.append(P(
        "1. <font face='Courier'>argparse</font> liest Optionen.<br/>"
        "2. <font face='Courier'>load_config()</font> lädt YAML oder Default.<br/>"
        "3. <font face='Courier'>build_components()</font> + "
        "<font face='Courier'>build_optimizer()</font> bauen das System.<br/>"
        "4. <font face='Courier'>load_input_data()</font> + "
        "<font face='Courier'>build_time_series_input()</font> laden Eingangsdaten.<br/>"
        "5. <font face='Courier'>optimizer.optimize()</font> oder "
        "<font face='Courier'>MPCController.run_mpc()</font>.<br/>"
        "6. Optional <font face='Courier'>calculate_baseline_cost()</font> "
        "für Vergleich.<br/>"
        "7. KPIs werden in den Terminal gedruckt."
    ))
    out.append(PageBreak())
    return out


def part_b_core():
    out = [H1("B.3 emos_light/core/ — Konfig, Szenario, Typen")]

    out.append(H2("config.py (~280 Zeilen)"))
    out.append(P(
        "Liefert <font face='Courier'>DEFAULT_CONFIG</font> als Python-dict "
        "mit allen Sektionen (general, tariff, pv, battery, heat_pump, "
        "underfloor_heating, hot_water_storage, fresh_water_station, "
        "household, heat_demand, wallboxes, electric_vehicles, par14a, "
        "building). "
        "Daneben spezifische Defaults für Sublisten "
        "(<font face='Courier'>WALLBOX_DEFAULT</font>, "
        "<font face='Courier'>EV_DEFAULT</font>, "
        "<font face='Courier'>PV_SURFACE_DEFAULT</font>)."
    ))
    out.append(P(
        "<b>Hauptfunktionen:</b> "
        "<font face='Courier'>load_config(path)</font> liest YAML und "
        "merged in den Default; "
        "<font face='Courier'>save_config(config, path)</font> schreibt zurück."
    ))

    out.append(H2("scenario.py (261 Zeilen) — die Klammer"))
    out.append(P(
        "Setzt aus der Konfiguration (1) die Komponenten-Objekte und "
        "(2) die Eingangs-Zeitreihen zusammen. Wichtig: hier wird die "
        "<b>Wand+Luft-Speicherkapazität</b> des Gebäudes als "
        "<font face='Courier'>additional_capacity_kwh_per_k</font> an die "
        "Fußbodenheizung weitergereicht (Lumped-Capacitance-Erweiterung)."
    ))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>")],
        [
            [cell("build_components(config)", mono=True),
             cell("Erstellt PV/Battery/HeatPump/... -Objekte; gibt dict zurück")],
            [cell("build_optimizer(components)", mono=True),
             cell("Konstruiert EMOSLightOptimizer aus dict")],
            [cell("load_input_data(config, date, use_api, csv...)", mono=True),
             cell("Holt Preise (data/prices), Wetter (data/weather), "
                  "berechnet PV-Ertrag (PVSystem.estimate_generation), "
                  "wählt Lastprofil: eigene CSV → vermessenes Profil "
                  "(data/household_profiles, falls "
                  "household.load_profile_id gesetzt) → synthetisches "
                  "Profil; Heiz-/WW-Profile aus data/profiles")],
            [cell("build_time_series_input(config, data)", mono=True),
             cell("Verpackt Zeitreihen in TimeSeriesInput (siehe types.py)")],
            [cell("_pad_array(arr, target_len)", mono=True),
             cell("Hilfsfunktion: schneidet/erweitert Arrays auf Soll-Länge")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))

    out.append(H2("types.py (82 Zeilen)"))
    out.append(P(
        "Zwei zentrale Dataclasses, die als Vertrag zwischen den Modulen dienen:"
    ))
    out.append(std_table(
        [cell("<b>Datentyp</b>"), cell("<b>Inhalt</b>")],
        [
            [cell("TimeSeriesInput", mono=True),
             cell("Eingang für Optimierer: prices_ct_kwh, "
                  "pv_generation_kw, household_load_kw, heating_demand_kw, "
                  "hot_water_demand_kw, outside_temp_c, timestamps, "
                  "step_minutes, feed_in_tariff, max_grid_power_kw, "
                  "par14a-Settings")],
            [cell("OptimizationResult", mono=True),
             cell("Ausgang: success, solver_status, solve_time_s, "
                  "total_cost_eur + alle Zeitreihen "
                  "(grid_buy/sell, batt_*, hp_power, floor_*, ww_*, "
                  "wallbox_power_kw[name], sg_ready_state, KPIs)")],
        ],
        [4.5 * cm, 12.5 * cm],
    ))
    out.append(PageBreak())
    return out


def part_b_data():
    out = [H1("B.4 emos_light/data/ — Preise, Wetter, Profile, Solar")]

    out.append(H2("prices.py (190 Zeilen)"))
    out.append(P(
        "Holt EPEX-Spot-Preise und rechnet sie in Endverbraucherpreise um."
    ))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>")],
        [
            [cell("fetch_day_ahead_prices(date)", mono=True),
             cell("Holt EPEX-Tagespreise (per HTTPS) und gibt DataFrame "
                  "mit price_ct_kwh zurück")],
            [cell("generate_synthetic_prices(date, num_steps)", mono=True),
             cell("Tagesprofil-ähnliches Fallback wenn Internet/API fehlt")],
            [cell("calculate_consumer_price(spot, tariff)", mono=True),
             cell("Endpreis = (Spot + Aufschlag + Netzentgelt + Konzession "
                  "+ Stromsteuer + KWKG/Offshore) x (1 + MwSt)")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))

    out.append(H2("weather.py (~250 Zeilen)"))
    out.append(P(
        "Open-Meteo-Client für Lufttemperatur, GHI/DNI/DHI und Windgeschwindigkeit."
    ))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>")],
        [
            [cell("fetch_weather_forecast(lat, lon, date, num_steps, step_min)", mono=True),
             cell("Open-Meteo Forecast-API; resampelt auf Optimierungs-Auflösung")],
            [cell("generate_synthetic_weather(date, num_steps)", mono=True),
             cell("Sinusoid-Tagesgang + saisonale Skalierung als Fallback")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))

    out.append(H2("solar.py (541 Zeilen) — Herzstück PV-Ertrag"))
    out.append(P(
        "Standortbasierte Sonnenstands-, Strahlungs- und PV-Ertragsberechnung. "
        "Kein scikit-learn / pvlib — alles handimplementiert nach Originalpapieren."
    ))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>")],
        [
            [cell("solar_position(lat, lon, ts)", mono=True),
             cell("Sonnenhöhe und -azimut nach Spencer (1971): "
                  "Deklination + Zeitgleichung + Stundenwinkel")],
            [cell("_kasten_airmass(zenith)", mono=True),
             cell("Kasten-Young Air Mass (atmosphärischer Weg)")],
            [cell("_disc_decomposition(ghi, ts, lat, lon)", mono=True),
             cell("DISC nach Maxwell (1987): GHI -> DNI bei fehlendem DNI")],
            [cell("_perez_diffuse(...)", mono=True),
             cell("Perez (1990) anisotropes Modell für Diffusstrahlung "
                  "auf geneigte Fläche (Zirkumsolar + Horizontband + Isotrop)")],
            [cell("ghi_to_poa(...)", mono=True),
             cell("Konvertiert GHI in Plane-of-Array (POA) Einstrahlung "
                  "für beliebige Modulausrichtung")],
            [cell("estimate_pv_power(...)", mono=True),
             cell("POA -> elektrische Leistung mit Temperaturkorrektur (NOCT) "
                  "und Systemwirkungsgrad")],
            [cell("estimate_cell_temperature(...)", mono=True),
             cell("Zelltemperatur aus Umgebungstemp, Wind und POA")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))

    out.append(H2("profiles.py (503 Zeilen)"))
    out.append(P(
        "Synthetische Last-, Heiz- und Warmwasserprofile sowie der "
        "Importer für eigene Smart-Meter-CSVs. Wird als Fallback "
        "verwendet, wenn der Nutzer kein vermessenes Profil "
        "(siehe nächster Abschnitt) und keine eigene CSV gewählt hat."
    ))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>")],
        [
            [cell("generate_load_profile(annual_kwh, date, n)", mono=True),
             cell("Synthetisches Haushalts-Standardlastprofil mit "
                  "Morgen-/Mittags-/Abend-Peak; Wochenend-Variante; "
                  "reproduzierbar via Datums-Seed")],
            [cell("generate_heat_demand_profile(annual, date, n, temp)", mono=True),
             cell("Heizbedarf abhängig von Außentemp und Tageszeit; "
                  "konstant 0 oberhalb Heizgrenztemp")],
            [cell("generate_hot_water_profile(annual, date, n)", mono=True),
             cell("WW-Bedarf mit Morgen- und Abend-Peak (Duschen)")],
            [cell("parse_csv_load_profile / load_csv_profile", mono=True),
             cell("Importiert echte Messdaten aus CSV (Smart-Meter-Export)")],
            [cell("forecast_load_profile(...)", mono=True),
             cell("Wochentag-/Saison-basierte Vorhersage aus historischer CSV")],
            [cell("_estimate_hp_profile(...)", mono=True),
             cell("Bei csv_includes_hp=True: WP-Anteil aus Gesamtmessung herausrechnen")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))

    out.append(H2("household_profiles.py (177 Zeilen) — vermessene Lastgänge"))
    out.append(P(
        "Lädt eines von vier vermessenen Jahres-Lastprofilen aus "
        "<font face='Courier'>data/load_profiles/*.csv</font> "
        "(35.040 Slots à 15 min, ohne Wärmepumpenanteil) und liefert "
        "den Tagesausschnitt in der gewünschten Auflösung. "
        "Linear skaliert auf den vom Nutzer gewählten Jahresverbrauch — "
        "damit bleibt das Tagesmuster der Messung erhalten, der "
        "Pegel passt aber zum konkreten Haushalt."
    ))
    out.append(std_table(
        [cell("<b>Profil-ID</b>"), cell("<b>Anzeige</b>"), cell("<b>Original kWh/a</b>")],
        [
            [cell("1person", mono=True), cell("1 Person"), cell("2 287")],
            [cell("2person", mono=True), cell("2 Personen"), cell("3 304")],
            [cell("2person_1kind", mono=True), cell("2 Personen + 1 Kind"), cell("3 929")],
            [cell("2person_2kinder", mono=True),
             cell("2 Personen + 2 Kinder (Default)"), cell("4 308")],
        ],
        [4.5 * cm, 7.5 * cm, 5.0 * cm],
    ))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>")],
        [
            [cell("HOUSEHOLD_PROFILES (dict)", mono=True),
             cell("Zentrales Verzeichnis: ID → Label, Dateiname, "
                  "Original-Jahreswert. Hier neue Profile registrieren.")],
            [cell("list_profiles()", mono=True),
             cell("Liefert (id, label, annual_kwh)-Liste für das "
                  "Dashboard-Dropdown")],
            [cell("get_profile_label(profile_id)", mono=True),
             cell("Anzeigename eines Profils (Fallback: ID selbst)")],
            [cell("load_household_profile(id, date, num_steps, "
                  "target_annual_kwh)", mono=True),
             cell("Lädt Tagesausschnitt, resampelt auf num_steps, "
                  "skaliert linear auf Ziel-Jahresverbrauch")],
            [cell("_load_full_year_kwh_per_slot(id)", mono=True),
             cell("Liest die CSV einmal und cached sie via "
                  "@lru_cache (35 040 Werte)")],
            [cell("_resample_kwh_per_slot(slot_kwh, target_steps)", mono=True),
             cell("Wandelt 96 Slots à kWh in num_steps Werte in kW; "
                  "linear über den Tagesverlauf")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))
    out.append(P(
        "<b>Verzweigungslogik in <font face='Courier'>scenario."
        "load_input_data</font>:</b> "
        "Eigene CSV (Smart-Meter-Upload) → "
        "<font face='Courier'>profiles.load_csv_profile</font>; sonst "
        "wenn <font face='Courier'>household.load_profile_id</font> "
        "gesetzt → "
        "<font face='Courier'>household_profiles.load_household_profile</font>; "
        "sonst → synthetisches "
        "<font face='Courier'>profiles.generate_load_profile</font>."
    ))
    out.append(PageBreak())
    return out


def part_b_components():
    out = [H1("B.5 emos_light/components/ — Anlagenmodelle")]
    out.append(P(
        "Seit dem Refactoring (Mai 2026) gibt es eine "
        "<b>zwei-stufige Basisklasse</b> in "
        "<font face='Courier'>base.py</font>:"
    ))
    out.append(std_table(
        [cell("<b>Basisklasse</b>"), cell("<b>Zweck</b>"), cell("<b>Erbende Klassen</b>")],
        [
            [cell("Component", mono=True),
             cell("Minimal: Name, Config, enabled-Flag. Für passive "
                  "Daten-Provider — keine MILP-Pflichten."),
             cell("PVSystem, Building, ElectricVehicle, FreshWaterStation")],
            [cell("MILPComponent", mono=True),
             cell("Erweitert Component um zwei abstrakte Methoden — "
                  "@abstractmethod erzwingt das Implementieren."),
             cell("Battery, HeatPump, ThermalStorage, "
                  "UnderfloorHeating, Wallbox")],
        ],
        [4.0 * cm, 7.0 * cm, 6.0 * cm],
    ))
    out.append(P(
        "MILPComponent-Pflichtmethoden:"
    ))
    out.append(std_table(
        [cell("<b>Methode</b>"), cell("<b>Zweck</b>")],
        [
            [cell("__init__(name, config)", mono=True),
             cell("Liest alle Parameter aus Config-Dict mit Defaults")],
            [cell("get_optimization_variables(num_steps, model)", mono=True),
             cell("Erstellt PuLP-LpVariable-Listen pro Zeitschritt; "
                  "gibt dict mit Variablen zurück")],
            [cell("add_constraints(model, variables, step_minutes)", mono=True),
             cell("Fügt lineare Ungleichungen und Gleichungen hinzu — "
                  "nutzt dabei die Helfer aus _milp_helpers.py")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))

    out.append(H2("_milp_helpers.py — wiederverwendbare MILP-Bausteine"))
    out.append(P(
        "Acht Hilfsfunktionen kapseln die Standardmuster, die sonst "
        "in jeder Komponente dupliziert würden. <b>Komponenten schreiben "
        "damit Intent statt Boilerplate</b> — also „dieser Mechanismus“ "
        "statt „diese 12 Zeilen Constraint-Code“."
    ))
    out.append(std_table(
        [cell("<b>Helfer</b>"), cell("<b>Zweck</b>"), cell("<b>Genutzt von</b>")],
        [
            [cell("step_hours / steps_for_minutes", mono=True),
             cell("Zeit-Konvertierungen"), cell("alle MILP-Komponenten")],
            [cell("make_var_array / make_binary_array", mono=True),
             cell("Erstellt Listen von LpVariables"),
             cell("alle MILP-Komponenten")],
            [cell("add_on_off_power_link", mono=True),
             cell("P ≤ Pmax·y und P ≥ Pmin·y (Modulationsbereich)"),
             cell("Battery, HeatPump, Wallbox")],
            [cell("add_mutual_exclusion", mono=True),
             cell("a[t] + b[t] ≤ 1 (Lade vs Entlade, SG1 vs SG3)"),
             cell("Battery, HeatPump")],
            [cell("add_min_run_time / add_min_pause_time", mono=True),
             cell("Hardware-Schutz: Verdichter/Schalter "
                  "Mindestlauf- und -pausenzeiten"), cell("HeatPump")],
            [cell("add_min_hold_time", mono=True),
             cell("Mindesthaltezeit für SG-Ready-Zustände"),
             cell("HeatPump")],
            [cell("add_state_balance", mono=True),
             cell("Energiebilanz E[t] = f(E[t-1], t) mit "
                  "Sonderfall t=0; rhs_fn liefert die rechte Seite"),
             cell("Battery, ThermalStorage, UnderfloorHeating")],
        ],
        [5.0 * cm, 7.5 * cm, 4.5 * cm],
    ))
    out.append(P(
        "<b>Effekt:</b> Komponenten-Code rund 26 % kürzer (1700 → 1250 "
        "Zeilen), Bug-Oberfläche pro Komponente kleiner, eine neue "
        "Komponente schreibt sich um ein Drittel schneller. "
        "Modellverhalten identisch — nur die Code-Struktur ist sauberer."
    ))

    out.append(H2("Komponenten-Steckbrief"))
    out.append(std_table(
        [cell("<b>Datei</b>"), cell("<b>Zeilen</b>"),
         cell("<b>Variablen</b>"), cell("<b>Besonderheit</b>")],
        [
            [cell("pv.py"), cell("190"), cell("0 (passiv)"),
             cell("nutzt data/solar.py für POA + Leistung")],
            [cell("battery.py"), cell("193"), cell("5 (3 kont., 2 binär)"),
             cell("Alterungskosten in Zielfunktion")],
            [cell("heat_pump.py"), cell("272"), cell("4-6"),
             cell("2D-COP-Kennfeld aroTHERM plus, SG-Ready 1/3")],
            [cell("thermal_storage.py"), cell("348"), cell("3 kont."),
             cell("Zwei-Zonen Verlustmodell, Komfortperioden")],
            [cell("underfloor_heating.py"), cell("167"), cell("2 kont."),
             cell("Estrich + optional Wand+Luft (Lumped Cap.)")],
            [cell("fresh_water_station.py"), cell("80"), cell("0 (passiv)"),
             cell("Faktor phi^FWS für Bedarfsumrechnung")],
            [cell("wallbox.py"), cell("147"), cell("2 (1 kont., 1 binär)"),
             cell("Pro Wallbox eigener Block; EV-Anwesenheit")],
            [cell("electric_vehicle.py"), cell("114"), cell("0 (passiv)"),
             cell("Liefert Wallbox-Konfig (Akku, SOC, Reichweite)")],
            [cell("building.py"), cell("220"), cell("0 (passiv)"),
             cell("Heizlast + shell_capacity_kwh_per_k")],
        ],
        [4.4 * cm, 1.5 * cm, 3.2 * cm, 7.9 * cm],
    ))
    out.append(P(
        "Eine vollständige Variablen-/Constraint-Tabelle pro Komponente "
        "findet sich im separaten Bericht "
        "<i>EMOS_Light_MILP_Variablen.pdf</i>."
    ))
    out.append(PageBreak())
    return out


def part_b_optimization():
    out = [H1("B.6 emos_light/optimization/ — Optimierer, MPC, Baseline")]

    out.append(H2("optimizer.py (495 Zeilen) — der Kern"))
    out.append(P(
        "Implementiert <font face='Courier'>EMOSLightOptimizer.optimize"
        "(input)</font>. Ablauf in einer einzigen Methode:"
    ))
    out.append(std_table(
        [cell("<b>Block</b>"), cell("<b>Was wird gemacht</b>")],
        [
            [cell("Setup"),
             cell("Anzahl Schritte, dt; pulp.LpProblem instanziieren")],
            [cell("Netz-Variablen"),
             cell("grid_buy / grid_sell / grid_buy_on + Disjunktion")],
            [cell("Komponenten-Loop"),
             cell("Für jede aktive Komponente: get_optimization_variables() + "
                  "add_constraints()")],
            [cell("WP-Pfad-Aufteilung"),
             cell("hp_power = hp_power_floor + hp_power_ww; "
                  "Q_floor = COP_heiz * hp_power_floor; "
                  "Q_ww = COP_ww * hp_power_ww")],
            [cell("WW-Bedarf-Kopplung"),
             cell("ww_q_demand + ww_slack = phi_FWS * Brauchwasserbedarf")],
            [cell("Komfort-Mindestenergie"),
             cell("ww_energy >= min_energy_schedule (zeitabhängig)")],
            [cell("SG-Ready dynamische Kapazität"),
             cell("ww_energy <= base_cap + delta_cap_3 * sg_state_3")],
            [cell("Wallbox-Loop"),
             cell("Summe Ladeleistung in wb_total_power[t]")],
            [cell("Knotenbilanz"),
             cell("PV + grid_buy + batt_dis = Last + grid_sell + batt_ch + "
                  "hp_power + Sum(wallboxes)")],
            [cell("Einspeise-Limit"),
             cell("grid_sell <= P_PV (nur PV einspeisen)")],
            [cell("§14a"),
             cell("Optionale Drosselung steuerbarer Verbraucher")],
            [cell("Zielfunktion"),
             cell("Netzkosten - Erlöse + Slack-Penalties + Alterung")],
            [cell("Solven"),
             cell("HiGHS_CMD timeLimit=120s; Fallback PULP_CBC_CMD")],
            [cell("Ergebnis-Extraktion"),
             cell("Alle Variablen als np.array; SG-Ready aus sg_state_1/3 "
                  "rekonstruiert; Alterungs-KPIs; calculate_kpis()")],
        ],
        [4.5 * cm, 12.5 * cm],
    ))

    out.append(H2("mpc.py — Rollierender Horizont"))
    out.append(P(
        "<font face='Courier'>MPCController(optimizer, horizon_hours, "
        "execute_hours)</font>. Wiederholt Optimierungsläufe in einem "
        "Sliding-Window:"
    ))
    out.append(P(
        "1. Schneide aus der Gesamt-Eingabe ein Fenster über "
        "<i>horizon_hours</i> heraus.<br/>"
        "2. <font face='Courier'>optimizer.optimize(window)</font> lösen.<br/>"
        "3. Nur die ersten <i>execute_hours</i> Schritte als "
        "definitives Ergebnis übernehmen.<br/>"
        "4. Endzustände (Batterie-SOC, Estrich-Energie, WW-Energie) "
        "via <font face='Courier'>_update_initial_conditions()</font> "
        "in die Komponenten zurückschreiben.<br/>"
        "5. Fenster um <i>execute_hours</i> nach vorne schieben, weiter."
    ))
    out.append(P(
        "Damit reagiert das System auf neue Prognosen — wichtig wenn "
        "Wetter oder Preise im Laufe des Tages aktualisiert werden."
    ))

    out.append(H2("baseline.py — Vergleichsmaßstab"))
    out.append(P(
        "<font face='Courier'>calculate_baseline_cost(input, config)</font>: "
        "Naive Strategie als Kostenvergleich, ohne MILP."
    ))
    out.append(P(
        "Regelwerk: PV-Überschuss zuerst in Batterie, dann ins Netz; "
        "Bezug aus Batterie wenn möglich, sonst Netz; "
        "WP läuft nach Bedarf ohne Preisoptimierung; "
        "Wallbox lädt sofort bei Ankunft. Liefert eine Vergleichszahl, "
        "die in der App neben den Optimierungs-Kosten angezeigt wird."
    ))
    out.append(PageBreak())
    return out


def part_b_utils_scripts():
    out = [H1("B.7 emos_light/utils/ — KPI-Auswertung")]
    out.append(P(
        "<font face='Courier'>kpi.py</font> nimmt nach erfolgreicher Lösung "
        "das <font face='Courier'>OptimizationResult</font> und ergänzt:"
    ))
    out.append(std_table(
        [cell("<b>KPI</b>"), cell("<b>Formel</b>")],
        [
            [cell("pv_total_kwh", mono=True),     cell("Sum(P_PV_t) * dt")],
            [cell("load_total_kwh", mono=True),   cell("Sum(Last + WP + Wallbox) * dt")],
            [cell("grid_buy_total_kwh", mono=True),  cell("Sum(P_buy_t) * dt")],
            [cell("grid_sell_total_kwh", mono=True), cell("Sum(P_sell_t) * dt")],
            [cell("hp_total_kwh", mono=True),     cell("Sum(P_HP_t) * dt")],
            [cell("eigenverbrauch_pct", mono=True),
             cell("(PV_self_consumed / PV_total) * 100")],
            [cell("autarkie_pct", mono=True),
             cell("(Last - Netzbezug) / Last * 100")],
            [cell("grid_buy_cost_eur", mono=True),
             cell("Sum(P_buy_t * pi_t) * dt / 100")],
            [cell("feed_in_revenue_eur", mono=True),
             cell("Sum(P_sell_t * pi_feed) * dt / 100")],
            [cell("total_cost_eur", mono=True),
             cell("buy_cost - feed_in_revenue (ohne Alterung)")],
        ],
        [4.5 * cm, 12.5 * cm],
    ))

    out.append(H1("B.8 scripts/ — PDF-Generatoren"))
    out.append(std_table(
        [cell("<b>Skript</b>"), cell("<b>Erzeugt</b>")],
        [
            [cell("build_milp_report.py"),
             cell("Mathematischer MILP-Bericht mit Formeln und Topologie")],
            [cell("build_variables_report.py"),
             cell("Variablen- und Constraint-Tabellen pro Komponente")],
            [cell("build_codebase_report.py"),
             cell("Diese Codebase-Dokumentation")],
        ],
        [6.0 * cm, 11.0 * cm],
    ))
    out.append(P(
        "Alle drei nutzen <i>reportlab</i> + <i>matplotlib mathtext</i> "
        "und sind eigenständig laufbar via "
        "<font face='Courier'>python scripts/&lt;name&gt;.py &lt;output.pdf&gt;</font>."
    ))
    out.append(PageBreak())
    return out


def part_b_config():
    out = [H1("B.9 config/ — YAML-Konfigurationen")]
    out.append(P(
        "<font face='Courier'>default_config.yaml</font> ist die "
        "auf YAML serialisierte Form von "
        "<font face='Courier'>DEFAULT_CONFIG</font> aus "
        "<font face='Courier'>core/config.py</font>. Sie wird beim "
        "App-Start optional eingelesen und vom Nutzer im Dashboard "
        "modifiziert. Custom-Konfigurationen lassen sich aus dem "
        "Dashboard per Download/Upload austauschen oder via "
        "<font face='Courier'>main.py --config x.yaml</font> in der CLI "
        "übergeben."
    ))
    out.append(P(
        "<b>Sektionen</b> (alle frei konfigurierbar, wo nichts angegeben "
        "wird gilt der Default):"
    ))
    sections = [
        "general (Standort, Schrittweite, Horizont, Netzanschluss, Einspeisevergütung)",
        "tariff (Aufschlag, Netzentgelt, Konzession, Stromsteuer, Umlagen, MwSt)",
        "household (Jahresverbrauch elektrisch)",
        "heat_demand (Jahres-Heiz- und Warmwasserbedarf)",
        "pv (peak_power_kwp, surfaces[], Wirkungsgrad)",
        "battery (capacity_kwh, Lade-/Entladelimits, SoC-Fenster, Alterung)",
        "heat_pump (max_power_kw, Vorlauftemperaturen, SG-Ready Settings)",
        "underfloor_heating (Fläche, Estrich, Komforttemp, Verlustkoeff.)",
        "hot_water_storage (Volumen, Temp-Band, Geometrie, Komfortperioden)",
        "fresh_water_station (Solltemp, Wirkungsgrad)",
        "building (Heizlast-Auslegung, Wand-/Luft-Kapazität)",
        "wallboxes[] (pro Wallbox: Phasen, Min/Max-Power)",
        "electric_vehicles[] (pro EV: Akku, SoC, Reichweite, Verbrauch)",
        "par14a (curtailment_kw, Drosselungs-Stunden)",
    ]
    for s in sections:
        out.append(P(f"• {s}"))
    out.append(PageBreak())
    return out


def appendix():
    out = [Paragraph("Anhang", styles["Part"])]

    out.append(H1("C.1 Konventionen und Datentypen"))
    out.append(std_table(
        [cell("<b>Größe</b>"), cell("<b>Einheit</b>"), cell("<b>Hinweis</b>")],
        [
            [cell("Leistung"), cell("kW"), cell("immer Brutto")],
            [cell("Energie"),  cell("kWh"), cell("Energie = Leistung * dt")],
            [cell("Preise (intern)"),  cell("ct/kWh"),
             cell("erst am Ende /100 für EUR-Anzeige")],
            [cell("Temperaturen"), cell("°C"), cell("nicht Kelvin")],
            [cell("Zeitschritt"), cell("min"), cell("typisch 15, optional 60")],
            [cell("Zeit-Index"), cell("t = 0..N-1"),
             cell("N = horizon_hours * 60 / step_minutes")],
            [cell("SOC"), cell("0..1"), cell("nicht Prozent")],
            [cell("Komfortperioden"), cell("Stunden 0-24"),
             cell("über Mitternacht erlaubt")],
        ],
        [4.0 * cm, 2.5 * cm, 10.5 * cm],
    ))

    out.append(H1("C.2 Wo erweitere ich was?"))
    out.append(std_table(
        [cell("<b>Änderungswunsch</b>"), cell("<b>Wo anfassen</b>")],
        [
            [cell("Neue Komponente (z. B. Heizstab)"),
             cell("emos_light/components/<neu>.py mit Component-Subklasse + "
                  "Eintrag in core/scenario.build_components + Optimizer "
                  "(Knotenbilanz erweitern) + Default in core/config + "
                  "UI in app.py")],
            [cell("Neuer Tarif-Bestandteil"),
             cell("data/prices.calculate_consumer_price + DEFAULT_CONFIG[tariff]")],
            [cell("Anderes COP-Kennfeld"),
             cell("components/heat_pump.py: _OUTDOOR_TEMPS, _FLOW_TEMPS, _COP_TABLE")],
            [cell("Andere Wettertabellen"),
             cell("data/weather.py")],
            [cell("Strafkosten Komfortverletzung"),
             cell("optimization/optimizer.UNMET_HEAT_PENALTY_CT")],
            [cell("Solver wechseln"),
             cell("optimization/optimizer.optimize() — pulp.HiGHS_CMD ersetzen")],
            [cell("Neuen KPI"),
             cell("utils/kpi.calculate_kpis + Anzeige in app.py / main.py")],
            [cell("Raum als zweiter Knoten (RC-Modell)"),
             cell("components/building.py um Variablen erweitern + "
                  "neuer Constraint-Block im Optimizer (Building-Energiebilanz)")],
        ],
        [5.5 * cm, 11.5 * cm],
    ))
    return out


# ----------------------------------------------------------------------
# Document assembly
# ----------------------------------------------------------------------

def build_pdf(out_path: str):
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        topMargin=2.0 * cm, bottomMargin=1.8 * cm,
        title="EMOS Light - Codebase-Dokumentation",
        author="EMOS Light Projektteam",
    )

    story = []
    story += build_cover()
    story += build_toc()

    story += part_a_intro()
    story += part_a_tree()
    story += part_a_dataflow()
    story += part_a_overview()

    story += part_b_intro()
    story += part_b_app()
    story += part_b_main()
    story += part_b_core()
    story += part_b_data()
    story += part_b_components()
    story += part_b_optimization()
    story += part_b_utils_scripts()
    story += part_b_config()

    story += appendix()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "Codebase_Dokumentation.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
