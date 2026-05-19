"""Erzeugt einen ausfuehrlichen mathematischen Bericht zum MILP-Optimierer.

Layout: ReportLab. Formeln: Matplotlib mathtext -> PNG -> Image-Flowable.
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
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
    Table, TableStyle, KeepTogether, ListFlowable, ListItem,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.enums import TA_JUSTIFY


# ----------------------------------------------------------------------
# Equation rendering via matplotlib mathtext
# ----------------------------------------------------------------------

def eq_image(latex: str, fontsize: int = 14, dpi: int = 220) -> Image:
    """Rendert einen LaTeX-Mathstring als PNG und packt ihn in ein Image-Flowable.

    Achtung: matplotlib mathtext, kein volles LaTeX. Subset reicht aber gut.
    """
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.patch.set_alpha(0.0)
    text = fig.text(0, 0, f"${latex}$", fontsize=fontsize, color="black")

    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=dpi,
        bbox_inches="tight", pad_inches=0.05,
        transparent=True,
    )
    plt.close(fig)
    buf.seek(0)

    # Bildgroesse in Punkten (1 inch = 72 pt) berechnen
    from PIL import Image as PILImage
    pil = PILImage.open(buf)
    w_px, h_px = pil.size
    w_pt = w_px * 72.0 / dpi
    h_pt = h_px * 72.0 / dpi

    buf.seek(0)
    img = Image(buf, width=w_pt, height=h_pt)
    img.hAlign = "CENTER"
    return img


# ----------------------------------------------------------------------
# Styles
# ----------------------------------------------------------------------

styles = getSampleStyleSheet()

# Body-Stil mit Blocksatz und etwas mehr Zeilenabstand
styles.add(ParagraphStyle(
    name="BodyDE",
    parent=styles["BodyText"],
    alignment=TA_JUSTIFY,
    fontSize=10.5,
    leading=15,
    spaceAfter=6,
))

styles.add(ParagraphStyle(
    name="H1",
    parent=styles["Heading1"],
    fontSize=18,
    leading=22,
    spaceBefore=14,
    spaceAfter=10,
    textColor=colors.HexColor("#0b3d91"),
))

styles.add(ParagraphStyle(
    name="H2",
    parent=styles["Heading2"],
    fontSize=14,
    leading=18,
    spaceBefore=10,
    spaceAfter=6,
    textColor=colors.HexColor("#143f7a"),
))

styles.add(ParagraphStyle(
    name="H3",
    parent=styles["Heading3"],
    fontSize=12,
    leading=15,
    spaceBefore=8,
    spaceAfter=4,
    textColor=colors.HexColor("#333333"),
))

styles.add(ParagraphStyle(
    name="Caption",
    parent=styles["BodyText"],
    fontSize=9,
    leading=12,
    textColor=colors.HexColor("#555555"),
    alignment=TA_JUSTIFY,
    spaceBefore=2,
    spaceAfter=10,
))

styles.add(ParagraphStyle(
    name="Mono",
    parent=styles["BodyText"],
    fontName="Courier",
    fontSize=9,
    leading=11,
    textColor=colors.HexColor("#222222"),
    spaceAfter=6,
))


def P(text, style="BodyDE"):
    return Paragraph(text, styles[style])


def H1(text):
    return Paragraph(text, styles["H1"])


def H2(text):
    return Paragraph(text, styles["H2"])


def H3(text):
    return Paragraph(text, styles["H3"])


def caption(text):
    return Paragraph(text, styles["Caption"])


def hr():
    t = Table([[" "]], colWidths=[16 * cm], rowHeights=[2])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#888")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


# ----------------------------------------------------------------------
# Page header / footer
# ----------------------------------------------------------------------

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666"))
    # Footer
    canvas.drawString(2 * cm, 1.2 * cm, "EMOS Light — MILP-Optimierer (mathematischer Bericht)")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Seite {doc.page}")
    # Header (ab Seite 2)
    if doc.page > 1:
        canvas.setStrokeColor(colors.HexColor("#bbb"))
        canvas.setLineWidth(0.4)
        canvas.line(2 * cm, A4[1] - 1.6 * cm, A4[0] - 2 * cm, A4[1] - 1.6 * cm)
    canvas.restoreState()


# ----------------------------------------------------------------------
# Content builders
# ----------------------------------------------------------------------

def build_cover():
    return [
        Spacer(1, 4 * cm),
        Paragraph(
            "EMOS Light",
            ParagraphStyle("CovTop", parent=styles["Title"],
                           fontSize=32, leading=38,
                           textColor=colors.HexColor("#0b3d91"),
                           alignment=1),
        ),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Der MILP-Hauptoptimierer",
            ParagraphStyle("CovSub", parent=styles["Title"],
                           fontSize=20, leading=24,
                           textColor=colors.HexColor("#333"), alignment=1),
        ),
        Spacer(1, 0.6 * cm),
        Paragraph(
            "Mathematische Beschreibung von Variablen, Nebenbedingungen "
            "und Zielfunktion",
            ParagraphStyle("CovSub2", parent=styles["BodyText"],
                           fontSize=12, leading=16,
                           textColor=colors.HexColor("#555"), alignment=1),
        ),
        Spacer(1, 6 * cm),
        Paragraph(
            "Projektarbeit EMOS Light",
            ParagraphStyle("CovMeta", parent=styles["BodyText"],
                           fontSize=11, alignment=1,
                           textColor=colors.HexColor("#444")),
        ),
        Paragraph(
            "Implementierungsstand: Mai 2026 (Raumluft als Zustandsvariable)",
            ParagraphStyle("CovMeta2", parent=styles["BodyText"],
                           fontSize=10, alignment=1,
                           textColor=colors.HexColor("#777")),
        ),
        PageBreak(),
    ]


def build_overview():
    out = []
    out.append(H1("1. Uebersicht"))
    out.append(P(
        "Der Hauptoptimierer von EMOS Light ist als <b>gemischt-ganzzahliges "
        "lineares Programm</b> (Mixed-Integer Linear Program, MILP) formuliert. "
        "Er bestimmt fuer einen vorgegebenen Zeithorizont (typischerweise 24 h "
        "Day-Ahead, in 15- oder 60-Minuten-Schritten) die kostenoptimale "
        "Steuerung aller regelbaren Energiekomponenten unter Einhaltung aller "
        "physikalischer und komfortbezogener Nebenbedingungen."
    ))
    out.append(P(
        "Optimiert wird die Summe aus Netzbezugskosten, Einspeiseverguetung "
        "und Batterie-Alterungskosten. Komfortverletzungen werden ueber "
        "Slack-Variablen mit hoher Strafkosten in die Zielfunktion aufgenommen, "
        "sodass Komfort nur dann verletzt wird, wenn das Problem sonst nicht "
        "loesbar waere."
    ))
    out.append(P(
        "Die Komponenten — PV, Batterie, Waermepumpe (mit getrennten COP-Pfaden "
        "fuer Heizung und Warmwasser), Pufferspeicher, Fussbodenheizung mit "
        "Estrich-Speicher, Wallboxen — werden modular eingebunden. Jede "
        "Komponente liefert eine Menge Entscheidungsvariablen und linearer "
        "Nebenbedingungen, die der Optimierer einsammelt und gemeinsam loest."
    ))
    out.append(P(
        "Geloest wird mit dem Open-Source-Solver <b>HiGHS</b> (Branch-and-Cut), "
        "ueber die <i>PuLP</i>-Schnittstelle. Als Fallback steht CBC bereit. "
        "Beide sind frei und benoetigen keine Lizenz."
    ))
    out.append(Spacer(1, 0.3 * cm))

    # Komponententabelle
    data = [
        ["Komponente", "Variablentypen", "Charakter"],
        ["Netz", "kontinuierlich + binaer", "Bezug/Einspeisung getrennt"],
        ["Batterie", "kontinuierlich + 2 binaer", "Lade-/Entladeentkopplung"],
        ["Waermepumpe", "kontinuierlich + 6 binaer", "SG-Ready 1/2/3/4 (einziger Steuerkanal), hp_on, hp_start, max 8 Starts/Tag"],
        ["Estrich (FBH)", "kontinuierlich", "Energie + Q_in + Q Estrich->Raum"],
        ["Gebäude (Raum)", "kontinuierlich", "T_innen-Zustandsvar. + Komfortband-Slacks (seit Mai 2026)"],
        ["Pufferspeicher (WW)", "kontinuierlich + 1 binaer", "Zwei-Zonen-Verlustmodell + Legionellen-Tag"],
        ["Wallbox", "kontinuierlich + 1 binaer", "EV-SOC-Zustandsvar., Ziel-SOC zur Abfahrt, 5%/h Verbrauch waehrend Abwesenheit"],
    ]
    t = Table(data, colWidths=[4.0 * cm, 5.5 * cm, 6.0 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3d91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaaaaa")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f1f4fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    out.append(t)
    out.append(caption(
        "Tabelle 1: Variablentypen pro Komponente. Binaervariablen entstehen "
        "ueberall dort, wo physikalische oder logische Entweder-Oder-"
        "Entscheidungen formuliert sind (Laden ODER Entladen, EIN ODER AUS, etc.)."
    ))
    out.append(Spacer(1, 0.4 * cm))
    out.append(PageBreak())
    return out


def build_notation():
    out = []
    out.append(H1("2. Notation und Indexmengen"))
    out.append(P(
        "Der Planungshorizont ist diskretisiert in Zeitschritte gleicher "
        "Laenge. Bezeichnet sei:"
    ))
    out.append(eq_image(
        r"\mathcal{T} = \{0, 1, 2, \ldots, N{-}1\},"
        r"\quad \Delta t = \frac{\text{step\_minutes}}{60}\ \text{[h]}"
    ))
    out.append(P(
        "wobei N die Anzahl der Zeitschritte ist und Δt die Schrittweite in "
        "Stunden. Typisch: 24 h Horizont, 15-min-Aufloesung → N = 96."
    ))

    out.append(H2("Eingangs- und Parameterzeitreihen"))
    inputs = [
        (r"\pi_t \ \text{[ct/kWh]}", "dynamischer Strompreis (Day-Ahead + Tarif)"),
        (r"\pi^{\text{feed}}\ \text{[ct/kWh]}", "Einspeiseverguetung (i. d. R. konstant)"),
        (r"P^{\text{PV}}_t\ \text{[kW]}", "PV-Erzeugungsprognose"),
        (r"P^{\text{Last}}_t\ \text{[kW]}", "Haushaltslastprofil (nicht regelbar)"),
        (r"\dot{Q}^{\text{WW,Bedarf}}_t\ \text{[kW]}", "Warmwasserbedarf"),
        (r"T^{\text{aussen}}_t\ \text{[}^\circ\text{C]}", "Aussentemperatur (geht in COP ein)"),
        (r"\bar{P}^{\text{Netz}}\ \text{[kW]}", "Netzanschlussleistung (oberes Limit)"),
    ]
    for sym, desc in inputs:
        row = Table([[eq_image(sym, fontsize=12), Paragraph(desc, styles["BodyDE"])]],
                    colWidths=[5 * cm, 11 * cm])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        out.append(row)
    out.append(Spacer(1, 0.3 * cm))

    out.append(H2("Konvention"))
    out.append(P(
        "Alle Leistungen sind in kW, alle Energien in kWh, alle Preise in ct. "
        "Das gewaehlte Schrittweiten-Δt sorgt fuer die Energie-Leistung-"
        "Konsistenz: Energie = Leistung · Δt."
    ))
    out.append(PageBreak())
    return out


def build_grid_balance():
    out = []
    out.append(H1("3. Netzanschluss und elektrische Energiebilanz"))
    out.append(H2("3.1 Netzvariablen"))
    out.append(P("Pro Zeitschritt t werden definiert:"))
    out.append(eq_image(
        r"P^{\text{buy}}_t \in [0,\bar{P}^{\text{Netz}}], "
        r"\quad P^{\text{sell}}_t \in [0,\bar{P}^{\text{Netz}}], "
        r"\quad y^{\text{buy}}_t \in \{0,1\}"
    ))
    out.append(P(
        "Die binaere Variable y<sup>buy</sup><sub>t</sub> erzwingt, dass "
        "<b>nicht gleichzeitig bezogen und eingespeist</b> wird:"
    ))
    out.append(eq_image(
        r"P^{\text{buy}}_t \leq \bar{P}^{\text{Netz}} \cdot y^{\text{buy}}_t, "
        r"\quad\quad P^{\text{sell}}_t \leq \bar{P}^{\text{Netz}} \cdot (1 - y^{\text{buy}}_t)"
    ))
    out.append(P(
        "Ohne diese Kopplung koennte der Solver bei Roundtrip-Verlusten der "
        "Batterie scheinbar 'kostenlos Energie schoepfen', indem er Strom "
        "kauft und gleichzeitig verkauft. Die Disjunktion ist physikalisch "
        "korrekt (gleicher Zaehler in beide Richtungen) und wird hier explizit "
        "erzwungen."
    ))
    out.append(P(
        "Zusaetzlich darf nur PV eingespeist werden — kein Verkauf aus Batterie "
        "oder Netzbezug:"
    ))
    out.append(eq_image(r"P^{\text{sell}}_t \leq P^{\text{PV}}_t"))

    out.append(H2("3.2 Elektrische Knotenbilanz"))
    out.append(P(
        "Fuer jeden Zeitschritt muss Erzeugung gleich Verbrauch sein "
        "(Kirchhoff 1. fuer den AC-Knoten):"
    ))
    out.append(eq_image(
        r"P^{\text{PV}}_t + P^{\text{buy}}_t + P^{\text{batt,dis}}_t"
        r"\;=\;"
        r"P^{\text{Last}}_t + P^{\text{sell}}_t + P^{\text{batt,ch}}_t"
        r"+ P^{\text{HP}}_t + \sum_w P^{\text{WB},w}_t"
    ))
    out.append(P(
        "Diese Gleichung ist die <b>zentrale Kopplung</b> aller Komponenten. "
        "Sie zwingt PV-Ueberschuss entweder in die Batterie, in die Wallbox, "
        "in die Waermepumpe (Sektorenkopplung) oder in die Einspeisung — "
        "und Defizite entweder aus Batterie oder aus dem Netz."
    ))

    out.append(H2("3.3 §14a EnWG — netzdienliche Drosselung"))
    out.append(P(
        "Optional kann der Verteilnetzbetreiber steuerbare Verbrauchseinrichtungen "
        "drosseln. Fuer eine vom Nutzer angegebene Teilmenge "
        "𝒯<sub>14a</sub> ⊂ 𝒯 von Zeitschritten gilt dann eine "
        "Leistungsobergrenze:"
    ))
    out.append(eq_image(
        r"P^{\text{HP}}_t + \sum_w P^{\text{WB},w}_t "
        r"\leq \bar{P}^{14a}, \quad\quad \forall t \in \mathcal{T}_{14a}"
    ))
    out.append(P(
        "Andere Verbraucher (Haushalt, PV-Einspeisung) sind nicht betroffen. "
        "<i>Hinweis:</i> die Auswahl der gedrosselten Stunden ist exogen — "
        "der Optimierer entscheidet nicht ueber die Drosselung selbst, sondern "
        "passt sich an."
    ))
    out.append(PageBreak())
    return out


def build_battery():
    out = []
    out.append(H1("4. Batteriespeicher"))
    out.append(P(
        "Die Batterie ist als energieneutraler Speicher mit getrennten Lade- "
        "und Entladevariablen, ladestandsabhaengiger Bilanzgleichung und "
        "Roundtrip-Wirkungsgrad modelliert."
    ))

    out.append(H2("4.1 Variablen"))
    out.append(eq_image(
        r"P^{\text{batt,ch}}_t \in [0,\bar{P}^{\text{ch}}], \quad"
        r"P^{\text{batt,dis}}_t \in [0,\bar{P}^{\text{dis}}], \quad"
        r"E^{\text{batt}}_t \in [E^{\min}, E^{\max}]"
    ))
    out.append(eq_image(
        r"y^{\text{ch}}_t,\ y^{\text{dis}}_t \in \{0,1\}"
    ))
    out.append(P(
        "Die Bounds des Energiezustands ergeben sich aus dem zulaessigen "
        "SOC-Fenster:"
    ))
    out.append(eq_image(
        r"E^{\min} = \text{SOC}_{\min} \cdot E^{\text{kap}}, \quad"
        r"E^{\max} = \text{SOC}_{\max} \cdot E^{\text{kap}}"
    ))

    out.append(H2("4.2 Logische Kopplung — kein gleichzeitiges Laden/Entladen"))
    out.append(P(
        "Wie beim Netz koennte der Solver sonst Verluste 'wegwirtschaften'. "
        "Mit Big-M-aehnlicher Kopplung (M = max. Leistung):"
    ))
    out.append(eq_image(
        r"y^{\text{ch}}_t + y^{\text{dis}}_t \leq 1"
    ))
    out.append(eq_image(
        r"P^{\text{batt,ch}}_t \leq \bar{P}^{\text{ch}} \cdot y^{\text{ch}}_t, \quad"
        r"P^{\text{batt,dis}}_t \leq \bar{P}^{\text{dis}} \cdot y^{\text{dis}}_t"
    ))

    out.append(H2("4.3 SOC-Bilanzgleichung"))
    out.append(P(
        "Die gespeicherte Energie entwickelt sich gemaess Lade- und Entlade-"
        "Wirkungsgrad. <b>Verluste werden auf der DC-Seite verbucht</b>, "
        "d. h. eine eingespeiste kWh AC erhoeht den SOC nur um η<sub>ch</sub>·kWh, "
        "und um eine kWh entnehmen zu koennen muss intern 1/η<sub>dis</sub> kWh "
        "entladen werden:"
    ))
    out.append(eq_image(
        r"E^{\text{batt}}_t = E^{\text{batt}}_{t-1} + "
        r"\eta_{\text{ch}}\, P^{\text{batt,ch}}_t\, \Delta t - "
        r"\frac{1}{\eta_{\text{dis}}}\, P^{\text{batt,dis}}_t\, \Delta t"
    ))
    out.append(P(
        "Anfangsbedingung E<sub>0</sub><sup>batt</sup> = SOC<sub>init</sub> · "
        "E<sup>kap</sup>. Es wird keine Endbedingung erzwungen — die Batterie "
        "darf am Horizontende leer sein, falls das oekonomisch sinnvoll ist."
    ))

    out.append(H2("4.4 Zyklische Alterungskosten"))
    out.append(P(
        "Damit der Optimierer nicht 'Cycling-Sucht' entwickelt (jede 0,1-ct-"
        "Preisdifferenz ausnutzt), werden Alterungskosten in die Zielfunktion "
        "aufgenommen. Der spezifische Alterungspreis pro durchgesetzte kWh "
        "ergibt sich aus Wiederbeschaffungskosten, Restwert, garantierter "
        "Zyklenzahl und Roundtrip-Wirkungsgrad:"
    ))
    out.append(eq_image(
        r"c^{\text{age}} = \frac{C^{\text{Ersatz}} - R^{\text{EOL}}}"
        r"{N_{\text{EFC}} \cdot E^{\text{nutzbar}} \cdot \eta_{\text{rt}}}"
        r"\quad [\text{ct/kWh}]"
    ))
    out.append(P(
        "Da ein Aequivalent-Vollzyklus = 1× laden + 1× entladen ist, wird der "
        "Term in der Zielfunktion <b>halbiert</b> auf charge und discharge verteilt:"
    ))
    out.append(eq_image(
        r"K^{\text{age}} = \frac{c^{\text{age}}}{2} \sum_{t \in \mathcal{T}}"
        r"( P^{\text{batt,ch}}_t + P^{\text{batt,dis}}_t ) \Delta t"
    ))
    out.append(P(
        "Wirtschaftlich heisst das: Ein Lade-Entlade-Zyklus muss eine "
        "Preisdifferenz von mindestens c<sup>age</sup>/η<sub>rt</sub> "
        "ueberschreiten, um sich zu lohnen."
    ))
    out.append(PageBreak())
    return out


def build_heatpump():
    out = []
    out.append(H1("5. Waermepumpe"))
    out.append(P(
        "Die Waermepumpe wandelt elektrische in thermische Leistung um. "
        "Modelliert ist eine Vaillant aroTHERM plus VWL 105/8.1 A mit "
        "real vermessenem 2D-Kennfeld nach EN 14511."
    ))

    out.append(H2("5.1 Variablen"))
    out.append(eq_image(
        r"P^{\text{HP}}_t \in [0, \bar{P}^{\text{HP}}], \quad"
        r"y^{\text{HP}}_t \in \{0,1\}, \quad"
        r"y^{\text{HP,start}}_t \in \{0,1\}"
    ))
    out.append(P(
        "SG-Ready ist seit Mai 2026 der <b>einzige</b> Steuerkanal der WP "
        "(BWP v1.1, vier Zustaende). Pro Schritt ist genau ein Zustand "
        "aktiv, y<sup>HP</sup> ist davon abgeleitet:"
    ))
    out.append(eq_image(
        r"y^{\text{SG1}}_t,\ y^{\text{SG2}}_t,\ y^{\text{SG3}}_t,\ y^{\text{SG4}}_t \in \{0,1\}"
    ))
    out.append(P(
        "Zustand 1 = Zwangsabschaltung (EVU-Sperre, WP zwingend AUS), "
        "Zustand 2 = Normalbetrieb, "
        "Zustand 3 = Einschaltempfehlung (WW-Sollwert um sg3-Offset angehoben), "
        "Zustand 4 = Zwangseinschaltung (WW + Estrich-Pufferspeicher angehoben). "
        "Die Einschalt-Variable y<sup>HP,start</sup> markiert OFF&#8594;ON-Vorgaenge "
        "und wird vom Tageslimit (siehe 5.5) beschraenkt."
    ))

    out.append(H2("5.2 Modulationsbereich"))
    out.append(P(
        "Wenn die WP an ist, gilt die untere Modulationsgrenze; ist sie aus, "
        "ist die Leistung null:"
    ))
    out.append(eq_image(
        r"P^{\text{HP,min}} \cdot y^{\text{HP}}_t \leq P^{\text{HP}}_t "
        r"\leq \bar{P}^{\text{HP}} \cdot y^{\text{HP}}_t"
    ))

    out.append(H2("5.3 COP — vorberechnete Zeitreihe"))
    out.append(P(
        "Der COP haengt von Aussen- und Vorlauftemperatur ab. Da die Vorlauftemperatur "
        "fest pro Pfad konfiguriert ist (Heizkreis ~35&nbsp;°C, WW ~55&nbsp;°C), "
        "kann der COP <b>vor der Optimierung</b> als Zeitreihe berechnet werden — "
        "via bilinearer 2D-Interpolation aus dem Kennfeld:"
    ))
    out.append(eq_image(
        r"\text{COP}^{\text{heiz}}_t = f_{\text{interp}}(T^{\text{aussen}}_t,\ T^{\text{VL,heiz}}), \quad"
        r"\text{COP}^{\text{ww}}_t  = f_{\text{interp}}(T^{\text{aussen}}_t,\ T^{\text{VL,ww}})"
    ))
    out.append(P(
        "Damit bleibt die Beziehung zwischen elektrischer und thermischer "
        "Leistung in der Optimierung <b>linear</b>. Wuerde der COP von "
        "Entscheidungsvariablen abhaengen, ergaebe sich ein bilineares (nicht-"
        "lineares) Problem — viel teurer zu loesen."
    ))
    out.append(P(
        "Stuetzstellen des Kennfeldes (Vaillant aroTHERM plus, EN 14511):"
    ))
    cop_data = [
        ["T_aussen \\ T_VL", "W35", "W45", "W55", "W65"],
        ["A−7 °C", "3.01", "2.28", "2.03", "1.74"],
        ["A2 °C",  "4.40", "3.37", "2.76", "2.26"],
        ["A7 °C",  "5.29", "4.03", "3.19", "2.51"],
    ]
    t = Table(cop_data, colWidths=[3.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#143f7a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f1f4fb")),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaa")),
    ]))
    out.append(t)
    out.append(caption(
        "Tabelle 2: COP-Kennfeld der modellierten Waermepumpe. Werte werden "
        "in der Optimierung mit Aussentemperatur-Zeitreihe bilinear interpoliert "
        "und als Konstanten in den Constraints verwendet."
    ))

    out.append(H2("5.4 Thermische Leistungsaufteilung WP → FBH und WW"))
    out.append(P(
        "Wenn beide thermischen Senken aktiv sind, wird die elektrische "
        "WP-Leistung auf zwei Teilstroeme aufgeteilt — jeder mit dem zu "
        "seiner Vorlauftemperatur passenden COP:"
    ))
    out.append(eq_image(
        r"P^{\text{HP}}_t = P^{\text{HP,Floor}}_t + P^{\text{HP,WW}}_t"
    ))
    out.append(eq_image(
        r"\dot{Q}^{\text{Floor,in}}_t = \text{COP}^{\text{heiz}}_t \cdot P^{\text{HP,Floor}}_t"
    ))
    out.append(eq_image(
        r"\dot{Q}^{\text{WW,in}}_t = \text{COP}^{\text{ww}}_t \cdot P^{\text{HP,WW}}_t"
    ))
    out.append(P(
        "Diese Trennung erlaubt es dem Optimierer, in einer kalten Stunde "
        "die WP gezielt auf den hocheffizienten Pfad (Heizkreis @ W35, COP ≈ 4) "
        "zu lenken, wenn dort Speicherplatz ist — und teures Nachladen des "
        "WW-Speichers (COP ≈ 2,8) auf waermere Stunden zu legen."
    ))

    out.append(H2("5.5 Mindestlauf- und Mindestpausenzeiten und Cycling-Limit"))
    out.append(P(
        "Hardwareschutz: ein Verdichter darf nicht beliebig oft starten. "
        "Mit n<sub>run</sub> = ⌈t<sub>min,run</sub>/Δt<sub>min</sub>⌉ "
        "Schritten Mindestlaufzeit gilt fuer alle Folgeschritte k = 1, …, "
        "n<sub>run</sub>−1:"
    ))
    out.append(eq_image(
        r"y^{\text{HP}}_t - y^{\text{HP}}_{t-1} \leq y^{\text{HP}}_{t+k}"
    ))
    out.append(P(
        "Anschaulich: Wenn die WP gerade eingeschaltet wurde "
        "(y<sub>t</sub> = 1, y<sub>t−1</sub> = 0, linke Seite = 1), "
        "muss y<sub>t+k</sub> = 1 sein — sie bleibt also fuer mindestens "
        "n<sub>run</sub> Schritte an."
    ))
    out.append(P("Analog fuer die Mindestpause:"))
    out.append(eq_image(
        r"y^{\text{HP}}_{t-1} - y^{\text{HP}}_t \leq 1 - y^{\text{HP}}_{t+k}"
    ))

    out.append(P(
        "<b>Tageslimit der Einschaltvorgaenge</b> (Mai 2026, "
        "<font face='Courier'>max_starts_per_day</font>, Default 8): "
        "Jedes OFF→ON belastet den Verdichter. Umschalten zwischen "
        "Heizkreis und WW <i>zaehlt nicht</i>, weil y<sup>HP</sup> dabei "
        "an bleibt. Linking-Constraint + Tagessumme:"
    ))
    out.append(eq_image(
        r"y^{\text{HP,start}}_t \geq y^{\text{HP}}_t - y^{\text{HP}}_{t-1}, \quad"
        r"\sum_{t \in d} y^{\text{HP,start}}_t \leq N^{\text{max,start}}"
    ))
    out.append(P(
        "Tagesgruppierung kommt aus den Zeitstempeln; bei t=0 wird "
        "y<sup>HP</sup><sub>−1</sub> = 0 angenommen (im MPC-Folgewindow "
        "ueberzaehlt das maximal um +1 pro Window-Wechsel). "
        "<font face='Courier'>max_starts_per_day = 0</font> deaktiviert die "
        "Restriktion."
    ))

    out.append(H2("5.6 SG-Ready (BWP v1.1) als einziger Steuerkanal"))
    out.append(P(
        "Seit Mai 2026 ist SG-Ready nicht mehr ein optionaler Boost-Hebel "
        "<i>neben</i> einem freien y<sup>HP</sup>-Entscheid des Solvers, "
        "sondern die <b>einzige</b> Schaltlogik der WP. Zwei kompakte "
        "Constraints decken alle vier Zustaende ab:"
    ))
    out.append(P(
        "<b>(a) Genau ein Zustand pro Schritt:</b>"
    ))
    out.append(eq_image(
        r"y^{\text{SG1}}_t + y^{\text{SG2}}_t + y^{\text{SG3}}_t + y^{\text{SG4}}_t = 1"
    ))
    out.append(P(
        "<b>(b) WP nur per SG1 abschaltbar — y<sup>HP</sup> direkt aus SG1 abgeleitet:</b>"
    ))
    out.append(eq_image(
        r"y^{\text{HP}}_t + y^{\text{SG1}}_t = 1"
    ))
    out.append(P(
        "Daraus folgt automatisch: SG1=1 erzwingt y<sup>HP</sup>=0 "
        "(Zwangsabschaltung), und SG2/SG3/SG4=1 erzwingen y<sup>HP</sup>=1. "
        "Die alten Einzelconstraints (SG-Exklusivitaet, SG1-Leistungslimit, "
        "SG3-needs-on) sind in diesem Schema implizit enthalten und entfallen."
    ))
    out.append(P(
        "<b>Speicherwirkung der Zustaende 3 und 4:</b>"
    ))
    out.append(eq_image(
        r"E^{\text{WW,max}}_t = C^{\text{WW}} \cdot (T^{\text{WW,max}} "
        r"+ \Delta T^{\text{SG3}} \cdot y^{\text{SG3}}_t + \Delta T^{\text{SG4}} \cdot y^{\text{SG4}}_t)"
    ))
    out.append(eq_image(
        r"E^{\text{Floor,max}}_t = C^{\text{Floor}} \cdot (T^{\text{Floor,max}} "
        r"+ \Delta T^{\text{SG4}} \cdot y^{\text{SG4}}_t)"
    ))
    out.append(P(
        "SG3 (Einschaltempfehlung) hebt nur den WW-Sollwert "
        "(<font face='Courier'>sg_temp_raise_state3_c</font>, Default 5 K). "
        "SG4 (Zwangseinschaltung) hebt zusaetzlich auch die Estrich-Komfort-"
        "Obergrenze "
        "(<font face='Courier'>sg_temp_raise_state4_c</font>, Default 10 K). "
        "Damit kann der Solver in Niedrigpreisstunden gezielt 'mehr "
        "speichern' — physikalisch genau das, was die SG-Ready-Norm "
        "BWP v1.1 vom EVU vorsieht."
    ))
    out.append(P(
        "Zusaetzlich gilt eine Mindesthaltezeit fuer SG3 und SG4 nach demselben "
        "Schema wie die Mindestlaufzeit der WP."
    ))
    out.append(PageBreak())
    return out


def build_thermal_storages():
    out = []
    out.append(H1("6. Thermische Speicher"))

    out.append(H2("6.1 Estrich der Fussbodenheizung"))
    out.append(P(
        "Der Betonestrich der Fussbodenheizung ist der einzige thermische "
        "Speicher fuer die Raumheizung — kein separater Pufferspeicher."
    ))
    out.append(P(
        "<b>Kapazitaet</b> aus Masse, spezifischer Waerme und nutzbarem "
        "Komfortband:"
    ))
    out.append(eq_image(
        r"C^{\text{Estrich}} = \frac{A_{\text{beheizt}} \cdot d \cdot \rho \cdot c_p}"
        r"{3{,}6 \cdot 10^6}\ \ \left[\frac{\text{kWh}}{\text{K}}\right]"
    ))
    out.append(eq_image(
        r"E^{\text{Floor,kap}} = C^{\text{Estrich}}_\Sigma \cdot "
        r"(T^{\text{Floor,max}} - T^{\text{Floor,min}})"
    ))
    out.append(P(
        "Bei 150 m² Wohnflaeche, 65 mm Estrich, 2000 kg/m³, "
        "c<sub>p</sub> = 1000 J/(kg·K) und 6 K Komfortband (20–26 °C) ergeben "
        "sich rund 32 kWh nutzbarer Speicher. Optional kann die Gebaeudemasse "
        "(Wand, Luft) ueber einen Zusatzterm in C<sup>Estrich</sup><sub>Σ</sub> "
        "addiert werden (Lumped-Capacitance)."
    ))
    out.append(P("<b>Variablen:</b>"))
    out.append(eq_image(
        r"E^{\text{Floor}}_t \in [0, E^{\text{Floor,kap}}], \quad"
        r"\dot{Q}^{\text{Floor,in}}_t \in [0, \dot{Q}^{\text{Floor,max}}], \quad"
        r"\dot{Q}^{\text{Floor}\to\text{Raum}}_t \geq 0"
    ))
    out.append(P(
        "<b>Energiebilanz mit aktivem Gebäude (Mai 2026):</b> Der Wärme"
        "strom Estrich → Raum ist eine separate MILP-Variable, die gleich"
        "zeitig die Raumluftbilanz (§6.3) speist:"
    ))
    out.append(eq_image(
        r"E^{\text{Floor}}_t = E^{\text{Floor}}_{t-1} + "
        r"(\dot{Q}^{\text{Floor,in}}_t - \dot{Q}^{\text{Floor}\to\text{Raum}}_t) \cdot \Delta t"
    ))
    out.append(eq_image(
        r"\dot{Q}^{\text{Floor}\to\text{Raum}}_t = "
        r"\frac{h_{\text{oberfl}} \cdot A}{1000} \cdot "
        r"(T^{\text{Floor}}_{t-1} - T^{\text{innen}}_{t-1})"
    ))
    out.append(P(
        "Die Kopplung ist affin in den Variablen (Vorzeitschritt-Werte) "
        "und bleibt damit MILP-konform. <b>Fallback ohne Gebäude:</b> "
        "Wenn die Building-Komponente nicht aktiv ist, fällt das Modell "
        "auf die alte Verlustraten-Bilanz "
        r"E_t = E_{t-1} + Q_{\text{in}} \Delta t - \lambda E_{t-1} \Delta t "
        "zurück, mit λ = h·A/(C<sub>Σ</sub>·1000). In diesem Modus IST "
        "die Selbstentladung die (implizite) Raumheizung — beide Modelle "
        "sind physikalisch äquivalent, nur explizit vs. implizit."
    ))

    out.append(H2("6.2 Raumluftbilanz (seit Mai 2026)"))
    out.append(P(
        "Mit aktiver Building-Komponente ist die Raumlufttemperatur "
        "<b>T<sub>innen</sub></b> eine eigene MILP-Zustandsvariable. "
        "Das Modell wird explizit zweistufig: Estrich (§6.1) speichert, "
        "Raum verliert über die Hülle. Damit lässt sich die Optimierung "
        "auch im Winter ohne implizite λ-Approximation rechnen."
    ))
    out.append(P("<b>Variablen:</b>"))
    out.append(eq_image(
        r"T^{\text{innen}}_t \in [T^{\min}_{\text{komf}}-10,\ T^{\max}_{\text{komf}}+10], \quad"
        r"s^{\text{low}}_t,\ s^{\text{high}}_t \geq 0"
    ))
    out.append(P("<b>Energiebilanz</b> (explizites Euler, affin in den Variablen):"))
    out.append(eq_image(
        r"C^{\text{room}} \cdot (T^{\text{innen}}_t - T^{\text{innen}}_{t-1}) = "
        r"(\dot{Q}^{\text{Floor}\to\text{Raum}}_t - \dot{Q}^{\text{Verlust}}_t) \cdot \Delta t"
    ))
    out.append(eq_image(
        r"\dot{Q}^{\text{Verlust}}_t = \frac{UA}{1000} \cdot "
        r"(T^{\text{innen}}_{t-1} - T^{\text{aussen}}_t)"
    ))
    out.append(P(
        "Die transmissions- und lüftungsbedingte UA-Konstante kommt aus "
        "den Gebäude-Geometrie- und U-Wert-Eingaben (Gebäudegruppe-PDF "
        "Mai 2026). Auch hier sorgt die Auswertung am Vorzeitschritt "
        "dafür, dass die rechte Seite linear in T<sub>innen,t-1</sub> "
        "bleibt — kein Bilinear-Term."
    ))
    out.append(P("<b>Komfortband als Soft-Constraint:</b>"))
    out.append(eq_image(
        r"T^{\text{innen}}_t + s^{\text{low}}_t \geq T^{\min}_{\text{komf}}, \quad"
        r"T^{\text{innen}}_t - s^{\text{high}}_t \leq T^{\max}_{\text{komf}}"
    ))
    out.append(P(
        "Default-Komfortband 21–24 °C (konfigurierbar). Die Slack-"
        "Variablen werden in der Zielfunktion mit "
        "<b>500 ct/kWh</b> bestraft (UNMET_HEAT_PENALTY_CT, Abschnitt 8.2) "
        "— weit über jedem realen Strompreis, sodass das Komfortband nur "
        "verletzt wird, wenn das Problem sonst infeasible wäre."
    ))

    out.append(H2("6.3 Warmwasser-Pufferspeicher (Zwei-Zonen-Modell)"))
    out.append(P(
        "Der Speicher wird als ideal geschichtet modelliert: heisse Zone "
        "oben (T<sub>max</sub>), kalte Zone unten (T<sub>min</sub>). Die "
        "Thermokline wandert mit Lade- und Entnahmevorgaengen."
    ))
    out.append(P("<b>Variablen:</b>"))
    out.append(eq_image(
        r"E^{\text{WW}}_t \in [0, E^{\text{WW,kap}}], \quad"
        r"\dot{Q}^{\text{WW,in}}_t \geq 0, \quad"
        r"\dot{Q}^{\text{WW,bedarf}}_t \geq 0"
    ))
    out.append(P("<b>Kapazitaet:</b>"))
    out.append(eq_image(
        r"E^{\text{WW,kap}} = \frac{V \cdot c_{p,W} \cdot (T_{\max} - T_{\min})}"
        r"{1000}\ \ [\text{kWh}], \quad c_{p,W} = 1{,}163\ \frac{\text{Wh}}{\text{L\,K}}"
    ))
    out.append(P(
        "<b>Energiebilanz</b> mit fixen und SOC-proportionalen Verlusten:"
    ))
    out.append(eq_image(
        r"E^{\text{WW}}_t = E^{\text{WW}}_{t-1} + "
        r"(\dot{Q}^{\text{WW,in}}_t - \dot{Q}^{\text{WW,bedarf}}_t)\Delta t"
        r" - \dot{Q}^{\text{fix}} \Delta t"
        r" - \mu^{\text{rel}} \cdot E^{\text{WW}}_{t-1} \cdot \Delta t"
    ))
    out.append(P("Die Verlustparameter ergeben sich aus der Geometrie:"))
    out.append(eq_image(
        r"\dot{Q}^{\text{fix}} = U \cdot [A_{\text{Deckel}}(T_{\max}-T_{\text{amb}})"
        r"+ (A_{\text{Boden}}+A_{\text{Mantel}})(T_{\min}-T_{\text{amb}})]"
    ))
    out.append(eq_image(
        r"\mu^{\text{rel}} = \frac{U \cdot A_{\text{Mantel}} \cdot (T_{\max}-T_{\min})}"
        r"{E^{\text{WW,kap}}}"
    ))
    out.append(P(
        "Anschauung: Deckel ist immer heiss → konstanter Verlust. Boden und "
        "Mantel sind im 'leeren' Zustand kalt → Grundverlust gegen Umgebung. "
        "Beim Aufladen waechst die heisse Zone und damit die heisse "
        "Mantelflaeche → zusaetzliche, fuellstandsproportionale Verluste. "
        "Linear → MILP-kompatibel."
    ))

    out.append(H2("6.4 Bedarfsdeckung Warmwasser"))
    out.append(P(
        "Der Brauchwasserbedarf wird ueber die Frischwasserstation aus dem "
        "Pufferspeicher gedeckt. Mit dem evtl. zusaetzlichen Nachheizfaktor "
        "ϕ<sup>FWS</sup> der Frischwasserstation ergibt sich:"
    ))
    out.append(eq_image(
        r"\dot{Q}^{\text{WW,bedarf}}_t + s^{\text{WW}}_t = "
        r"\phi^{\text{FWS}} \cdot \dot{Q}^{\text{Brauchwasser}}_t"
    ))
    out.append(P(
        "Dabei ist s<sup>WW</sup><sub>t</sub> ≥ 0 eine Slack-Variable, die "
        "in der Zielfunktion mit hoher Strafkosten belegt ist (siehe Abschnitt 9). "
        "Damit bleibt das Modell auch bei extremen Bedarfsspitzen loesbar — "
        "der Solver darf 'Komfort verletzen', wird das aber nur als letztes "
        "Mittel tun."
    ))

    out.append(H2("6.5 Komfort-Mindestenergie"))
    out.append(P(
        "Optional kann der Nutzer Komfort-Perioden definieren (z. B. Duschen "
        "morgens 6–8 Uhr und abends 19–22 Uhr), in denen eine erhoehte "
        "Mindestenergie gilt:"
    ))
    out.append(eq_image(
        r"E^{\text{WW}}_t \geq E^{\min}_t,"
        r"\quad\text{mit }\ E^{\min}_t = E^{\text{WW}}(T^{\text{Komfort}})"
        r"\ \text{in Komfortperioden, sonst}\ E^{\text{WW}}(T^{\min})"
    ))

    out.append(H2("6.6 SG-Ready dynamische Obergrenzen (Zustaende 3 und 4)"))
    out.append(P(
        "Bei SG-Ready-Zustand 3 (Einschaltempfehlung) wird die WW-Obergrenze "
        "angehoben; bei Zustand 4 (Zwangseinschaltung) zusaetzlich auch die "
        "Estrich-Pufferspeicher-Obergrenze (BWP v1.1, Mai 2026):"
    ))
    out.append(eq_image(
        r"\Delta E^{\text{SG3}} = \frac{V \cdot c_{p,W} \cdot \Delta T^{\text{SG3}}}{1000}, \quad"
        r"\Delta E^{\text{SG4}}_{\text{WW}} = \frac{V \cdot c_{p,W} \cdot \Delta T^{\text{SG4}}}{1000}"
    ))
    out.append(eq_image(
        r"E^{\text{WW}}_t \leq E^{\text{WW,kap}} + \Delta E^{\text{SG3}} \cdot y^{\text{SG3}}_t + \Delta E^{\text{SG4}}_{\text{WW}} \cdot y^{\text{SG4}}_t"
    ))
    out.append(eq_image(
        r"E^{\text{Floor}}_t \leq E^{\text{Floor,kap}} + C^{\text{Floor}} \cdot \Delta T^{\text{SG4}} \cdot y^{\text{SG4}}_t"
    ))
    out.append(P(
        "Damit kann der Optimierer bei billigem Strom oder PV-Ueberschuss "
        "gezielt 'Energie-Vorrat' anlegen — physikalisch genau das Verhalten, "
        "das die SG-Ready-Norm vom EVU einfordert."
    ))
    out.append(PageBreak())
    return out


def build_wallbox():
    out = []
    out.append(H1("7. Wallbox und E-Fahrzeug"))
    out.append(P(
        "Pro Wallbox w wird modelliert: variable Ladeleistung, EV-SOC als "
        "Zustandsvariable, Anwesenheitsfenster, Ziel-SOC zur Abfahrt und "
        "Fahrverbrauch waehrend Abwesenheit (Mai 2026)."
    ))

    out.append(H2("7.1 Variablen"))
    out.append(eq_image(
        r"P^{\text{WB},w}_t \in [0, \bar{P}^{\text{WB},w}], \quad"
        r"y^{\text{WB},w}_t \in \{0,1\}, \quad"
        r"\text{SOC}^{\text{EV},w}_t \in [0,\ \text{SOC}^{\max} \cdot E^{\text{EV,kap}}]"
    ))
    out.append(P(
        "Die explizite SOC-Zustandsvariable ist neu seit Mai 2026 und loest "
        "die alte 'min_energy ueber Horizont'-Logik ab — damit kann das "
        "Ziel-SOC-Constraint exakt zur Abfahrtszeit greifen statt nur "
        "global im Mittel."
    ))

    out.append(H2("7.2 Modulationsbereich der Wallbox"))
    out.append(P(
        "Die Wallbox laedt entweder im erlaubten Modulationsbereich (z. B. "
        "1,4–3,7 kW einphasig oder 4,2–11 kW dreiphasig) oder gar nicht:"
    ))
    out.append(eq_image(
        r"P^{\text{WB,min},w} \cdot y^{\text{WB},w}_t "
        r"\leq P^{\text{WB},w}_t "
        r"\leq \bar{P}^{\text{WB},w} \cdot y^{\text{WB},w}_t"
    ))

    out.append(H2("7.3 EV-Anwesenheitsfenster"))
    out.append(P(
        "Aus Ankunfts- und Abfahrtsstunde wird pro Zeitschritt bestimmt, "
        "ob das Fahrzeug am Stecker ist. Fuer Schritte t ohne EV-Anwesenheit "
        "wird die Ladeleistung hart auf null gesetzt:"
    ))
    out.append(eq_image(
        r"P^{\text{WB},w}_t = 0, \quad\quad \forall t \notin "
        r"\mathcal{T}^{\text{anwesend},w}"
    ))

    out.append(H2("7.4 SOC-Bilanz mit Fahrverbrauch"))
    out.append(P(
        "Anwesend wird mit Wirkungsgrad geladen, abwesend faellt der SOC "
        "um den konstanten Fahrverbrauch (Default 5%/h)."
    ))
    out.append(eq_image(
        r"\text{SOC}^{\text{EV},w}_{t+1} = \text{SOC}^{\text{EV},w}_t + "
        r"\eta^{\text{WB}} \cdot P^{\text{WB},w}_t \cdot \Delta t \cdot "
        r"\mathbb{1}_{t \in \mathcal{T}^{\text{anwesend}}} - "
        r"\ell^{\text{drive}} \cdot \mathbb{1}_{t \notin \mathcal{T}^{\text{anwesend}}}"
    ))
    out.append(P(
        "mit ℓ<sup>drive</sup> = "
        r"<font face='Courier'>driving_loss_pct_per_hour</font>"
        " / 100 · E<sup>EV,kap</sup> · Δt. Bei 60 kWh, 5%/h und 15-min-"
        "Schritt sind das 0,75 kWh pro Schritt."
    ))

    out.append(H2("7.5 Ziel-SOC zur Abfahrt"))
    out.append(P(
        "Statt einer globalen Mindestlademenge wird der Ziel-SOC exakt zur "
        "Abfahrtszeit erzwungen (jede Praesenz→Absenz-Kante):"
    ))
    out.append(eq_image(
        r"\text{SOC}^{\text{EV},w}_{t_{\text{Abfahrt}}} \geq \text{SOC}^{\text{ziel}} \cdot E^{\text{EV,kap}}"
    ))
    out.append(P(
        "Der Ziel-SOC wiederum ergibt sich im Dashboard direkt aus der "
        "vom Nutzer angegebenen Mindestreichweite und dem Verbrauch in "
        "kWh/100 km."
    ))
    out.append(PageBreak())
    return out


def build_objective():
    out = []
    out.append(H1("8. Zielfunktion"))
    out.append(P(
        "Minimiert wird die Summe aus Netzbezugskosten, Einspeise-Erloes "
        "(als Erloes mit Minus), Strafkosten fuer Komfortverletzungen und "
        "Batterie-Alterungskosten. Alle Terme in ct, das Endergebnis wird "
        "spaeter in EUR umgerechnet."
    ))
    out.append(eq_image(
        r"\min_{\mathbf{x}} \quad K^{\text{Netz}} + K^{\text{Slack}} + K^{\text{age}}"
    ))
    out.append(H2("8.1 Netzkosten und Einspeise-Erloes"))
    out.append(eq_image(
        r"K^{\text{Netz}} = \sum_{t \in \mathcal{T}} ("
        r"\pi_t \cdot P^{\text{buy}}_t - \pi^{\text{feed}} \cdot P^{\text{sell}}_t"
        r") \Delta t"
    ))
    out.append(P(
        "π<sub>t</sub> ist der dynamische Strompreis (Day-Ahead-Boersenpreis "
        "+ Tarifkomponenten Netzentgelt, Steuern, Abgaben, Marge), π<sup>feed</sup> "
        "die typischerweise konstante Einspeiseverguetung."
    ))

    out.append(H2("8.2 Komfort-Penalties (Slack)"))
    out.append(P(
        "Mit Strafkosten c<sup>slack</sup> = 500 ct/kWh — deutlich oberhalb "
        "jedes realen Strompreises, sodass Slack erst aktiviert wird, wenn "
        "das Problem sonst infeasible waere. Seit Mai 2026 zusätzlich Slacks "
        "für das Raumlufttemperatur-Komfortband (s<sup>low</sup>, s<sup>high</sup>):"
    ))
    out.append(eq_image(
        r"K^{\text{Slack}} = c^{\text{slack}} \sum_{t \in \mathcal{T}}"
        r"( s^{\text{Heiz}}_t + s^{\text{WW}}_t + s^{\text{low}}_t + s^{\text{high}}_t ) \Delta t"
    ))

    out.append(H2("8.3 Batterie-Alterung"))
    out.append(P("Wie in Abschnitt 4.4 hergeleitet:"))
    out.append(eq_image(
        r"K^{\text{age}} = \frac{c^{\text{age}}}{2} \sum_{t \in \mathcal{T}}"
        r"( P^{\text{batt,ch}}_t + P^{\text{batt,dis}}_t ) \Delta t"
    ))

    out.append(H2("8.4 Vollstaendige Zielfunktion"))
    out.append(eq_image(
        r"\min \sum_{t \in \mathcal{T}} ["
        r"\pi_t P^{\text{buy}}_t - \pi^{\text{feed}} P^{\text{sell}}_t"
        r"+ c^{\text{slack}}(s^{\text{Heiz}}_t + s^{\text{WW}}_t + s^{\text{low}}_t + s^{\text{high}}_t)"
        r"+ \frac{c^{\text{age}}}{2}(P^{\text{batt,ch}}_t + P^{\text{batt,dis}}_t)"
        r"] \Delta t",
        fontsize=11,
    ))
    out.append(PageBreak())
    return out


def build_solving():
    out = []
    out.append(H1("9. Loesungsverfahren"))
    out.append(H2("9.1 Solver"))
    out.append(P(
        "Geloest wird mit <b>HiGHS</b> (high performance dual simplex / "
        "branch-and-cut, MIT-Lizenz) ueber die Python-Schnittstelle PuLP. "
        "Faellt HiGHS aus, wird automatisch <b>CBC</b> (Coin-OR) als Backup "
        "verwendet. Beide sind frei und benoetigen keine Lizenz."
    ))
    out.append(P(
        "Zeitlimit pro Loesung: 120 s. In der Praxis loest HiGHS einen "
        "24-h-Horizont mit 15-min-Schritten und allen Komponenten typisch "
        "in unter 1 s."
    ))

    out.append(H2("9.2 Modellgroesse (Beispiel)"))
    sizes = [
        ["Konfiguration", "Variablen", "davon binaer", "Constraints"],
        ["nur Netz + Last (24h, 15min)", "≈ 290",  "≈ 100", "≈ 200"],
        ["+ PV + Batterie",              "≈ 770",  "≈ 290", "≈ 670"],
        ["+ WP + FBH + WW + SG-Ready",   "≈ 1700", "≈ 580", "≈ 1700"],
        ["+ 2 Wallboxen",                "≈ 2100", "≈ 770", "≈ 2200"],
    ]
    t = Table(sizes, colWidths=[6 * cm, 3 * cm, 3 * cm, 3.2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3d91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaa")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f1f4fb")]),
    ]))
    out.append(t)
    out.append(caption(
        "Tabelle 3: Groessenordnung des Optimierungsmodells fuer typische "
        "Konfigurationen. Werte gerundet; PuLP-Variablenzaehlung."
    ))

    out.append(H2("9.3 Was wird zurueckgegeben?"))
    out.append(P(
        "Nach erfolgreicher Loesung extrahiert der Optimierer alle Variablen "
        "als Zeitreihen und liefert ein <i>OptimizationResult</i>-Objekt:"
    ))
    items = [
        "Netzbezug und -einspeisung pro Zeitschritt",
        "Batterieleistung (Laden/Entladen) und SOC-Trajektorie",
        "Waermepumpenleistung und SG-Ready-Zustand",
        "Estrichtemperatur (aus floor_energy zurueckgerechnet)",
        "Pufferspeichertemperatur (aus ww_energy zurueckgerechnet)",
        "Wallbox-Ladeleistung pro Wallbox",
        "Gesamtkosten in EUR plus separate KPIs (Autarkie, Eigenverbrauch, "
        "Aequivalent-Vollzyklen, Alterungskosten)",
    ]
    out.append(ListFlowable(
        [ListItem(P(s), leftIndent=12) for s in items],
        bulletType="bullet", start="•", leftIndent=18,
    ))

    out.append(H2("9.4 Einbettung in MPC (Day-Ahead-konform seit Apr 2026)"))
    out.append(P(
        "Der MILP-Solver wird auch als Kern des MPC-Reglers (Model Predictive "
        "Control) verwendet — dabei wird er rollierend mit aktualisierten "
        "Prognosen aufgerufen, jeweils nur der erste Steuerschritt umgesetzt. "
        "Der Vorhersagehorizont ist <b>Day-Ahead-konform</b>: <b>vor 13 Uhr</b> "
        "Ortszeit reicht das Fenster bis Tagesende heute (morgige EPEX-Preise "
        "noch nicht publiziert), <b>ab 13 Uhr</b> bis Tagesende morgen. "
        "Hard-Cap durch <font face='Courier'>optimization_horizon_hours</font> "
        "(Default 48 h). Damit nutzt der MPC stets so viel Preis-Information "
        "wie verfügbar, ohne über die Datengrenze hinaus zu schauen."
    ))
    out.append(P(
        "<b>Dynamische Horizont-Anpassung (Mai 2026):</b> Bei aktivierten "
        "Echtdaten prueft "
        "<font face='Courier'>is_day_ahead_published()</font>, ob die EPEX-"
        "Preise fuer den Folgetag schon vorliegen. Falls nicht, schrumpft "
        "<font face='Courier'>load_input_data</font> den Horizont automatisch "
        "von 48 h auf 24 h — es wird nie ueber einen Zeitraum optimiert, "
        "fuer den keine echten Marktpreise vorliegen. Das Dashboard "
        "visualisiert das im Panel <i>Planungshorizont</i> (Gantt-Balken "
        "pro MPC-Iteration mit 13:00-Markern als Day-Ahead-Publikationsgrenze)."
    ))
    out.append(PageBreak())
    return out


def build_summary():
    out = []
    out.append(H1("10. Zusammenfassung"))
    out.append(P(
        "Der MILP-Hauptoptimierer von EMOS Light ist als modulares, "
        "linear-konvexes Mischganzzahliges Programm formuliert. "
        "Alle physikalischen Beziehungen sind so gewaehlt, dass sie linear "
        "bleiben:"
    ))
    points = [
        ("COP konstant pro Pfad",
         "vorberechnete Zeitreihe statt Funktion der Entscheidungsvariablen — "
         "verhindert Bilinearitaet."),
        ("Speicherverluste als feste + lineare Anteile",
         "Zwei-Zonen-Modell ohne quadratische Termpostionen — exakt MILP."),
        ("Lade-/Entlade-Disjunktion ueber Binaervariablen",
         "verhindert physikalisch unsinnige Energiespruenge zum Nulltarif."),
        ("Komfortverletzungen ueber Slack mit Strafkosten",
         "haelt das Problem auch bei Bedarfsspitzen loesbar."),
    ]
    for title, desc in points:
        out.append(P(f"<b>{title}.</b> {desc}"))
    out.append(P(
        "Diese Formulierung ist robust und schnell loesbar; sie liefert ein "
        "global optimales Steuerschema (im Rahmen der Modellannahmen) und "
        "skaliert linear in der Horizontlaenge. Erweiterungen (zusaetzliche "
        "Komponenten, weitere Tarife, Netzentgelt-Lastspitzenkomponenten) "
        "lassen sich modular hinzufuegen, solange Linearitaet gewahrt bleibt."
    ))
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
        title="EMOS Light - MILP-Optimierer (Mathematischer Bericht)",
        author="EMOS Light Projektteam",
    )

    story = []
    story += build_cover()
    story += build_overview()
    story += build_notation()
    story += build_grid_balance()
    story += build_battery()
    story += build_heatpump()
    story += build_thermal_storages()
    story += build_wallbox()
    story += build_objective()
    story += build_solving()
    story += build_summary()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "MILP_Optimierer_Bericht.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
