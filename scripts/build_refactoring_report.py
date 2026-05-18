"""Erzeugt eine PDF-Beschreibung der Codebase nach dem Komponenten-Refactoring.

Beschreibt was geändert wurde (5 Commits), warum, mit konkreten Vorher-/
Nachher-Beispielen und einem Ausblick auf die noch offene zweite Stufe
(Optimizer-Modularisierung).
"""

import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, Preformatted,
)
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT


# ----------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------

styles = getSampleStyleSheet()

styles.add(ParagraphStyle(
    name="BodyDE", parent=styles["BodyText"], alignment=TA_JUSTIFY,
    fontSize=10.5, leading=15, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="Part", parent=styles["Heading1"], fontSize=22, leading=28,
    spaceBefore=4, spaceAfter=12, textColor=colors.HexColor("#0b3d91"),
    alignment=TA_LEFT,
))
styles.add(ParagraphStyle(
    name="H1", parent=styles["Heading1"], fontSize=17, leading=22,
    spaceBefore=14, spaceAfter=10, textColor=colors.HexColor("#0b3d91"),
))
styles.add(ParagraphStyle(
    name="H2", parent=styles["Heading2"], fontSize=13, leading=17,
    spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#143f7a"),
))
styles.add(ParagraphStyle(
    name="H3", parent=styles["Heading3"], fontSize=11, leading=14,
    spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#333"),
))
styles.add(ParagraphStyle(
    name="Cell", parent=styles["BodyText"], fontSize=9, leading=12,
    alignment=TA_LEFT, spaceAfter=0,
))
styles.add(ParagraphStyle(
    name="CellMono", parent=styles["BodyText"], fontName="Courier",
    fontSize=8.5, leading=11, alignment=TA_LEFT, spaceAfter=0,
))
styles.add(ParagraphStyle(
    name="Caption", parent=styles["BodyText"], fontSize=9, leading=12,
    textColor=colors.HexColor("#555"), alignment=TA_JUSTIFY, spaceAfter=10,
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


def code_block(text, bg="#f4f6fa"):
    return Preformatted(
        text,
        ParagraphStyle(
            "Code", fontName="Courier", fontSize=8.5, leading=11,
            leftIndent=10, backColor=colors.HexColor(bg),
            borderColor=colors.HexColor("#dde3f0"), borderWidth=0.4,
            borderPadding=6, spaceAfter=10,
        ),
    )


def diff_block(text):
    return code_block(text, bg="#fbfbf3")


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
                      "EMOS Light — Codebase nach dem Komponenten-Refactoring")
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
        Paragraph("Codebase nach dem Refactoring",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=20, leading=24,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.6 * cm),
        Paragraph(
            "Was sich an den Komponenten geändert hat, warum, "
            "und wie eine neue Komponente jetzt aussieht — "
            "vier Refactoring-Phasen im Detail.",
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
    out = [Paragraph("Inhaltsverzeichnis", styles["Part"])]
    out.append(toc_row("1", "Was wurde refactored — und was nicht", 3))
    out.append(toc_row("2", "Die vier Phasen im Überblick", 4))
    out.append(toc_row("3", "Zwei-Stufen-Basisklasse: Component vs MILPComponent", 5))
    out.append(toc_row("4", "Das neue Modul _milp_helpers.py", 7))
    out.append(toc_row("5", "Migrationsbeispiel: Battery vorher/nachher", 10))
    out.append(toc_row("6", "Vereinheitlichte Naming-Convention", 12))
    out.append(toc_row("7", "Ausgelagerte Hilfsmodule", 13))
    out.append(toc_row("8", "Was bedeutet das für eine neue Komponente?", 14))
    out.append(toc_row("9", "Was noch offen ist (zweite Refactoring-Stufe)", 16))
    out.append(toc_row("10", "Zusammenfassung", 17))
    out.append(PageBreak())
    return out


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------

def section_1():
    out = [H1("1. Was wurde refactored — und was nicht")]
    out.append(P(
        "Die Modularitäts-Diskussion vom 02. Mai hat fünf konkrete "
        "Verbesserungen aufgelistet, die das Hinzufügen neuer Komponenten "
        "erleichtern würden. Das jetzt durchgeführte Refactoring greift "
        "die <b>am stärksten dupliziert auftretenden Muster im "
        "Komponentencode</b> heraus und konsolidiert sie an einem Ort. "
        "Ein zweiter, größerer Schritt (Optimizer-Modularisierung, "
        "OptimizationResult als dict, Plugin-Registry) bleibt bewusst "
        "für später."
    ))

    out.append(H2("In Zahlen"))
    out.append(std_table(
        [cell("<b>Kennzahl</b>"), cell("<b>vorher</b>"), cell("<b>nachher</b>")],
        [
            [cell("Komponenten-Code (Summe LOC)"),
             cell("ca. 1 700 Zeilen"), cell("ca. 1 250 Zeilen")],
            [cell("Duplizierte MILP-Muster"),
             cell("8 mal hardcodiert"), cell("8 Helfer in einem Modul")],
            [cell("Basisklasse"),
             cell("eine, alle Komponenten erben"),
             cell("zwei Stufen (passiv vs MILP)")],
            [cell("Abstrakter Vertrag"),
             cell("nur per Konvention"),
             cell("@abstractmethod erzwungen")],
            [cell("interp_2d"),
             cell("nur in heat_pump.py"), cell("in utils/interpolation.py")],
            [cell("Variablen-Naming"),
             cell("uneinheitlich (sg_state_1, …)"),
             cell("einheitlich (hp_sg1, hp_sg3, ufh_floor_energy, …)")],
        ],
        [6.0 * cm, 5.5 * cm, 5.5 * cm],
    ))

    out.append(H2("Was bewusst NICHT angefasst wurde"))
    out.append(P(
        "Damit das Refactoring überschaubar und sicher bleibt, sind "
        "diese Punkte explizit verschoben:"
    ))
    out.append(std_table(
        [cell("<b>Verschoben</b>"), cell("<b>Begründung</b>")],
        [
            [cell("Optimizer-Modularisierung "
                  "(generische Komponenten-Schleife)"),
             cell("Größerer struktureller Eingriff. Erfordert auch "
                  "die nächsten Punkte, sonst halber Erfolg.")],
            [cell("OptimizationResult als dict statt fester Felder"),
             cell("Bricht UI- und Plot-Code an mehreren Stellen — "
                  "nur sinnvoll im selben Schritt.")],
            [cell("WP-Wärmesplit verallgemeinern auf Liste von Senken"),
             cell("Wartet auf konkreten Bedarf (z. B. neue Heizung)")],
            [cell("Plugin-Registry mit @register_component-Decorator"),
             cell("Erst sinnvoll, wenn Optimizer-Schleife steht")],
            [cell("Erste automatisierte Tests"),
             cell("Eigene Aktion, parallel laufbar")],
        ],
        [6.5 * cm, 10.5 * cm],
    ))
    out.append(PageBreak())
    return out


def section_2():
    out = [H1("2. Die vier Phasen im Überblick")]
    out.append(P(
        "Das Refactoring kam in fünf Commits, die logisch in vier "
        "Phasen gruppiert sind:"
    ))
    out.append(std_table(
        [cell("<b>Phase</b>"), cell("<b>Commit</b>"), cell("<b>Inhalt</b>")],
        [
            [cell("<b>Phase 1</b><br/>Fundament"),
             cell("86f506a", mono=True),
             cell("Neues Modul <font face='Courier'>_milp_helpers.py</font> "
                  "mit 8 Helferfunktionen. Neue Basisklasse "
                  "<font face='Courier'>MILPComponent</font> mit "
                  "abstrakten Methoden. Battery als erste auf Helfer "
                  "migriert.")],
            [cell("<b>Phase 2</b><br/>Verdichter & Wallbox"),
             cell("26e69de", mono=True),
             cell("HeatPump und Wallbox auf Helfer umgestellt. "
                  "interp_2d ausgelagert nach "
                  "<font face='Courier'>utils/interpolation.py</font>.")],
            [cell("<b>Phase 3</b><br/>Speicher"),
             cell("b47bddb", mono=True),
             cell("ThermalStorage und UnderfloorHeating auf "
                  "<font face='Courier'>add_state_balance</font> umgestellt. "
                  "Energiebilanz-Code halbiert.")],
            [cell("<b>Phase 4a</b><br/>Naming"),
             cell("33316d6", mono=True),
             cell("Variablen-Namen vereinheitlicht: "
                  "<font face='Courier'>sg_state_1 → hp_sg1</font>, "
                  "<font face='Courier'>floor_energy → ufh_floor_energy</font>, "
                  "etc. Konsistente Präfixe pro Komponente.")],
            [cell("<b>Phase 4b</b><br/>Aufräumen"),
             cell("3594ac1", mono=True),
             cell("Tote Imports raus, leere Stub-Methoden bei passiven "
                  "Komponenten gelöscht (sind dank "
                  "<font face='Courier'>Component</font>-Basis nicht mehr "
                  "nötig), Doku in <font face='Courier'>__init__.py</font> "
                  "ergänzt.")],
        ],
        [3.0 * cm, 2.0 * cm, 12.0 * cm],
    ))
    out.append(P(
        "Wichtig: <b>jede Phase hat das Modellverhalten unverändert "
        "gelassen</b>. Die generierten LP-Modelle sind bit-identisch "
        "(bis auf Variablennamen) — das Refactoring ist rein eine "
        "Aufräumaktion am Code, keine Änderung der Optimierung."
    ))
    out.append(PageBreak())
    return out


def section_3():
    out = [H1("3. Zwei-Stufen-Basisklasse: Component vs MILPComponent")]
    out.append(P(
        "Vorher gab es <b>eine</b> Basisklasse "
        "<font face='Courier'>Component</font>, die alle Komponenten — "
        "auch die rein passiven — gezwungen hat, leere Stub-Methoden "
        "<font face='Courier'>get_optimization_variables()</font> und "
        "<font face='Courier'>add_constraints()</font> zu implementieren. "
        "Das war Ballast."
    ))

    out.append(H2("Vorher"))
    out.append(code_block("""class Component(ABC):
    def __init__(self, name, config): ...

    @abstractmethod
    def get_optimization_variables(self, num_steps, model): ...

    @abstractmethod
    def add_constraints(self, model, variables, step_minutes): ...


# Building muss leere Stubs liefern, obwohl es nichts zu liefern hat:
class Building(Component):
    def get_optimization_variables(self, num_steps, model):
        return {}              # toter Code

    def add_constraints(self, model, variables, step_minutes):
        pass                   # toter Code"""))

    out.append(H2("Nachher"))
    out.append(code_block("""class Component(ABC):
    \"\"\"Minimal: Name, Config, enabled-Flag.\"\"\"
    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.enabled = config.get("enabled", True)


class MILPComponent(Component):
    \"\"\"Erweitert Component um die MILP-Pflichten.\"\"\"

    @abstractmethod
    def get_optimization_variables(self, num_steps, model): ...

    @abstractmethod
    def add_constraints(self, model, variables, step_minutes): ...


# Passive Komponente erbt nur Component:
class Building(Component):
    pass                       # keine leeren Stubs noetig

# Aktive Komponente erbt MILPComponent:
class Battery(MILPComponent):
    def get_optimization_variables(self, ...): ...
    def add_constraints(self, ...): ...        # Pflicht durch ABC"""))

    out.append(H2("Wer erbt was?"))
    out.append(std_table(
        [cell("<b>Klasse</b>"), cell("<b>Basis</b>"), cell("<b>Bringt MILP-Beitrag?</b>")],
        [
            [cell("Battery", mono=True),         cell("MILPComponent", mono=True), cell("ja — Lade/Entlade/SOC + 2 binär")],
            [cell("HeatPump", mono=True),        cell("MILPComponent", mono=True), cell("ja — Power + on/off + SG-Ready")],
            [cell("ThermalStorage", mono=True),  cell("MILPComponent", mono=True), cell("ja — Energie + Q_in/Q_demand")],
            [cell("UnderfloorHeating", mono=True), cell("MILPComponent", mono=True), cell("ja — Estrich-Energie + Q_in")],
            [cell("Wallbox", mono=True),         cell("MILPComponent", mono=True), cell("ja — Power + on/off, je Wallbox")],
            [cell("PVSystem", mono=True),        cell("Component", mono=True),     cell("nein — liefert nur Erzeugungs-Zeitreihe")],
            [cell("Building", mono=True),        cell("Component", mono=True),     cell("nein — liefert Heizlast und Massen")],
            [cell("FreshWaterStation", mono=True), cell("Component", mono=True),   cell("nein — Faktor in Bedarfsumrechnung")],
            [cell("ElectricVehicle", mono=True), cell("Component", mono=True),     cell("nein — Datencontainer für Wallbox")],
        ],
        [4.5 * cm, 4.0 * cm, 8.5 * cm],
    ))
    out.append(P(
        "<b>Vorteil:</b> die Trennung macht <i>im Code</i> sichtbar, "
        "welche Komponente etwas zur Optimierung beiträgt. Wer eine neue "
        "Komponente schreibt, weiß sofort, ob sie aktiv (= "
        "<font face='Courier'>MILPComponent</font>) oder passiv "
        "(= <font face='Courier'>Component</font>) ist."
    ))
    out.append(PageBreak())
    return out


def section_4():
    out = [H1("4. Das neue Modul _milp_helpers.py")]
    out.append(P(
        "Bisher hat jede Komponente ihre MILP-Constraints von Hand "
        "geschrieben — was auf 5 Komponenten zu sehr viel Wiederholung "
        "geführt hat. Das neue Modul "
        "<font face='Courier'>emos_light/components/_milp_helpers.py</font> "
        "(196 Zeilen) bündelt diese Muster:"
    ))

    out.append(H2("Inhalt — 8 Hilfsfunktionen"))
    out.append(std_table(
        [cell("<b>Funktion</b>"), cell("<b>Aufgabe</b>"), cell("<b>Wer nutzt sie?</b>")],
        [
            [cell("step_hours(step_minutes)", mono=True),
             cell("min → h Konvertierung (15 → 0,25)"),
             cell("Battery, ThermalStorage, UnderfloorHeating")],
            [cell("steps_for_minutes(min, step_min)", mono=True),
             cell("Anzahl Schritte für eine Zeitspanne"),
             cell("HeatPump (Min-Run/Pause), Wallbox")],
            [cell("make_var_array(name, n, low, high)", mono=True),
             cell("Erstellt Liste von kontinuierlichen LpVariables"),
             cell("alle MILP-Komponenten")],
            [cell("make_binary_array(name, n)", mono=True),
             cell("Erstellt Liste von binären LpVariables"),
             cell("Battery, HeatPump, Wallbox")],
            [cell("add_on_off_power_link(...)", mono=True),
             cell("Koppelt Leistung an EIN/AUS-Binär: P ≤ Pmax·y, "
                  "P ≥ Pmin·y (falls Modulation)"),
             cell("Battery (Lade/Entlade), HeatPump, Wallbox")],
            [cell("add_mutual_exclusion(a, b)", mono=True),
             cell("Erzwingt a[t] + b[t] ≤ 1 für jeden Zeitschritt"),
             cell("Battery (Lade vs Entlade), HeatPump (SG1 vs SG3)")],
            [cell("add_min_run_time(on, n_steps)", mono=True),
             cell("Mindestlaufzeit nach Einschalten"),
             cell("HeatPump")],
            [cell("add_min_pause_time(on, n_steps)", mono=True),
             cell("Mindestpausenzeit nach Ausschalten"),
             cell("HeatPump")],
            [cell("add_min_hold_time(state, n_steps)", mono=True),
             cell("Mindesthaltezeit (semantisch wie min_run)"),
             cell("HeatPump (SG-Ready 1/3)")],
            [cell("add_state_balance(state, init, rhs_fn)", mono=True),
             cell("Energiebilanz mit Sonderfall t=0; rhs_fn liefert "
                  "die rechte Seite pro Zeitschritt"),
             cell("Battery (SOC), ThermalStorage, UnderfloorHeating")],
        ],
        [5.0 * cm, 7.5 * cm, 4.5 * cm],
    ))

    out.append(H2("Beispiel: add_state_balance"))
    out.append(P(
        "Ein typisches Speichermuster ist <b>E[t] = E[t-1] + Zufluss − "
        "Verluste</b>, mit dem Sonderfall, dass für t = 0 ein konstanter "
        "Anfangswert eingesetzt wird. Vorher hat das jede Komponente "
        "selbst geschrieben:"
    ))
    out.append(code_block("""# vorher in battery.py
for t in range(num_steps):
    if t == 0:
        model += (
            soc[t]
            == initial_soc_kwh
            + charge[t] * self.charge_eff * dt_h
            - discharge[t] / self.discharge_eff * dt_h,
            f"{prefix}_soc_balance_{t}",
        )
    else:
        model += (
            soc[t]
            == soc[t - 1]
            + charge[t] * self.charge_eff * dt_h
            - discharge[t] / self.discharge_eff * dt_h,
            f"{prefix}_soc_balance_{t}",
        )"""))

    out.append(P("Nachher mit Helfer:"))
    out.append(code_block("""# nachher in battery.py
add_state_balance(
    model, soc,
    initial=initial_soc_kwh,
    rhs_fn=lambda prev, t: (
        prev
        + charge[t] * self.charge_eff * dt_h
        - discharge[t] / self.discharge_eff * dt_h
    ),
    name=f"{prefix}_soc",
)"""))
    out.append(P(
        "Die Sonderfall-Logik (t = 0 vs. t > 0) steht jetzt einmal in "
        "<font face='Courier'>add_state_balance</font> — drei Komponenten "
        "(Battery, ThermalStorage, UnderfloorHeating) profitieren davon. "
        "Wer eine neue Speicherkomponente baut, schreibt dieselbe "
        "Sonderfall-Behandlung nicht ein viertes Mal."
    ))
    out.append(PageBreak())
    return out


def section_5():
    out = [H1("5. Migrationsbeispiel: Battery vorher/nachher")]
    out.append(P(
        "Die Batterie war als erste Komponente in Phase 1 dran und ist "
        "der beste Vergleichsfall. Die Funktion "
        "<font face='Courier'>add_constraints</font> ist von <b>~60 "
        "Zeilen auf ~30 Zeilen geschrumpft</b>, lesbarer geworden, und "
        "jede Constraint-Gruppe ist über die Helferfunktion "
        "selbsterklärend."
    ))

    out.append(H2("Vorher (~60 Zeilen)"))
    out.append(code_block("""def add_constraints(self, model, variables, step_minutes):
    prefix = f"bat_{self.name}"
    dt_h = step_minutes / 60.0

    charge = variables["batt_charge"]
    discharge = variables["batt_discharge"]
    soc = variables["batt_soc"]
    b_charge = variables["batt_b_charge"]
    b_discharge = variables["batt_b_discharge"]

    num_steps = len(charge)
    initial_soc_kwh = self.initial_soc * self.capacity_kwh

    for t in range(num_steps):
        # Constraint 1: Kein gleichzeitiges Laden und Entladen
        model += (b_charge[t] + b_discharge[t] <= 1, f"{prefix}_no_simul_{t}")

        # Constraint 2: Ladeleistung nur bei aktivem Laden
        model += (charge[t] <= self.max_charge_kw * b_charge[t],
                  f"{prefix}_charge_link_{t}")

        # Constraint 3: Entladeleistung nur bei aktivem Entladen
        model += (discharge[t] <= self.max_discharge_kw * b_discharge[t],
                  f"{prefix}_discharge_link_{t}")

        # Constraint 4/5: SOC-Bilanzgleichung
        if t == 0:
            model += (
                soc[t] == initial_soc_kwh
                + charge[t] * self.charge_eff * dt_h
                - discharge[t] / self.discharge_eff * dt_h,
                f"{prefix}_soc_balance_{t}")
        else:
            model += (
                soc[t] == soc[t - 1]
                + charge[t] * self.charge_eff * dt_h
                - discharge[t] / self.discharge_eff * dt_h,
                f"{prefix}_soc_balance_{t}")"""))

    out.append(H2("Nachher (~30 Zeilen)"))
    out.append(code_block("""def add_constraints(self, model, variables, step_minutes):
    prefix = f"bat_{self.name}"
    dt_h = step_hours(step_minutes)

    charge = variables["bat_charge"]
    discharge = variables["bat_discharge"]
    soc = variables["bat_soc"]
    b_charge = variables["bat_b_charge"]
    b_discharge = variables["bat_b_discharge"]

    # 1) Gegenseitiger Ausschluss Laden/Entladen
    add_mutual_exclusion(model, b_charge, b_discharge,
                         name=f"{prefix}_no_simul")

    # 2+3) Leistung nur wenn Binaer-Variable aktiv
    add_on_off_power_link(model, charge, b_charge,
                          max_power=self.max_charge_kw,
                          name=f"{prefix}_charge_link")
    add_on_off_power_link(model, discharge, b_discharge,
                          max_power=self.max_discharge_kw,
                          name=f"{prefix}_discharge_link")

    # 4) SOC-Bilanzgleichung
    initial_soc_kwh = self.initial_soc * self.capacity_kwh
    add_state_balance(model, soc,
        initial=initial_soc_kwh,
        rhs_fn=lambda prev, t: (
            prev
            + charge[t] * self.charge_eff * dt_h
            - discharge[t] / self.discharge_eff * dt_h
        ),
        name=f"{prefix}_soc")"""))

    out.append(P(
        "Was sich gewonnen hat:"
    ))
    out.append(P(
        "<b>(a) Lesbarkeit:</b> jede Helferaufruf trägt seine Bedeutung "
        "im Namen. <font face='Courier'>add_mutual_exclusion</font> "
        "ist sofort verständlich; <font face='Courier'>"
        "b_charge[t] + b_discharge[t] &lt;= 1</font> braucht zwei "
        "Sekunden Nachdenken."
    ))
    out.append(P(
        "<b>(b) Wartbarkeit:</b> Wenn an der Sonderfall-Logik (t = 0) "
        "ein Bug auftritt, gibt es <b>eine Stelle</b> zum Fixen, nicht "
        "vier. Dasselbe gilt für die Big-M-Formulierung des EIN/AUS-Links."
    ))
    out.append(P(
        "<b>(c) Verlässlichkeit:</b> Die Helfer sind eng dokumentiert "
        "und werden von mehreren Komponenten genutzt — sie sind im "
        "Praxiseinsatz validiert. Eigene Implementierungen pro Komponente "
        "vergrößerten die Bug-Oberfläche."
    ))
    out.append(PageBreak())
    return out


def section_6():
    out = [H1("6. Vereinheitlichte Naming-Convention")]
    out.append(P(
        "In Phase 4 wurden Variablen-Namen so umbenannt, dass jede "
        "Komponente einen <b>einheitlichen Präfix</b> hat. Vorher gab "
        "es Reste alter Iterationen — z. B. "
        "<font face='Courier'>sg_state_1</font> und "
        "<font face='Courier'>floor_energy</font> ohne Komponenten-Präfix, "
        "was im optimizer.py bei der Variablen-Suche zu langen Namen-Listen "
        "geführt hat."
    ))

    out.append(H2("Umbenennungen"))
    out.append(std_table(
        [cell("<b>Komponente</b>"), cell("<b>vorher</b>"), cell("<b>nachher</b>")],
        [
            [cell("HeatPump"), cell("sg_state_1, sg_state_3", mono=True),
             cell("hp_sg1, hp_sg3", mono=True)],
            [cell("HeatPump"), cell("hp_on, hp_power (gleich)", mono=True),
             cell("hp_on, hp_power", mono=True)],
            [cell("UnderfloorHeating"), cell("floor_energy, q_floor_in", mono=True),
             cell("ufh_floor_energy, ufh_q_in", mono=True)],
            [cell("ThermalStorage (WW)"), cell("&lt;prefix&gt;_energy_kwh, "
                                              "&lt;prefix&gt;_q_in, _q_demand", mono=True),
             cell("ww_energy_kwh, ww_q_in, ww_q_demand", mono=True)],
            [cell("Wallbox w"), cell("wb_&lt;name&gt;_power, _on", mono=True),
             cell("(unverändert — war schon einheitlich)", mono=True)],
            [cell("Battery"), cell("batt_charge, batt_discharge, batt_soc", mono=True),
             cell("bat_charge, bat_discharge, bat_soc", mono=True)],
        ],
        [3.5 * cm, 6.5 * cm, 7.0 * cm],
    ))

    out.append(P(
        "Mehrere Wallboxen haben weiterhin individuelle Präfixe "
        "(<font face='Courier'>wb_carport_links_power</font> vs. "
        "<font face='Courier'>wb_carport_rechts_power</font>), und auch "
        "mehrere Batterien blieben kompatibel — der "
        "<font face='Courier'>{self.name}</font>-Anteil im Präfix ist "
        "erhalten."
    ))

    out.append(H2("Wirkung im Optimizer"))
    out.append(P(
        "Im <font face='Courier'>optimizer.py</font> bzw. in den "
        "Plot-Routinen sucht man Variablen jetzt direkt am "
        "Komponenten-Präfix:"
    ))
    out.append(code_block("""# Beispiel: alle Wärmepumpen-Variablen finden
hp_vars = {k: v for k, v in variables.items() if k.startswith("hp_")}

# Estrich-Energie auswerten
floor_energy = variables["ufh_floor_energy"]"""))
    out.append(P(
        "Vorher musste man wissen, dass <font face='Courier'>"
        "sg_state_1</font> auch zur WP gehört, obwohl der Name das nicht "
        "verrät. Das ist eine kleine, aber wirksame Verbesserung der "
        "Lesbarkeit."
    ))
    out.append(PageBreak())
    return out


def section_7():
    out = [H1("7. Ausgelagerte Hilfsmodule")]

    out.append(H2("emos_light/utils/interpolation.py (56 Zeilen)"))
    out.append(P(
        "Die Funktion <font face='Courier'>_interp_2d</font> war "
        "ursprünglich als private Hilfe in "
        "<font face='Courier'>heat_pump.py</font> versteckt. Sie ist "
        "aber mathematisch generisch — bilineare Interpolation auf "
        "einem regulären 2D-Gitter mit Clamping am Rand — und kann "
        "z. B. genauso für Wallbox-Wirkungsgrade über Leistung und "
        "Temperatur, oder für PV-Modulkennlinien, verwendet werden."
    ))
    out.append(P(
        "Sie steht jetzt unter "
        "<font face='Courier'>emos_light/utils/interpolation.py</font> "
        "und exportiert <font face='Courier'>interp_2d(x, y, x_grid, "
        "y_grid, z_grid)</font>. <font face='Courier'>HeatPump</font> "
        "importiert sie wie jede andere Komponente auch — keine "
        "Sonderbehandlung mehr."
    ))

    out.append(H2("emos_light/components/_milp_helpers.py (196 Zeilen)"))
    out.append(P(
        "Beschrieben in Kapitel 4. Wichtig: das führende "
        "<i>Underscore</i> markiert das Modul als <b>komponenten-intern</b> "
        "— Code außerhalb von "
        "<font face='Courier'>emos_light/components/</font> sollte die "
        "Helfer nicht direkt importieren. Wer von außen ein "
        "Energiemodell baut, nutzt die fertige "
        "<font face='Courier'>MILPComponent</font>-API; Helfer sind "
        "Implementierungsdetail."
    ))

    out.append(H2("emos_light/components/__init__.py — Re-Exports"))
    out.append(P(
        "Sauber aufgebauter Public-API-Export. Externer Code kann direkt "
        "<font face='Courier'>from emos_light.components import "
        "Battery, MILPComponent</font> machen, ohne sich um die interne "
        "Modulstruktur zu kümmern."
    ))
    out.append(code_block("""from emos_light.components.base import Component, MILPComponent
from emos_light.components.battery import Battery
from emos_light.components.building import Building
# ...
__all__ = [
    "Component", "MILPComponent",
    "Battery", "Building", "ElectricVehicle", "FreshWaterStation",
    "HeatPump", "PVSystem", "ThermalStorage", "UnderfloorHeating",
    "Wallbox",
]"""))
    out.append(PageBreak())
    return out


def section_8():
    out = [H1("8. Was bedeutet das für eine neue Komponente?")]
    out.append(P(
        "Konkretes Beispiel: jemand soll einen <b>Heizstab</b> "
        "implementieren. Der Heizstab ist eine neue Wärmequelle für "
        "den WW-Speicher mit COP = 1 und einer EIN/AUS-Binärvariable. "
        "So sieht das nach dem Refactoring aus:"
    ))

    out.append(H2("Skeleton (~50 Zeilen)"))
    out.append(code_block("""# emos_light/components/heater_rod.py

from typing import Any
from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_on_off_power_link, make_binary_array, make_var_array,
)


class HeaterRod(MILPComponent):
    \"\"\"Elektrischer Heizstab im WW-Speicher (COP = 1).

    Config:
        max_power_kw (float): Heizstab-Leistung
        min_power_kw (float): Min-Modulation (0 bei einfachem Schaltbetrieb)
    \"\"\"

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.max_power_kw = config.get("max_power_kw", 6.0)
        self.min_power_kw = config.get("min_power_kw", 0.0)

    def get_optimization_variables(self, num_steps, model):
        return {
            "hr_power": make_var_array("hr_power", num_steps,
                                        low=0, high=self.max_power_kw),
            "hr_on":    make_binary_array("hr_on", num_steps),
        }

    def add_constraints(self, model, variables, step_minutes):
        add_on_off_power_link(
            model, variables["hr_power"], variables["hr_on"],
            max_power=self.max_power_kw, min_power=self.min_power_kw,
            name="hr",
        )"""))

    out.append(P(
        "Damit ist die Komponente an sich fertig — ihre interne "
        "Logik ist 100 % komplett. Was außerhalb noch nötig ist:"
    ))
    out.append(std_table(
        [cell("<b>Schritt</b>"), cell("<b>Datei</b>"), cell("<b>~Zeilen</b>")],
        [
            [cell("Komponente schreiben"),
             cell("components/heater_rod.py", mono=True), cell("~50")],
            [cell("Re-Export hinzufügen"),
             cell("components/__init__.py", mono=True), cell("2")],
            [cell("Default-Config-Sektion"),
             cell("core/config.py", mono=True), cell("~10")],
            [cell("Instanziierung"),
             cell("core/scenario.build_components()", mono=True), cell("~3")],
            [cell("Strom-Bilanz: hr_power als Verbrauch"),
             cell("optimization/optimizer.py", mono=True), cell("~3")],
            [cell("Wärme-Bilanz: hr_power · 1 in WW einspeisen"),
             cell("optimization/optimizer.py", mono=True), cell("~5")],
            [cell("Result-Feld"),
             cell("core/types.py + optimizer.py Ende", mono=True), cell("~5")],
            [cell("UI-Block (Streamlit)"),
             cell("app.py", mono=True), cell("~30")],
        ],
        [6.0 * cm, 6.0 * cm, 2.0 * cm],
    ))
    out.append(P(
        "<b>Summe ~110 Zeilen, verteilt auf 6 Dateien.</b> Vorher waren "
        "es eher ~150 Zeilen, weil die MILP-Constraints in der "
        "Komponente selbst dupliziert worden wären."
    ))

    out.append(H2("Vergleich Aufwand vorher/nachher"))
    out.append(std_table(
        [cell("<b>Aufgabe</b>"), cell("<b>vorher</b>"), cell("<b>nachher</b>")],
        [
            [cell("EIN/AUS-Power-Link schreiben"),
             cell("~10 Zeilen handcodiert"), cell("1 Zeile add_on_off_power_link(...)")],
            [cell("Variable-Array bauen"),
             cell("3-4 Zeilen for-loop"), cell("1 Zeile make_var_array(...)")],
            [cell("Energiebilanz (mit t=0)"),
             cell("~12 Zeilen if/else"), cell("3 Zeilen add_state_balance(...)")],
            [cell("Mindestlauf/-pause"),
             cell("~8 Zeilen verschachtelter Loop"), cell("1 Zeile add_min_run_time(...)")],
            [cell("MILP-Vertrag durchsetzen"),
             cell("Konvention, kein Linter-Check"), cell("@abstractmethod erzwingt es")],
        ],
        [6.0 * cm, 5.5 * cm, 5.5 * cm],
    ))
    out.append(PageBreak())
    return out


def section_9():
    out = [H1("9. Was noch offen ist (zweite Refactoring-Stufe)")]
    out.append(P(
        "Das jetzt durchgeführte Refactoring hat den <b>Komponenten-"
        "Code</b> aufgeräumt. Eine zweite, größere Stufe würde den "
        "<b>Optimizer und die Result-Schicht</b> betreffen. Sie ist "
        "bewusst noch nicht angefasst, weil sie an mehreren Stellen "
        "gleichzeitig eingreifen muss."
    ))

    out.append(H2("Offene Punkte"))
    out.append(std_table(
        [cell("<b>Punkt</b>"), cell("<b>Zustand heute</b>"),
         cell("<b>Zielzustand</b>")],
        [
            [cell("Optimizer-Schleife"),
             cell("500-Zeilen-Methode mit "
                  "<font face='Courier'>if self.battery: …</font> "
                  "an mehreren Stellen"),
             cell("<font face='Courier'>for c in self.components:</font>, "
                  "jede Komponente liefert ihren Bilanz-Beitrag selbst")],
            [cell("Energiebilanz-Beiträge"),
             cell("Im Optimizer hartcodiert "
                  "(supply += variables['batt_discharge'] etc.)"),
             cell("Methoden auf der Komponente: "
                  "<font face='Courier'>electrical_supply()</font>, "
                  "<font face='Courier'>electrical_demand()</font>, "
                  "<font face='Courier'>heat_supply(senke=…)</font>")],
            [cell("OptimizationResult"),
             cell("Dataclass mit hartcodierten Feldern pro Komponente"),
             cell("Dict-basiert; jede Komponente schreibt unter ihrem "
                  "Namen rein")],
            [cell("WP-Wärmesplit"),
             cell("Hartcodiert auf 2 Senken (Floor + WW)"),
             cell("Liste von Wärmesenken, Optimizer summiert generisch")],
            [cell("Plugin-Registrierung"),
             cell("Manuell in scenario.build_components() eintragen"),
             cell("<font face='Courier'>@register_component(...)</font>-"
                  "Decorator + automatische UI-Generierung")],
            [cell("Tests"),
             cell("Keine"),
             cell("Smoketest pro Komponente: einzeln aktivieren, "
                  "Optimum existiert, Werte plausibel")],
        ],
        [4.5 * cm, 6.5 * cm, 6.0 * cm],
    ))

    out.append(H2("Geschätzter Aufwand zweite Stufe"))
    out.append(P(
        "Realistisch ein <b>Sprint von 2–3 Tagen</b> wenn alles "
        "zusammen gemacht wird. Der Hauptaufwand ist nicht der "
        "Optimizer selbst (eher 200 Zeilen Refactoring), sondern die "
        "<b>UI- und Plot-Anpassungen</b>, weil "
        "<font face='Courier'>OptimizationResult</font> aktuell an "
        "vielen Stellen mit punktnotation "
        "(<font face='Courier'>result.batt_charge_kw</font>) abgefragt "
        "wird. Diese Stellen müssen alle umgestellt werden auf "
        "<font face='Courier'>result['batt']['charge_kw']</font>."
    ))
    out.append(P(
        "Die heutige Refactoring-Stufe ist <b>Voraussetzung</b> für "
        "die zweite — ohne saubere Komponenten-API wären die "
        "Generalisierungen im Optimizer nicht möglich. Insofern "
        "nichts verschwendet, wenn die zweite Stufe später kommt."
    ))
    out.append(PageBreak())
    return out


def section_10():
    out = [H1("10. Zusammenfassung")]
    out.append(P(
        "Vier Phasen, fünf Commits, ein Ziel: die Komponenten-Code "
        "konsistent und duplikatfrei machen, ohne das Modellverhalten "
        "zu verändern."
    ))

    bullets = [
        ("Zwei-Stufen-Basis",
         "Component (passiv) und MILPComponent (mit Variablen + "
         "Constraints) — sichtbar im Code, nicht mehr durch leere "
         "Stubs verschleiert."),
        ("MILP-Helfer",
         "Acht wiederverwendbare Bausteine in _milp_helpers.py "
         "decken die Standardmuster ab. Komponenten schreiben jetzt "
         "Intent statt Boilerplate."),
        ("Konsistente Namen",
         "Jede Komponente hat einen Präfix (hp_, ufh_, ww_, bat_, "
         "wb_*, hr_) — Variablen sind auf einen Blick zuordbar."),
        ("Helfer wiederverwendbar gemacht",
         "interp_2d in utils/interpolation.py — verfügbar für jede "
         "Komponente, nicht nur die Wärmepumpe."),
        ("Verhaltensgleich",
         "Alle Optimierungs-Outputs sind bit-identisch (außer "
         "Variablennamen). Die Refactoring-Phasen sind sicher und "
         "rückbaubar."),
    ]
    for title, desc in bullets:
        out.append(P(f"<b>{title}.</b> {desc}"))

    out.append(P(
        "Praktischer Effekt: <b>eine neue Komponente schreibt sich um "
        "ein Drittel kürzer</b>, mit besserer Lesbarkeit und weniger "
        "Bug-Oberfläche. Eine zweite Refactoring-Stufe (Optimizer-"
        "Modularisierung, dict-Ergebnis, Plugin-Registry) bleibt das "
        "logische nächste Ziel — sie wird auf dieser Basis sauber "
        "aufsetzen."
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
        title="EMOS Light - Codebase nach dem Refactoring",
        author="EMOS Light Projektteam",
    )

    story = []
    story += build_cover()
    story += build_toc()
    story += section_1()
    story += section_2()
    story += section_3()
    story += section_4()
    story += section_5()
    story += section_6()
    story += section_7()
    story += section_8()
    story += section_9()
    story += section_10()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "EMOS_Light_Codebase_Refactored.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
