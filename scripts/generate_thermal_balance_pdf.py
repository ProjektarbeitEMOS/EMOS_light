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
        ["Erzeuger", "Speicher (Zustand)", "Senke / Kopplung"],
        ["Waermepumpe (Q_WP)", "Estrich  T_B", "-> Raum  T_R"],
        ["", "Raumluft  T_R", "-> Wand + Fenster/Lueftung"],
        ["", "Aussenwand  T_W (NEU)", "-> Aussenluft (traege)"],
        ["", "WW-Speicher", "-> Brauchwasser"],
        ["solare + interne Gewinne", "-> Raum  T_R", ""],
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
        ["T_innen(t) = T_R", "°C", "Raumlufttemperatur (MILP-Variable)"],
        ["T_wand(t) = T_W", "°C", "Aussenwandtemperatur (MILP-Variable, NEU)"],
        ["T_floor(t) = T_B", "°C", "Estrich-Temperatur"],
        ["T_aus(t)", "°C", "Aussentemperatur (Eingangsdaten)"],
        ["E_floor(t)", "kWh", "Im Estrich gespeicherte Energie ueber T_min"],
        ["E_ww(t)", "kWh", "Im WW-Speicher gespeicherte Energie"],
        ["q_floor_in(t)", "kW", "Waermestrom WP -> Estrich"],
        ["q_floor_to_room(t)", "kW", "Waermestrom Estrich -> Raum"],
        ["q_loss(t)", "kW", "Gesamtverlust Raum -> Aussen (direkt + Wandpfad)"],
        ["Q_g,R(t)", "W", "solare + interne Raumgewinne (NEU)"],
        ["q_ww_in / q_ww_out", "kW", "Zu-/Abfluss WW-Speicher"],
        ["P_WP_el(t)", "kW", "Elektrische WP-Leistung"],
        ["COP_floor / COP_ww", "-", "COP fuer Heiz- bzw. WW-Pfad"],
        ["UA_direkt", "W/K", "direkter Verlust: Fenster + Dach + Lueftung"],
        ["k_RW·A_W / k_WA·A_W", "W/K", "Uebergang Raum->Wand bzw. Wand->Aussen"],
        ["C_floor", "kWh/K", "Thermische Kapazitaet Estrich"],
        ["C_room", "kWh/K", "Thermische Kapazitaet nur der Raumluft (NEU)"],
        ["C_wand", "kWh/K", "Thermische Kapazitaet der Wandmasse (NEU)"],
        ["h_floor·A = k_BR·A_B", "W/K", "Waermeuebergang Estrich -> Raum"],
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
        ["C_floor", "≈ 5.4 kWh/K", "Estrich-Masse · c (Speicher T_B)"],
        ["C_room", "≈ 0.16 kWh/K", "nur Raumluft (Wand jetzt separat!)"],
        ["C_wand", "≈ 7.5 kWh/K", "Wandmasse 50 Wh/(m²K)·A (Speicher T_W)"],
        ["k_RW : k_WA", "2.5 : 25", "Verhaeltnis; Reihen-U an U_Wand verankert"],
        ["Fenster-Split", "N10/S40/O25/W25 %", "window_orientation_split"],
        ["g-Wert", "0.7", "Gesamtenergiedurchlass Fenster"],
        ["q_int", "5 W/m²", "interne Gewinne (DIN V 4108)"],
        ["h_floor = k_BR", "10 W/(m²·K)", "Boden->Raum Waermeuebergang"],
        ["T_VL,Heiz / T_VL,WW", "35 / 55 °C", "Vorlauf FBH / WW"],
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
        "EMOS Light — 3-Speicher-Gebaeudemodell (ETH Zuerich), Stand Juni 2026",
        styles["Subtitle"],
    ))
    story.append(P(
        "Dieses Dokument beschreibt die thermischen Energiebilanzen, die der MILP-Optimierer "
        "von EMOS Light loest. Das Gebaeude folgt seit Juni 2026 dem 3-Speicher-Ansatz der "
        "Schweizer Studie (ETH Zuerich) mit den drei thermischen Zustaenden <b>Estrich (T_B)</b>, "
        "<b>Raumluft (T_R)</b> und — neu — <b>Aussenwand (T_W)</b>. Hinzu kommen die solaren und "
        "internen Waermegewinne sowie der Warmwasserspeicher; einziger Waermeerzeuger ist die "
        "Waermepumpe.",
        styles,
    ))
    story.append(Spacer(1, 6))
    story.append(P(
        "Drei Korrekturen gegenueber der ETH-Originalformulierung machen das Modell MILP-tauglich "
        "(alle umgesetzt): <b>K1</b> — die Bilinearitaet V_WP·T_RL des Heizwassers entfaellt, die "
        "WP-Waermeleistung Q_WP ist direkte (lineare) Entscheidungsvariable; <b>K2</b> — das "
        "Heizwasser wird quasistationaer eliminiert (Zeitkonstante &lt;&lt; 15 min), es fliesst "
        "direkt in den Estrich (Q_floor,in = Q_WP); <b>K3</b> — Fenster- und Lueftungsverluste "
        "wirken direkt (ohne Traegheit), nur die opake Wand laeuft ueber die traege Masse T_W.",
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

    story.append(H2("2.2 Energiebilanz Estrich (K1/K2: Q_WP direkt)", styles))
    story.append(P(
        "Die WP-Waermeleistung Q_WP fliesst nach den Korrekturen K1/K2 DIREKT in den Estrich "
        "(q_floor,in = Q_WP; das Heizwasser ist quasistationaer eliminiert, keine Bilinearitaet). "
        "Davon abgezogen wird der Waermestrom an den Raum; ein solarer Estrich-Gewinn Q_g,B ist 0. "
        "Estrich und Wand sind traege Knoten (explizites Euler, Zustand bei t-1):",
        styles,
    ))
    story.extend(equation_block(
        "Zustandsuebergang Estrich:",
        r"E_{\mathrm{floor}}(t) = E_{\mathrm{floor}}(t{-}1) + \left(Q_{WP}(t) "
        r"- q_{\mathrm{floor\to room}}(t) + Q_{g,B}\right)\Delta t,\quad Q_{g,B}=0",
        styles,
    ))
    story.extend(equation_block(
        "Newton-Waermeuebergang Boden -> Raum (k_BR = h_floor):",
        r"q_{\mathrm{floor\to room}}(t) \;=\; \frac{k_{BR}\, A_{B}}{1000}\,"
        r"\left(T_{\mathrm{floor}}(t{-}1) - T_{R}(t)\right) \quad [\mathrm{kW}]",
        styles,
    ))
    story.append(P(
        "q_floor_to_room ist eine eigene MILP-Variable und erscheint identisch in Estrich- und "
        "Raumbilanz (energiekonsistent). Der Raum geht mit T_R(t) ein (impliziter Euler fuer den "
        "schnellen Luftknoten, siehe 3.1); der Estrich bleibt explizit bei t-1.",
        styles,
    ))

    story.append(PageBreak())

    # 3. Raum / Wand / Gewinne (3-Speicher-Modell)
    story.append(H1("3 Raumluft-, Wand- und Gewinnbilanz (3-Speicher-Modell)", styles))
    story.append(P(
        "Der Raum ist der zentrale Komfortknoten. Im 3-Speicher-Modell verliert er Waerme auf "
        "zwei Wegen: ueber die TRAEGE Aussenwand (eigener Speicher T_W) und DIREKT — ohne "
        "Traegheit — ueber Fenster, Dach und Lueftung (Korrektur K3). Dazu kommen solare und "
        "interne Gewinne Q_g,R. Die Estrich->Raum-Waerme ist die einzige aktive Zufuhr.",
        styles,
    ))
    story.append(H2("3.1 Energiebilanz Raum (impliziter Euler)", styles))
    story.extend(equation_block(
        "Zustandsuebergang Raumluft:",
        r"C_{\mathrm{room}}\,\frac{T_{R}(t) - T_{R}(t{-}1)}{\Delta t} \;=\;"
        r"q_{\mathrm{floor\to room}}(t) - q_{\mathrm{RW}}(t) - q_{\mathrm{direkt}}(t) + Q_{g,R}(t)",
        styles,
    ))
    story.extend(equation_block(
        "Verlust ueber die traege Aussenwand (Raum -> Wand):",
        r"q_{\mathrm{RW}}(t) \;=\; \frac{k_{RW}\,A_{W}}{1000}\,\left(T_{R}(t) - T_{W}(t{-}1)\right)",
        styles,
    ))
    story.extend(equation_block(
        "Direkter Verlust (Fenster + Dach + Lueftung, ohne Traegheit):",
        r"q_{\mathrm{direkt}}(t) \;=\; \frac{UA_{\mathrm{direkt}}}{1000}\,\left(T_{R}(t) - T_{A}(t)\right)",
        styles,
    ))
    story.append(P(
        "Die Verlust- und Estrich->Raum-Terme greifen auf T_R(t) zu (impliziter Euler). Grund: "
        "C_room ist hier NUR die Raumluft (Wandmasse sitzt im T_W-Knoten), die Zeitkonstante "
        "liegt im Minutenbereich &lt;&lt; 15 min. Explizites Euler wuerde oszillieren; das "
        "implizite Verfahren ist unbedingt stabil und bleibt linear (LP-kompatibel). Die "
        "traegen Knoten Estrich und Wand bleiben explizit (Zustand bei t-1).",
        styles,
    ))

    story.append(H2("3.2 UA-Wert: Aufteilung Wandpfad / direkter Pfad", styles))
    story.append(P(
        "Der gesamte Huellverlust wird auf zwei Pfade aufgeteilt: der TRAEGE Wandpfad laeuft "
        "ueber den Speicher T_W (Abschnitt 3.5), der DIREKTE Pfad UA_direkt buendelt Fenster, "
        "Dach/Bodenplatte und Lueftung (sofort wirksam).",
        styles,
    ))
    story.extend(equation_block(
        "Direkter Verlustleitwert (ohne opake Wand):",
        r"UA_{\mathrm{direkt}} \;=\; U_{\mathrm{Fenster}}A_{\mathrm{Fenster}} + "
        r"U_{\mathrm{Dach}}A_{\mathrm{Grund}} + n_{\mathrm{lueft}}V_{\mathrm{Gebaeude}}",
        styles,
    ))
    story.extend(equation_block(
        "Gesamtverlust = direkter Pfad + Wandpfad (stationaer == U_Wand·A_Wand):",
        r"UA_{\mathrm{ges}} \;=\; UA_{\mathrm{direkt}} + U_{\mathrm{Wand}}A_{\mathrm{Wand}}",
        styles,
    ))

    story.append(H2("3.3 Raumkapazitaet C_room (nur Luft)", styles))
    story.append(P(
        "Im 3-Speicher-Modell enthaelt C_room NUR noch die Raumluft — die Wandmasse ist in "
        "den eigenen Zustand T_W gewandert (Abschnitt 3.5) und darf nicht doppelt gezaehlt "
        "werden; der Estrich (T_B) ist ohnehin ein separater Speicher. C_room ist damit klein, "
        "weshalb der Raum implizit gefuehrt wird (3.1).",
        styles,
    ))
    story.extend(equation_block(
        "Lumped-Capacitance der Raumluft:",
        r"C_{\mathrm{room}} \;=\; \frac{V_{\mathrm{Luft}}\, \rho_{\mathrm{Luft}}\, "
        r"c_{\mathrm{p,Luft}}}{3.6\cdot 10^{6}} \quad [\mathrm{kWh/K}]",
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
    story.append(P(
        "Anmerkung: Im Sommer/bei Hitze kann der Raum ohne aktive Kuehlung ueber den "
        "Komfortpunkt steigen; der Solver darf dann ueberschuessige Waerme ueber einen freien "
        "Lueftungs-Term (Fenster oeffnen) abfuehren, statt infeasibel zu werden.",
        styles,
    ))

    story.append(H2("3.5 Wandbilanz (Speicher T_W, NEU)", styles))
    story.append(P(
        "Die Aussenwand ist der neue traege Speicher zwischen Raum und Aussenluft. Sie nimmt "
        "Waerme vom Raum auf und gibt sie verzoegert nach aussen ab — explizites Euler "
        "(langsamer Knoten). Der Raum->Wand-Fluss ist identisch zu q_RW in der Raumbilanz "
        "(energetisch konsistent).",
        styles,
    ))
    story.extend(equation_block(
        "Zustandsuebergang Wand:",
        r"C_{\mathrm{wand}}\,\frac{T_{W}(t) - T_{W}(t{-}1)}{\Delta t} \;=\; "
        r"\frac{k_{RW}A_{W}}{1000}\!\left(T_{R}(t) - T_{W}(t{-}1)\right) - "
        r"\frac{k_{WA}A_{W}}{1000}\!\left(T_{W}(t{-}1) - T_{A}(t)\right)",
        styles,
    ))
    story.append(P(
        "Verankerung der k-Werte: k_RW (raumseitig) und k_WA (aussenseitig) der Gebaeudegruppe "
        "sind Oberflaechen-Filmkoeffizienten; ihre Reihenschaltung ergaebe roh "
        "U_eff &#8776; 2,27 W/(m²K) (~10x zu leck). Daher wird die Reihen-U an den physikalischen "
        "Wand-U-Wert gekoppelt; das Verhaeltnis k_RW:k_WA = 1:10 bleibt als Aufteilung erhalten. "
        "Der stationaere Gesamtverlust bleibt damit unveraendert (Konsistenz mit UA_ges).",
        styles,
    ))

    story.append(H2("3.6 Solare + interne Gewinne Q_g,R (finale Formel)", styles))
    story.append(P(
        "Die solaren Fenstergewinne werden ueber die vier Fassaden summiert; jede Fassade "
        "erhaelt den direkten Strahl (DNI) ueber ihren Einfallswinkel plus den halben "
        "Diffusanteil (DHI, Sichtfaktor 0,5 zum Himmel). Dazu kommen konstante interne Gewinne "
        "nach DIN V 4108. Der Estrich-Solargewinn Q_g,B ist 0 (mit Prof. Brueckl bestaetigt).",
        styles,
    ))
    story.extend(equation_block(
        "Gesamter solarer + interner Raumgewinn:",
        r"Q_{g,R}(t) = \sum_{i \in \{N,O,S,W\}} g\,A_{F,i}\left(I(t)\cos\theta_i(t) "
        r"+ 0.5\,D(t)\right) + q_{\mathrm{int}}\,A_{\mathrm{Wohn}}",
        styles,
    ))
    story.extend(equation_block(
        "Einfallswinkel je Fassade (vertikales Fenster):",
        r"\cos\theta_i(t) = \max\!\left(0,\; \cos\gamma_S(t)\,\cos\!\left(\alpha_S(t) "
        r"- \alpha_{E,i}\right)\right)",
        styles,
    ))
    story.append(P(
        "g = 0,7 (Gesamtenergiedurchlass), q_int = 5 W/m²; I = Direktstrahlung (DNI), "
        "D = Diffusstrahlung (DHI) aus den Wetterdaten, sonst aus der DISC-Zerlegung der GHI; "
        "gamma_S = Sonnenhoehe, alpha_S = Sonnenazimut, alpha_E,i = Fassadenazimut. Die "
        "Fensterflaeche wird ueber window_orientation_split (Default N10/S40/O25/W25 %) auf "
        "die Fassaden verteilt.",
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
    story.extend(equation_block(
        "Kennfeld-Begrenzung je Modus (Code-Review-Fix):",
        r"q_{\mathrm{floor,in}}(t) \leq P_{\mathrm{th,max}}^{W35}(T_{\mathrm{aus}}),\quad "
        r"q_{\mathrm{ww,in}}(t) \leq P_{\mathrm{th,max}}^{W55}(T_{\mathrm{aus}})",
        styles,
    ))
    story.append(P(
        "Die elektrische Obergrenze wird MODUS-SPEZIFISCH aus dem Kennfeld gesetzt (W35 fuer FBH, "
        "W55 fuer WW). Sonst koennte die hohe FBH-COP mit dem groesseren WW-Leistungs-Cap mehr "
        "FBH-Waerme liefern als das Kennfeld bei W35 physikalisch hergibt. Pro Zeitschritt "
        "bedient die WP genau eine Senke (Entweder-Oder ueber eine Binaervariable — ein "
        "Heizkreis + 3-Wege-Ventil).",
        styles,
    ))
    story.append(P(
        "Steuerung: SG-Ready ist der einzige Schaltkanal (Zustaende sg1..sg4, hp_on = 1 - sg1), "
        "dazu Mindestlauf-/Pausenzeiten. sg3/sg4 sind fuer eine Sollwert-Anhebung der Speicher "
        "vorgesehen (Estrich-Puffer bei sg4 aktiv; die analoge WW-Anhebung ist ein dokumentierter "
        "offener Punkt).",
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
        ["Building", "room", "Q_g,R(t)", "C_room·ΔT/Δt + q_RW + q_direkt"],
        ["Building", "(Wand T_W)", "interne Wandbilanz (kein Senkenknoten)", "—"],
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
