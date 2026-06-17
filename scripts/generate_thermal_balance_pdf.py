"""Erzeugt ein PDF mit den thermischen Bilanzen des Gebaeudemodells (Mai 2026).

Verwendet matplotlib (mathtext) fuer Formeldarstellung und reportlab fuer Layout.
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def render_math(latex: str, fontsize: int = 14, dpi: int = 200) -> Image:
    """Render eines LaTeX-Mathstrings als matplotlib-Image fuer reportlab."""
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.patch.set_alpha(0.0)
    fig.text(0, 0, f"${latex}$", fontsize=fontsize)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                pad_inches=0.05, transparent=True)
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    # Skalieren auf vernuenftige Breite
    scale = 0.45
    img.drawWidth = img.imageWidth * scale / 2.0
    img.drawHeight = img.imageHeight * scale / 2.0
    return img


def H1(text: str, styles) -> Paragraph:
    return Paragraph(text, styles["H1"])


def H2(text: str, styles) -> Paragraph:
    return Paragraph(text, styles["H2"])


def P(text: str, styles) -> Paragraph:
    return Paragraph(text, styles["Body"])


def Eq(latex: str) -> Image:
    return render_math(latex, fontsize=16)


def Eq_small(latex: str) -> Image:
    return render_math(latex, fontsize=12)


# ----------------------------------------------------------------------
# Document
# ----------------------------------------------------------------------

def build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {}
    styles["Title"] = ParagraphStyle(
        "Title", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=22, leading=26,
        textColor=colors.HexColor("#0B3D91"), spaceAfter=8,
    )
    styles["Subtitle"] = ParagraphStyle(
        "Subtitle", parent=base["Normal"],
        fontName="Helvetica-Oblique", fontSize=12, leading=15,
        textColor=colors.HexColor("#444444"), spaceAfter=18,
    )
    styles["H1"] = ParagraphStyle(
        "H1", parent=base["Heading1"],
        fontName="Helvetica-Bold", fontSize=16, leading=20,
        textColor=colors.HexColor("#0B3D91"),
        spaceBefore=14, spaceAfter=8,
    )
    styles["H2"] = ParagraphStyle(
        "H2", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=13, leading=17,
        textColor=colors.HexColor("#1F4E79"),
        spaceBefore=10, spaceAfter=6,
    )
    styles["Body"] = ParagraphStyle(
        "Body", parent=base["BodyText"],
        fontName="Helvetica", fontSize=10.5, leading=14,
        textColor=colors.black, spaceAfter=6, alignment=0,
    )
    styles["Caption"] = ParagraphStyle(
        "Caption", parent=base["Italic"],
        fontName="Helvetica-Oblique", fontSize=9, leading=12,
        textColor=colors.HexColor("#555555"), spaceAfter=10,
    )
    styles["Mono"] = ParagraphStyle(
        "Mono", parent=base["Code"],
        fontName="Courier", fontSize=9, leading=12,
        textColor=colors.HexColor("#222222"), spaceAfter=8,
    )
    return styles


def topology_table() -> Table:
    """ASCII-artige Topologie als Tabelle."""
    data = [
        ["Erzeuger", "Speicher", "Senke / Bedarf"],
        ["Waermepumpe", "Estrich (FBH)", "Raum (T_innen)"],
        ["", "WW-Speicher", "Brauchwasser"],
        ["", "", "Aussenluft (Verlust)"],
    ]
    t = Table(data, colWidths=[5*cm, 5*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F2F6FB")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def symbol_table() -> Table:
    """Glossar wichtiger Symbole."""
    rows = [
        ["Symbol", "Einheit", "Bedeutung"],
        ["T_innen(t)", "°C", "Raumlufttemperatur (MILP-Variable)"],
        ["T_floor(t)", "°C", "Estrich-Oberflaechentemperatur"],
        ["T_aus(t)", "°C", "Aussentemperatur (Eingangsdaten)"],
        ["E_floor(t)", "kWh", "Im Estrich gespeicherte Energie ueber T_min"],
        ["E_ww(t)", "kWh", "Im WW-Speicher gespeicherte Energie"],
        ["q_floor_in(t)", "kW", "Waermestrom WP -> Estrich"],
        ["q_floor_to_room(t)", "kW", "Waermestrom Estrich -> Raum"],
        ["q_loss(t)", "kW", "Verlust Raum -> Aussenluft"],
        ["q_ww_in / q_ww_out", "kW", "Zu-/Abfluss WW-Speicher"],
        ["P_WP_el(t)", "kW", "Elektrische WP-Leistung"],
        ["COP_floor / COP_ww", "-", "COP fuer Heiz- bzw. WW-Pfad"],
        ["UA", "W/K", "Gesamt-Waermedurchgang Huelle + Lueftung"],
        ["C_floor", "kWh/K", "Thermische Kapazitaet Estrich"],
        ["C_room", "kWh/K", "Thermische Kapazitaet Raum (Wand + Luft)"],
        ["h_floor · A", "W/K", "Waermeuebergang Estrich -> Raum"],
        ["dt", "h", "Zeitschritt (Default 0.25 h = 15 min)"],
    ]
    t = Table(rows, colWidths=[4.2*cm, 2.2*cm, 9*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Oblique"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8F9FB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F2F6FB"), colors.HexColor("#FFFFFF")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def parameter_table() -> Table:
    """Default-Parameterwerte fuer das Referenz-EFH (Gebaeudegruppe Mai 2026)."""
    rows = [
        ["Parameter", "Wert", "Quelle / Bemerkung"],
        ["A_Wohn", "150 m²", "DEFAULT_CONFIG.building.heated_area_m2"],
        ["l × b × h", "15 × 10 × 2.5 m", "Geometrie EFH"],
        ["U_Wand", "0.2 W/(m²·K)", "KfW55-Niveau"],
        ["U_Fenster", "0.9 W/(m²·K)", "Dreifachverglasung"],
        ["U_Dach/Boden", "0.4 W/(m²·K)", "kombiniert"],
        ["n_Lueft", "0.17 W/(m³·K)", "spezifischer Lueftungsverlust"],
        ["UA_total", "≈ 178 W/K", "Transmission + Lueftung (EFH-Default)"],
        ["d_Estrich", "0.065 m", "Estrichdicke"],
        ["ρ_Estrich", "2000 kg/m³", "Zementestrich"],
        ["c_Estrich", "1000 J/(kg·K)", "spez. Waermekapazitaet"],
        ["C_floor", "≈ 5.4 kWh/K", "Estrich-Masse · c"],
        ["C_room", "≈ 7.9 kWh/K", "Wand (50 Wh/m²K · A) + Luft"],
        ["h_floor", "10 W/(m²·K)", "Boden->Raum Waermeuebergang"],
        ["T_VL,Heiz", "35 °C", "Vorlauf FBH"],
        ["T_VL,WW", "55 °C", "Vorlauf WW"],
        ["[T_min, T_max]", "[20, 24] °C", "Komfortband (Slack-bestraft)"],
    ]
    t = Table(rows, colWidths=[4.5*cm, 4.0*cm, 7*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F2F6FB"), colors.HexColor("#FFFFFF")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def equation_block(title: str, latex: str, styles) -> list:
    """Kompakter Block: Untertitel + zentrierte Formel."""
    return [
        Paragraph(f"<b>{title}</b>", styles["Body"]),
        Spacer(1, 2),
        Eq(latex),
        Spacer(1, 6),
    ]


# ----------------------------------------------------------------------
# Inhalt
# ----------------------------------------------------------------------

def build_story(styles) -> list:
    story = []

    # Titelseite
    story.append(Paragraph(
        "Thermische Bilanzen des Gebaeudemodells",
        styles["Title"],
    ))
    story.append(Paragraph(
        "EMOS Light — MILP-Erweiterung Mai 2026",
        styles["Subtitle"],
    ))
    story.append(P(
        "Dieses Dokument beschreibt die thermischen Energiebilanzen, die der MILP-Optimierer "
        "von EMOS Light zur Energiekostenoptimierung loest. Im Mittelpunkt stehen die drei "
        "thermischen Speicher- bzw. Bilanzknoten Estrich, Raumluft und Warmwasser-Speicher "
        "sowie die Kopplung an die Waermepumpe als einzigem Erzeuger.",
        styles,
    ))
    story.append(Spacer(1, 8))

    # 1. Topologie
    story.append(H1("1 Topologie der Waermestroeme", styles))
    story.append(P(
        "Die Waermepumpe ist der einzige Waermeerzeuger und versorgt zwei Senken: "
        "den Estrich (Fussbodenheizung) und den Warmwasserspeicher. Der Estrich gibt seine "
        "Waerme an den Raum ab; der Raum verliert sie ueber die Gebaeudehuelle und Lueftung "
        "an die Aussenluft. Der Warmwasserspeicher wird ueber die Frischwasserstation an "
        "den Brauchwasserbedarf gekoppelt.",
        styles,
    ))
    story.append(Spacer(1, 4))
    story.append(topology_table())
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Abb. 1: Senken-Bilanzknoten im MILP — <i>floor</i>, <i>room</i>, <i>ww</i>.",
        styles["Caption"],
    ))

    # 2. Estrich
    story.append(H1("2 Estrich (Fussbodenheizung)", styles))
    story.append(P(
        "Der Estrich ist der dominante thermische Speicher des Heizpfades. Statt mit "
        "Temperaturen rechnet das Modell mit der gespeicherten Energie ueber dem unteren "
        "Komfortpunkt T_min,floor. Das macht alle Beziehungen affin und damit LP-kompatibel.",
        styles,
    ))
    story.append(H2("2.1 Speicherkapazitaet", styles))
    story.extend(equation_block(
        "Thermische Kapazitaet (Estrichplatte):",
        r"C_{\mathrm{floor}} \;=\; \frac{\rho_{\mathrm{Estrich}}\, c_{\mathrm{Estrich}}\, "
        r"A_{\mathrm{floor}}\, d_{\mathrm{Estrich}}}{3.6 \cdot 10^{6}} "
        r"\quad [\mathrm{kWh/K}]",
        styles,
    ))
    story.extend(equation_block(
        "Lineare Energie/Temperatur-Relation:",
        r"T_{\mathrm{floor}}(t) \;=\; T_{\mathrm{min,floor}} + "
        r"\frac{E_{\mathrm{floor}}(t)}{C_{\mathrm{floor}}}",
        styles,
    ))

    story.append(H2("2.2 Energiebilanz Estrich", styles))
    story.append(P(
        "Die zeitliche Aenderung der Estrich-Energie folgt aus Waermezufuhr durch die "
        "Fussbodenheizung minus Waermestrom an den Raum. Diskretisiert nach explizitem "
        "Euler (alle Fluesse aus Zustaenden bei t-1):",
        styles,
    ))
    story.extend(equation_block(
        "Zustandsuebergang Estrich:",
        r"E_{\mathrm{floor}}(t) \;=\; E_{\mathrm{floor}}(t{-}1) + "
        r"q_{\mathrm{floor,in}}(t)\,\Delta t \;-\; q_{\mathrm{floor\to room}}(t)\,\Delta t",
        styles,
    ))
    story.extend(equation_block(
        "Newton-Waermeuebergang Boden -> Raum:",
        r"q_{\mathrm{floor\to room}}(t) \;=\; \frac{h_{\mathrm{floor}}\, A_{\mathrm{floor}}}{1000}\,"
        r"\left(T_{\mathrm{floor}}(t{-}1) - T_{\mathrm{innen}}(t{-}1)\right) \quad [\mathrm{kW}]",
        styles,
    ))
    story.append(P(
        "Wichtig: q_floor_to_room ist eine eigene MILP-Variable mit dieser linearen Kopplung "
        "an Estrich- und Raumtemperatur. Damit erscheint derselbe Waermestrom physikalisch "
        "konsistent in beiden Energiebilanzen.",
        styles,
    ))

    story.append(PageBreak())

    # 3. Raum
    story.append(H1("3 Raumluftbilanz (MILP-Erweiterung Mai 2026)", styles))
    story.append(P(
        "Vor Mai 2026 war die Innentemperatur keine Optimierungsvariable; der Heizbedarf wurde "
        "ausserhalb des Solvers ueber eine Heizkennlinie vorgegeben. Damit \"sah\" der Solver "
        "weder den eigentlichen Komfortzustand noch die Verluste an die Aussenluft. Mit der "
        "Mai-2026-Erweiterung uebernimmt der MILP die Raumbilanz explizit.",
        styles,
    ))
    story.append(H2("3.1 Energiebilanz Raum", styles))
    story.extend(equation_block(
        "Zustandsuebergang Raum (Lumped-Capacitance, explizites Euler):",
        r"C_{\mathrm{room}}\,\left(T_{\mathrm{innen}}(t) - T_{\mathrm{innen}}(t{-}1)\right) \;=\;"
        r"\left(q_{\mathrm{floor\to room}}(t) - q_{\mathrm{loss}}(t)\right)\,\Delta t",
        styles,
    ))
    story.extend(equation_block(
        "Waermeverlust an die Aussenluft (Transmission + Lueftung):",
        r"q_{\mathrm{loss}}(t) \;=\; \frac{UA}{1000}\,\left(T_{\mathrm{innen}}(t{-}1) "
        r"- T_{\mathrm{aussen}}(t)\right) \quad [\mathrm{kW}]",
        styles,
    ))
    story.extend(equation_block(
        "Aufgeloest nach T_innen(t):",
        r"T_{\mathrm{innen}}(t) \;=\; T_{\mathrm{innen}}(t{-}1) + "
        r"\frac{\Delta t}{C_{\mathrm{room}}}\,\left(q_{\mathrm{floor\to room}}(t) "
        r"- q_{\mathrm{loss}}(t)\right)",
        styles,
    ))

    story.append(H2("3.2 UA-Wert der Gebaeudehuelle", styles))
    story.append(P(
        "UA setzt sich aus Transmission und Lueftung zusammen. Die Transmission wird ueber "
        "die einzelnen Bauteilflaechen aufsummiert (Aussenwand, Fenster, Dach + Bodenplatte). "
        "Die Lueftung wird ueber das beheizte Volumen ausgedrueckt.",
        styles,
    ))
    story.extend(equation_block(
        "Transmission:",
        r"UA_{\mathrm{trans}} \;=\; U_{\mathrm{Wand}}\, A_{\mathrm{Wand}} + "
        r"U_{\mathrm{Fenster}}\, A_{\mathrm{Fenster}} + U_{\mathrm{Dach}}\, A_{\mathrm{Grund}}",
        styles,
    ))
    story.extend(equation_block(
        "Lueftung:",
        r"UA_{\mathrm{lueft}} \;=\; n_{\mathrm{lueft}}\, V_{\mathrm{Gebaeude}}",
        styles,
    ))
    story.extend(equation_block(
        "Gesamt:",
        r"UA \;=\; UA_{\mathrm{trans}} + UA_{\mathrm{lueft}}",
        styles,
    ))

    story.append(H2("3.3 Raumkapazitaet C_room", styles))
    story.append(P(
        "C_room beschreibt, wieviel Waerme der Raum (Wand + Luft) je Kelvin "
        "Temperaturaenderung aufnimmt. Die Estrich-Kapazitaet ist hier NICHT enthalten — "
        "der Estrich ist ein separater Speicher mit eigener Bilanz.",
        styles,
    ))
    story.extend(equation_block(
        "Lumped-Capacitance des Raumes (Wand-Anteil + Luft-Anteil):",
        r"C_{\mathrm{room}} \;=\; c_{\mathrm{Wand}}\, A_{\mathrm{Wohn}} "
        r"\;+\; \frac{V_{\mathrm{Gebaeude}}\, \rho_{\mathrm{Luft}}\, c_{\mathrm{p,Luft}}}{3.6\cdot 10^{6}}",
        styles,
    ))

    story.append(H2("3.4 Komfortband als Soft-Constraint", styles))
    story.append(P(
        "Statt T_innen hart zu binden, laesst der Solver Komfortverletzungen zu — bestraft "
        "mit einem hohen Preis (im Code UNMET_HEAT_PENALTY_CT = 500 ct/kWh). Slack-Variablen "
        "absorbieren Unter- oder Ueberschreitungen:",
        styles,
    ))
    story.extend(equation_block(
        "Komfort-Slack (Unterschreitung):",
        r"T_{\mathrm{innen}}(t) + s_{\mathrm{low}}(t) \;\geq\; T_{\mathrm{min,Komfort}},"
        r"\quad s_{\mathrm{low}}(t) \geq 0",
        styles,
    ))
    story.extend(equation_block(
        "Komfort-Slack (Ueberschreitung):",
        r"T_{\mathrm{innen}}(t) - s_{\mathrm{high}}(t) \;\leq\; T_{\mathrm{max,Komfort}},"
        r"\quad s_{\mathrm{high}}(t) \geq 0",
        styles,
    ))
    story.extend(equation_block(
        "Penalty-Beitrag in der Zielfunktion:",
        r"\sum_{t}\left(s_{\mathrm{low}}(t) + s_{\mathrm{high}}(t)\right)\cdot c_{\mathrm{pen}}\cdot \Delta t",
        styles,
    ))

    story.append(PageBreak())

    # 4. WP
    story.append(H1("4 Waermepumpe als Erzeuger", styles))
    story.append(P(
        "Die Waermepumpe ist die einzige Waermequelle. Sie wandelt elektrische Leistung in "
        "thermische Leistung um — der Wirkungsgrad ist temperaturabhaengig und wird ueber "
        "ein 2D-Kennfeld (Vaillant aroTHERM plus VWL 105/6) je nach Aussen- und "
        "Vorlauftemperatur interpoliert.",
        styles,
    ))
    story.extend(equation_block(
        "COP fuer Heizpfad und Warmwasserpfad:",
        r"\mathrm{COP}_{\mathrm{floor}}(t) = f(T_{\mathrm{aus}}(t),\, T_{\mathrm{VL,Heiz}}),\quad "
        r"\mathrm{COP}_{\mathrm{ww}}(t) = f(T_{\mathrm{aus}}(t),\, T_{\mathrm{VL,WW}})",
        styles,
    ))
    story.extend(equation_block(
        "Aufteilung der elektrischen Leistung (bei zwei aktiven Senken):",
        r"P_{\mathrm{WP,el}}(t) \;=\; P_{\mathrm{el,floor}}(t) + P_{\mathrm{el,ww}}(t)",
        styles,
    ))
    story.extend(equation_block(
        "Thermische Leistung pro Pfad:",
        r"q_{\mathrm{floor,in}}(t) = \mathrm{COP}_{\mathrm{floor}}(t)\cdot P_{\mathrm{el,floor}}(t),\quad "
        r"q_{\mathrm{ww,in}}(t)  = \mathrm{COP}_{\mathrm{ww}}(t)\cdot P_{\mathrm{el,ww}}(t)",
        styles,
    ))
    story.append(P(
        "Modulation und Schaltverhalten der WP werden mit binaeren Variablen (hp_on, sg1, sg3) "
        "und Mindestlauf-/Pausenzeit-Constraints abgebildet. Der SG-Ready-Zustand 3 erhoeht "
        "die zulaessige WW-Speichertemperatur fuer EVU-induzierte Verstaerkungssignale.",
        styles,
    ))

    # 5. WW-Speicher
    story.append(H1("5 Warmwasserspeicher", styles))
    story.append(P(
        "Der WW-Speicher ist analog zum Estrich ein Energie-Bilanzknoten — allerdings ohne "
        "Kopplung an einen Raum. Er entlaedt sich ueber die Frischwasserstation an den "
        "Brauchwasserbedarf und verliert zusaetzlich Waerme an die Umgebung.",
        styles,
    ))
    story.extend(equation_block(
        "Energiebilanz WW-Speicher:",
        r"E_{\mathrm{ww}}(t) \;=\; E_{\mathrm{ww}}(t{-}1) + q_{\mathrm{ww,in}}(t)\,\Delta t "
        r"- q_{\mathrm{ww,out}}(t)\,\Delta t - q_{\mathrm{ww,loss}}(t)\,\Delta t",
        styles,
    ))
    story.extend(equation_block(
        "Standby-Verlust:",
        r"q_{\mathrm{ww,loss}}(t) \;=\; \frac{UA_{\mathrm{Speicher}}}{1000}\,"
        r"\left(T_{\mathrm{ww}}(t{-}1) - T_{\mathrm{Umgebung}}\right)",
        styles,
    ))
    story.append(P(
        "Komfortperioden werden ueber zeitabhaengige Mindestenergien E_ww,min(t) erzwungen "
        "(harte Constraints) — z.B. morgens und abends, wenn Warmwasser gebraucht wird.",
        styles,
    ))

    story.append(PageBreak())

    # 6. Senkenbilanz im MILP
    story.append(H1("6 Generische Senkenbilanz im MILP", styles))
    story.append(P(
        "Der Optimierer baut fuer jede aktive thermische Senke s (floor, room, ww) generisch "
        "eine Bilanzgleichung pro Zeitschritt:",
        styles,
    ))
    story.extend(equation_block(
        "Allgemeine Senken-Bilanz:",
        r"\sum_{c}\, q_{\mathrm{supply}}^{(c)}(t,\,s) \;=\; \sum_{c}\, q_{\mathrm{demand}}^{(c)}(t,\,s)\quad"
        r"\forall t,\, \forall s \in \{\mathrm{floor},\mathrm{room},\mathrm{ww}\}",
        styles,
    ))
    story.append(P(
        "Jede MILP-Komponente entscheidet selbst, was sie zu welcher Senke beisteuert:",
        styles,
    ))
    rows = [
        ["Komponente", "Senke", "supply", "demand"],
        ["HeatPump", "floor", "COP_floor · P_el,floor", "—"],
        ["HeatPump", "ww", "COP_ww · P_el,ww", "—"],
        ["UnderfloorHeating", "floor", "—", "q_floor_in"],
        ["UnderfloorHeating", "room", "q_floor_to_room", "—"],
        ["Building", "room", "—", "C_room·ΔT/Δt + UA·ΔT/1000"],
        ["ThermalStorage (WW)", "ww", "—", "q_ww_in + Verluste + Last"],
    ]
    t = Table(rows, colWidths=[3.8*cm, 2.0*cm, 4.5*cm, 5.0*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F2F6FB"), colors.HexColor("#FFFFFF")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Tab. 1: Bilanzbeitraege jeder Komponente pro Senke.",
        styles["Caption"],
    ))
    story.append(P(
        "Dadurch entsteht die Raum-Bilanz aus Abschnitt 3.1 vollautomatisch: UFH liefert "
        "q_floor_to_room als supply zur Senke <i>room</i>, Building liefert die dynamische "
        "Demand-Seite — Phase E des Optimierers setzt supply == demand und damit wird die "
        "Zustandsgleichung im Solver geschlossen.",
        styles,
    ))

    # 7. Zielfunktion
    story.append(H1("7 Zielfunktion (Auszug)", styles))
    story.append(P(
        "Die Zielfunktion minimiert die Netzkosten ueber den Horizont, abzueglich der "
        "Einspeiseerloese, zuzueglich der Strafkosten fuer Komfortverletzungen und der "
        "Batterie-Alterungskosten:",
        styles,
    ))
    story.extend(equation_block(
        "Gesamtkosten:",
        r"\min\;\;\sum_{t}\left[\,c_{\mathrm{Bezug}}(t)\,P_{\mathrm{bezug}}(t)\,\Delta t "
        r"\;-\; c_{\mathrm{ein}}\,P_{\mathrm{ein}}(t)\,\Delta t\,\right] \;+\; "
        r"c_{\mathrm{pen}}\sum_{t}\left(s_{\mathrm{low}}(t) + s_{\mathrm{high}}(t)\right)\Delta t",
        styles,
    ))

    # 8. Symbole
    story.append(PageBreak())
    story.append(H1("Anhang A: Symbolverzeichnis", styles))
    story.append(symbol_table())

    story.append(H1("Anhang B: Default-Parameter (Referenz-EFH)", styles))
    story.append(parameter_table())
    story.append(Paragraph(
        "Quelle: DEFAULT_CONFIG in <i>emos_light/core/config.py</i> sowie das XLSX-Lehrbeispiel "
        "der Gebaeudegruppe (Mai 2026).",
        styles["Caption"],
    ))

    return story


def main(out_path: Path) -> None:
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2.0*cm, rightMargin=2.0*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="EMOS Light — Thermische Bilanzen des Gebaeudes",
        author="EMOS Light Projektgruppe",
    )
    story = build_story(styles)
    doc.build(story)
    print(f"PDF erzeugt: {out_path}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    out = here.parent / "docs" / "thermische_bilanzen.pdf"
    out.parent.mkdir(exist_ok=True)
    main(out)
