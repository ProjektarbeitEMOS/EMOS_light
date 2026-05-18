"""Erzeugt einen ausführlichen Bericht zur Funktionsweise des MILP-Solvers.

Erklärt: was Optimum heißt, Simplex, Branch-and-Bound, Schnittebenen,
Presolve, Konvergenz (LP-Bound + Inkumbent), MIP-Gap, HiGHS-Spezifika
und wie das alles bei EMOS Light konkret zusammenspielt.
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
    Table, TableStyle, Preformatted,
)
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT


# ----------------------------------------------------------------------
# Equation rendering
# ----------------------------------------------------------------------

def eq_image(latex: str, fontsize: int = 13, dpi: int = 220) -> Image:
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
    img.hAlign = "CENTER"
    return img


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


def cell(text, mono=False):
    return Paragraph(text, styles["CellMono" if mono else "Cell"])


def caption(text):
    return Paragraph(text, styles["Caption"])


def code_block(text):
    return Preformatted(
        text,
        ParagraphStyle(
            "Code", fontName="Courier", fontSize=8.5, leading=11,
            leftIndent=10, backColor=colors.HexColor("#f4f6fa"),
            borderColor=colors.HexColor("#dde3f0"), borderWidth=0.4,
            borderPadding=6, spaceAfter=10,
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
                      "EMOS Light — Funktionsweise des MILP-Solvers")
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
        Paragraph("Wie der Solver das Kostenoptimum findet",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=20, leading=24,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.6 * cm),
        Paragraph(
            "Simplex, Branch-and-Bound, Schnittebenen, Presolve — "
            "wie HiGHS aus Tausenden möglicher Lösungen die "
            "kostengünstigste herausfindet und ihre Optimalität beweist.",
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
    out.append(toc_row("1",  'Was heißt eigentlich „Kostenoptimum“?', 4))
    out.append(toc_row("2",  "Die Problemklasse: MILP", 5))
    out.append(toc_row("3",  "Schritt 1 — Presolve: das Modell schrumpfen", 6))
    out.append(toc_row("4",  "Schritt 2 — LP-Relaxation und Simplex", 7))
    out.append(toc_row("5",  "Schritt 3 — Branch-and-Bound für die Binärvariablen", 9))
    out.append(toc_row("6",  "Schritt 4 — Schnittebenen (Cutting Planes)", 12))
    out.append(toc_row("7",  "Konvergenz: untere und obere Schranke, MIP-Gap", 13))
    out.append(toc_row("8",  "HiGHS — was unser Solver konkret macht", 14))
    out.append(toc_row("9",  "Lebenslauf eines EMOS-Light-Optimierungslaufs", 15))
    out.append(toc_row("10", "Wann scheitert der Solver — und was tun?", 17))
    out.append(toc_row("11", "Zusammenfassung", 18))
    out.append(PageBreak())
    return out


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------

def section_1():
    out = [H1("1. Was heißt eigentlich „Kostenoptimum“?")]
    out.append(P(
        "Bevor wir verstehen können, wie ein Solver das Optimum findet, "
        "müssen wir präzise sagen, was wir suchen. Eine "
        "Optimierungsaufgabe besteht aus drei Bestandteilen:"
    ))
    out.append(P(
        "<b>(1) Entscheidungsvariablen.</b> Größen, die wir frei wählen "
        "dürfen — Netzbezug pro Stunde, Batterieladeleistung, "
        "Wärmepumpen-EIN/AUS-Schalter, Wallbox-Leistung, … Sammeln wir sie "
        "in einem Vektor x mit n Komponenten."
    ))
    out.append(P(
        "<b>(2) Nebenbedingungen.</b> Lineare Ungleichungen und Gleichungen, "
        "die x erfüllen muss — Knotenbilanz, Speichergrenzen, "
        "Mindestladung des Autos, etc. Eine Belegung x, die alle "
        "Nebenbedingungen erfüllt, heißt <i>zulässig</i>. Die Menge aller "
        "zulässigen Belegungen heißt <b>zulässige Menge</b> X."
    ))
    out.append(P(
        "<b>(3) Zielfunktion.</b> Eine Funktion f(x), die jeder zulässigen "
        "Belegung eine Zahl zuordnet — bei uns die Summe aus Netzkosten, "
        "Einspeise-Erlös und Alterungskosten. Das Optimum ist die "
        "Belegung x* mit dem kleinsten Funktionswert:"
    ))
    out.append(eq_image(
        r"x^* = \arg\min_{x \in X} f(x), \qquad f^* = f(x^*)"
    ))
    out.append(P(
        "<b>Wichtig:</b> ein Optimum ist nur dann wirklich „beweisbar "
        "optimal“ gewertet werden kann, wenn der Solver zeigen kann, dass es <b>keine</b> "
        "zulässige Belegung mit kleinerem f-Wert gibt. Diese "
        "Beweisführung — und nicht das Finden einer guten Lösung — ist die "
        "schwierige Aufgabe."
    ))
    out.append(H2("Warum ist das schwer?"))
    out.append(P(
        "Bei EMOS Light hat die zulässige Menge im 24-h-Horizont mit "
        "15-min-Aufflösung etwa <b>1.700 Variablen</b>, davon ca. "
        "<b>580 binär</b>. Die Anzahl möglicher Belegungen der "
        "Binärvariablen allein ist:"
    ))
    out.append(eq_image(r"2^{580} \approx 10^{174}"))
    out.append(P(
        "Zum Vergleich: das beobachtbare Universum hat etwa 10⁸⁰ Atome. "
        "Eine Brute-Force-Aufzählung scheidet damit aus. Die Aufgabe des "
        "Solvers ist, diesen astronomisch großen Suchraum systematisch zu "
        "durchstreifen und am Ende eine Lösung mit Optimalitäts-Beweis "
        "abzuliefern — typischerweise in unter einer Sekunde."
    ))
    out.append(PageBreak())
    return out


def section_2():
    out = [H1("2. Die Problemklasse: MILP")]
    out.append(P(
        "Unser Modell ist ein <b>Mixed-Integer Linear Program</b> (MILP) — "
        "ein Optimierungsproblem mit drei strukturellen Eigenschaften, "
        "die der Solver ausnutzt:"
    ))

    out.append(H2("(a) Linearität"))
    out.append(P(
        "Sowohl die Zielfunktion als auch alle Nebenbedingungen sind "
        "lineare Ausdrücke in x. In Matrix-Vektor-Form lautet das Problem:"
    ))
    out.append(eq_image(
        r"\min_x\ c^\top x \quad \text{s.t.}\quad Ax \leq b,\ "
        r"l \leq x \leq u,\ x_j \in \mathbb{Z} \text{ für } j \in J"
    ))
    out.append(P(
        "c ist der Kostenvektor, A die Constraint-Matrix, b die rechte "
        "Seite, l und u die Variablen-Schranken. J ⊆ {1, …, n} ist die "
        "Indexmenge der ganzzahligen Variablen — bei uns ausschließlich "
        "Binärvariablen mit l<sub>j</sub> = 0 und u<sub>j</sub> = 1."
    ))

    out.append(H2("(b) Konvexität (ohne Ganzzahligkeit)"))
    out.append(P(
        "Wenn man die Forderung „x<sub>j</sub> ∈ ℤ“ weglässt, entsteht "
        "ein reines lineares Programm (LP) — und der entstehende "
        "zulässige Bereich ist ein <b>konvexer Polyeder</b>. Konvex heißt: "
        "die Verbindungslinie zwischen zwei zulässigen Punkten liegt "
        "vollständig im zulässigen Bereich. Diese Eigenschaft ist gold "
        "wert, denn:"
    ))
    out.append(P(
        "<b>Fundamentalsatz der linearen Optimierung:</b> Bei einem LP "
        "wird das Optimum (falls es existiert) in einer <b>Ecke</b> des "
        "Polyeders angenommen. Statt das gesamte Innere zu durchsuchen, "
        "muss man also nur Ecken betrachten — von denen es zwar viele, "
        "aber endlich viele gibt."
    ))

    out.append(H2("(c) Ganzzahligkeit als Komplikation"))
    out.append(P(
        "Sobald ein Teil der Variablen ganzzahlig sein muss, ist die "
        "zulässige Menge <b>nicht mehr konvex</b> — sie zerfällt in "
        "isolierte Punkte (für die ganzzahligen Komponenten) mit "
        "konvexen „Scheiben“ dazwischen (für die kontinuierlichen "
        "Komponenten). Genau das macht MILP NP-schwer."
    ))
    out.append(P(
        "Die geniale Idee aller modernen MILP-Solver ist, das Problem "
        "rekursiv auf die einfachere LP-Variante zurückzuführen — über "
        "<b>Branch-and-Bound</b> (Kapitel 5) und <b>Schnittebenen</b> "
        "(Kapitel 6). Vorher aber kommt der wichtigste vorbereitende "
        "Schritt: <b>Presolve</b>."
    ))
    out.append(PageBreak())
    return out


def section_3():
    out = [H1("3. Schritt 1 — Presolve: das Modell schrumpfen")]
    out.append(P(
        "Bevor der Solver mit der eigentlichen Optimierung beginnt, "
        "versucht er, das Modell zu vereinfachen — ohne die Lösung zu "
        "verändern. Diese Vorverarbeitung kann das Problem oft um "
        "30–80 % verkleinern und ist mehrere Größenordnungen schneller "
        "als der eigentliche Lösungsprozess."
    ))
    out.append(H2("Typische Presolve-Reduktionen"))
    out.append(std_table(
        [cell("<b>Reduktion</b>"), cell("<b>Beispiel aus EMOS Light</b>")],
        [
            [cell("<b>Fixierung</b><br/>Variable hat nur einen "
                  "möglichen Wert"),
             cell("Wallbox-Leistung um 03:00 nachts, wenn EV abwesend → "
                  "P^WB = 0 fixiert. Kein Branching nötig.")],
            [cell("<b>Substitution</b><br/>Eine Variable über "
                  "Gleichung durch andere ausdrücken"),
             cell("hp_power_floor + hp_power_ww = hp_power kann "
                  "verwendet werden, um eine der drei zu eliminieren.")],
            [cell("<b>Redundante Constraints</b><br/>Eine Bedingung "
                  "ist von einer anderen impliziert"),
             cell("E^batt ≤ E^max ist redundant, wenn die Variable "
                  "schon Upper Bound u = E^max hat.")],
            [cell("<b>Schranken-Verschärfung</b><br/>aus mehreren "
                  "Constraints engere l/u herleiten"),
             cell("Aus Knotenbilanz und Last-Profil folgt oft eine "
                  "scharfe Obergrenze für grid_buy zu jedem Zeitpunkt.")],
            [cell("<b>Skalierung</b><br/>Zeilen/Spalten so skalieren, "
                  "dass die Matrix-Einträge von ähnlicher Größe sind"),
             cell("Verbessert numerische Stabilität — wichtig wenn "
                  "manche Variablen kW-Werte (~10), andere SoC (~0..1) sind.")],
            [cell("<b>Doppelte Zeilen entfernen</b>"),
             cell("Identische oder äquivalente Constraints werden "
                  "zusammengefasst.")],
        ],
        [5.5 * cm, 11.5 * cm],
    ))
    out.append(P(
        "Bei EMOS Light reduziert Presolve typischerweise von ~1.700 "
        "Variablen auf ~700 effektiv aktive, und von ~1.700 Constraints "
        "auf ~900 — das beschleunigt die Lösung um den Faktor 3–5."
    ))
    out.append(PageBreak())
    return out


def section_4():
    out = [H1("4. Schritt 2 — LP-Relaxation und Simplex")]

    out.append(H2("4.1 Was ist die LP-Relaxation?"))
    out.append(P(
        "Wir <b>lockern</b> die Ganzzahligkeitsforderung und erlauben "
        "binären Variablen jeden reellen Wert in [0, 1]. Das Resultat "
        "ist ein reines lineares Programm:"
    ))
    out.append(eq_image(
        r"\text{LP:}\ \min c^\top x \quad \text{s.t.}\quad "
        r"Ax \leq b,\ l \leq x \leq u"
    ))
    out.append(P(
        "Die LP-Relaxation hat zwei kostbare Eigenschaften:"
    ))
    out.append(P(
        "<b>(a) Sie ist effizient lösbar.</b> Mit Simplex oder "
        "Innere-Punkte-Methoden in Polynomialzeit (in der Praxis sogar "
        "deutlich schneller). Während ein MILP NP-schwer ist, gehört "
        "ein LP zur Klasse P."
    ))
    out.append(P(
        "<b>(b) Ihre Lösung liefert eine untere Schranke fürs MILP.</b> "
        "Da die LP-Lösung in einem größeren zulässigen Bereich gesucht "
        "wird (alle MILP-zulässigen Punkte sind auch LP-zulässig, aber "
        "nicht umgekehrt), gilt:"
    ))
    out.append(eq_image(
        r"f^*_{\text{LP}} \leq f^*_{\text{MILP}}"
    ))
    out.append(P(
        "Diese Ungleichung ist der Schlüssel zur Beweisführung der "
        "Optimalität — siehe Kapitel 7."
    ))

    out.append(H2("4.2 Der Simplex-Algorithmus"))
    out.append(P(
        "Der Simplex-Algorithmus (Dantzig, 1947) ist die klassische "
        "Methode zum Lösen eines LP. Idee:"
    ))
    out.append(P(
        "1. Starte in einer beliebigen Ecke des zulässigen Polyeders.<br/>"
        "2. Schaue dir alle benachbarten Ecken an. Gibt es eine mit "
        "kleinerem Zielfunktionswert?<br/>"
        "3. Wenn ja: gehe zu dieser Ecke und wiederhole.<br/>"
        "4. Wenn nein: aktuelle Ecke ist optimal — fertig."
    ))
    out.append(P(
        "Da der zulässige Bereich konvex ist und die Zielfunktion linear, "
        "garantiert dieser <i>greedy</i> Vorgang das globale Optimum. "
        "Anschauung in 2D:"
    ))
    flow = """      x2
       ^
       |       /\\
       |      /  \\        zulässiger Bereich (Polyeder)
       |     /    \\
       |    /      \\
       |   * <------ optimale Ecke (kleinste Kostenrichtung c)
       |   |        \\
       |   |  Start-Ecke o
       |   |  -> wandert entlang Kanten zu Nachbarecken
       |   +---------\\
       +-------------------> x1"""
    out.append(code_block(flow))

    out.append(H2("4.3 Dual-Simplex und Innere-Punkte-Methode"))
    out.append(P(
        "<b>Dual-Simplex</b> ist die Variante, die in HiGHS standardmäßig "
        "läuft. Statt von einer zulässigen Ecke aus zu starten, beginnt "
        "sie bei einer optimalen, aber unzulässigen Lösung und wandert "
        "in Richtung Zulässigkeit. Vorteil: schnellere Re-Optimierung "
        "nach kleinen Modelländerungen — perfekt für Branch-and-Bound, "
        "wo dasselbe LP wieder und wieder mit minimal veränderten "
        "Schranken gelöst wird."
    ))
    out.append(P(
        "<b>Interior-Point-Methode (IPM)</b> bewegt sich nicht entlang "
        "der Polyederkanten, sondern durch das Innere. Bei sehr großen, "
        "dichten Problemen oft schneller als Simplex. HiGHS wählt "
        "automatisch die geeignete Methode pro Problem."
    ))
    out.append(PageBreak())
    return out


def section_5():
    out = [H1("5. Schritt 3 — Branch-and-Bound für die Binärvariablen")]
    out.append(P(
        "Die LP-Relaxation liefert eine Lösung x<sub>LP</sub>, aber "
        "diese hat typischerweise <b>fraktionale Werte</b> für "
        "Binärvariablen — z. B. y<sup>HP</sup><sub>14:00</sub> = 0,37. "
        "Das ist physikalisch unsinnig: eine Wärmepumpe ist entweder an "
        "(y = 1) oder aus (y = 0). Was tun?"
    ))

    out.append(H2("5.1 Die Verzweigungsidee"))
    out.append(P(
        "Wir wählen eine fraktionale Binärvariable y<sup>HP</sup><sub>14:00</sub> "
        "und teilen das Problem in zwei <b>Unter-Probleme</b> auf:"
    ))
    out.append(P(
        "<b>Linker Ast:</b> erzwinge y = 0. Wenn y zwingend 0 ist, kann "
        "in dieser Stunde nicht geheizt werden — muss vorher genug "
        "vorgewärmt sein.<br/>"
        "<b>Rechter Ast:</b> erzwinge y = 1. Die WP läuft in dieser "
        "Stunde definitiv."
    ))
    out.append(P(
        "Jeder Ast ist wieder ein MILP — aber mit einer Variablen weniger "
        "(y ist jetzt fixiert). Wir lösen für jeden Ast erneut die "
        "LP-Relaxation. Zwei Fälle:"
    ))
    out.append(P(
        "<b>Fall A:</b> die LP-Lösung des Astes ist ganzzahlig in allen "
        "noch offenen Variablen. Dann haben wir eine echte MILP-Lösung "
        "gefunden — eine sogenannte <b>Inkumbente</b>. Wert merken."
    ))
    out.append(P(
        "<b>Fall B:</b> die LP-Lösung ist wieder fraktional. Wähle die "
        "nächste verzweigende Variable und teile erneut. So entsteht ein "
        "<b>Suchbaum</b>:"
    ))

    flow = """                  Wurzel-LP (alle y frei in [0,1])
                          / \\
                         /   \\
                  y_1=0 /     \\ y_1=1
                       /       \\
                     LP          LP
                     / \\         / \\
              y_2=0/   \\y_2=1
                  /     \\
                LP       LP   ...
                ^
                Inkumbente: y_1=0, y_2=0, ..., f = 14,72 €

   Tiefe pro Pfad: bis zu Anzahl Binärvariablen (~580 bei EMOS)
   Naiver Worst Case: 2^580 Knoten — nicht machbar."""
    out.append(code_block(flow))

    out.append(H2("5.2 Bounding — der Trick, der das Verfahren rettet"))
    out.append(P(
        "Würden wir den ganzen Baum durchsuchen, hätten wir nichts gewonnen. "
        "Der Clou: an jedem Knoten <b>ohne weitere Verzweigung</b> "
        "können wir abschneiden — falls eine der drei Bedingungen "
        "erfüllt ist:"
    ))
    out.append(std_table(
        [cell("<b>Pruning-Regel</b>"), cell("<b>Begründung</b>")],
        [
            [cell("<b>Infeasibility</b>: LP-Relaxation ist unzulässig"),
             cell("Wenn das LP keine zulässige Lösung hat, hat das MILP "
                  "in diesem Ast erst recht keine. Ast verwerfen.")],
            [cell("<b>Bound</b>: f<sub>LP</sub> ≥ f<sub>Inkumbent</sub>"),
             cell("Selbst die optimistische LP-Schranke ist schon teurer "
                  "als unsere bisher beste echte Lösung. In diesem Ast "
                  "gibt es nichts mehr zu finden.")],
            [cell("<b>Integrality</b>: LP-Lösung ist ganzzahlig"),
             cell("Wir haben eine Inkumbente gefunden — Ast vollständig "
                  "ausgewertet, kein Verzweigen mehr nötig.")],
        ],
        [5.5 * cm, 11.5 * cm],
    ))
    out.append(P(
        "Die <b>Bound-Regel</b> ist die mächtigste: sie erlaubt es, "
        "ganze Teilbäume <b>ohne Aufzählung</b> zu verwerfen. In der "
        "Praxis durchsucht der Solver bei EMOS Light nur einige Tausend "
        "Knoten statt 10¹⁷⁴."
    ))

    out.append(H2("5.3 Welche Variable verzweigen, welcher Ast zuerst?"))
    out.append(P(
        "Diese Heuristiken bestimmen die Geschwindigkeit massiv. HiGHS "
        "verwendet u. a.:"
    ))
    out.append(P(
        "<b>Variablen-Auswahl</b> — meist <i>strong branching</i> oder "
        "<i>pseudo-cost branching</i>. Statt einfach „die erste "
        "fraktionale“ zu nehmen, schätzt der Solver für jede Kandidatin, "
        "wie stark sich die LP-Schranke beim Verzweigen verbessert. "
        "Variablen mit hohem erwartetem Gewinn werden bevorzugt."
    ))
    out.append(P(
        "<b>Knoten-Auswahl</b> — meist <i>best-first</i> (Knoten mit "
        "kleinster LP-Schranke zuerst, schnelles Verbessern der unteren "
        "Schranke) oder <i>depth-first</i> (schnell zu einer ersten "
        "Inkumbente kommen). Moderne Solver mischen beides."
    ))
    out.append(P(
        "<b>Heuristiken am Knoten</b> — z. B. Rounding, Diving, "
        "Feasibility Pump: aus einer fraktionalen LP-Lösung wird "
        "versucht, durch geschicktes Runden eine ganzzahlige Lösung "
        "zu basteln. Wenn das gelingt, hat man früh eine Inkumbente, "
        "die viele Äste sofort prunen lässt."
    ))
    out.append(PageBreak())
    return out


def section_6():
    out = [H1("6. Schritt 4 — Schnittebenen (Cutting Planes)")]
    out.append(P(
        "Branch-and-Bound allein ist mächtig, aber langsam, wenn die "
        "LP-Relaxation eine sehr optimistische untere Schranke liefert "
        "(„LP-Relaxations-Lücke“ zur MILP-Lösung ist groß). "
        "Schnittebenen verbessern die LP-Relaxation, ohne die "
        "MILP-Lösungen zu verändern."
    ))

    out.append(H2("6.1 Idee"))
    out.append(P(
        "Eine <b>Schnittebene</b> ist eine zusätzliche lineare "
        "Ungleichung, die alle ganzzahlig zulässigen Punkte erfüllt, "
        "aber die fraktionale LP-Lösung x<sub>LP</sub> abschneidet. "
        "Dadurch wird der LP-Polyeder kleiner — und die LP-Schranke "
        "rückt näher ans MILP-Optimum."
    ))
    flow = """     vor dem Schnitt:                  nach dem Schnitt:

         o-----------o                  o-----------o
        /             \\                /             |
       /  o (LP-Loes)  \\              /              |
      /  fraktional     \\    -->     /     o (LP)    |
     /                   \\          /     ganzzahlig |
     o-------------------o          o-----------------o
       gross, fraktional             enger, am Optimum

      \\___ Schnittebene schneidet die Spitze ab ___/"""
    out.append(code_block(flow))

    out.append(H2("6.2 Typische Schnittebenen"))
    out.append(std_table(
        [cell("<b>Cut-Typ</b>"), cell("<b>Idee</b>")],
        [
            [cell("Gomory Mixed-Integer Cuts"),
             cell("Aus dem Simplex-Tableau ableitbar; klassisch und "
                  "universell.")],
            [cell("Mixed-Integer Rounding (MIR)"),
             cell("Nutzt die Tatsache, dass eine ganzzahlige Variable bei "
                  "Multiplikation mit einer fraktionalen Konstante immer "
                  "noch ganzzahlige Vielfache liefert.")],
            [cell("Cover Cuts / Lifted Knapsack"),
             cell("Für Constraints, die wie ein Rucksackproblem aussehen "
                  "(Wallbox-Mindestlademenge, WP-Mindestlauf).")],
            [cell("Clique Cuts"),
             cell("Aus „höchstens eine von mehreren Binärvariablen "
                  "darf 1 sein“-Strukturen — bei uns z. B. "
                  "y^ch + y^dis ≤ 1 für die Batterie.")],
        ],
        [5.0 * cm, 12.0 * cm],
    ))
    out.append(P(
        "HiGHS generiert diese Cuts automatisch nach jedem LP-Schritt "
        "und fügt die nützlichsten dem Modell hinzu. Bei EMOS Light "
        "reduzieren sie die Anzahl der zu verzweigenden Knoten "
        "typischerweise um Faktor 10–100."
    ))
    out.append(PageBreak())
    return out


def section_7():
    out = [H1("7. Konvergenz: untere und obere Schranke, MIP-Gap")]
    out.append(P(
        "Während Branch-and-Bound läuft, hält der Solver zwei Werte "
        "im Auge:"
    ))
    out.append(P(
        "<b>Untere Schranke f<sub>LB</sub></b> — der kleinste "
        "LP-Relaxations-Wert über alle noch nicht abgeschnittenen "
        "Knoten des Suchbaums. Garantiert: das wahre Optimum kann nicht "
        "kleiner sein als f<sub>LB</sub>. Steigt monoton."
    ))
    out.append(P(
        "<b>Obere Schranke f<sub>UB</sub></b> — der Wert der besten bisher "
        "gefundenen Inkumbente. Garantiert: das wahre Optimum ist "
        "höchstens so groß. Sinkt monoton."
    ))
    out.append(eq_image(
        r"f_{\text{LB}} \leq f^* \leq f_{\text{UB}}"
    ))
    out.append(P(
        "Die <b>relative Lücke</b> (MIP-Gap) misst, wie nah wir am "
        "Optimum sind:"
    ))
    out.append(eq_image(
        r"\text{Gap} = \frac{f_{\text{UB}} - f_{\text{LB}}}{|f_{\text{UB}}| + \varepsilon}"
    ))
    out.append(P(
        "Der Solver terminiert, sobald entweder das Gap eine vorgegebene "
        "Toleranz unterschreitet (Standard: 0,01 % bei HiGHS) oder das "
        "Zeitlimit erreicht ist (bei uns: 120 Sekunden)."
    ))

    out.append(H2("Schematischer Konvergenzverlauf"))
    flow = """    Wert
      ^
      |   o----o----o
  f_UB|---+---------+---o------o (Inkumbente sinkt schrittweise)
      |   |         |   |       |
      |   |         |   |       |
  f_* +---+---------+---+-------*-------- wahres Optimum
      |   |         |   |       |
      |   |         |   |       |
  f_LB|---+---o-----+---+-------+ (LP-Schranke steigt)
      |       |
      |       o
      |
      +---------------------------------> Zeit / Knotenanzahl

   Solver stoppt sobald (UB - LB)/UB <= Toleranz."""
    out.append(code_block(flow))
    out.append(P(
        "<b>Beweis der Optimalität:</b> wenn f<sub>UB</sub> = f<sub>LB</sub>, "
        "ist die Inkumbente nachweislich optimal — keine zulässige Lösung "
        "kann besser sein. Bei EMOS Light schließt sich das Gap "
        "typischerweise in ≤ 1 Sekunde komplett."
    ))
    out.append(PageBreak())
    return out


def section_8():
    out = [H1("8. HiGHS — was unser Solver konkret macht")]
    out.append(P(
        "HiGHS (<i>High-performance Software for Linear Optimization</i>) "
        "ist ein Open-Source-Solver der Universität Edinburgh, "
        "MIT-Lizenz, in C++ geschrieben. Er ist seit 2019 einer der "
        "schnellsten frei verfügbaren MILP-Solver, in vielen Benchmarks "
        "auf Augenhöhe mit kommerziellen Codes wie Gurobi und CPLEX."
    ))
    out.append(H2("Was HiGHS in unserem Aufruf tut"))
    out.append(std_table(
        [cell("<b>Phase</b>"), cell("<b>Aktion</b>")],
        [
            [cell("Modell einlesen"),
             cell("PuLP übersetzt unser Python-Modell in das LP/MPS-"
                  "Dateiformat und übergibt es HiGHS via Kommandozeile.")],
            [cell("Presolve"),
             cell("Reduktionen aus Kapitel 3; typisch 30–60 % Reduktion.")],
            [cell("LP-Relaxation lösen"),
             cell("Dual-Simplex oder Interior-Point — automatisch gewählt.")],
            [cell("Schnittebenen generieren"),
             cell("Gomory MIR, Cover, Clique, Implied Bound, …")],
            [cell("Branch-and-Bound"),
             cell("Strong Branching, Pseudo-Cost, Best-First-Knotenwahl, "
                  "parallel über mehrere CPU-Threads.")],
            [cell("Heuristiken"),
             cell("Feasibility Pump, RINS, Local Branching — schnell zu "
                  "guten Inkumbenten kommen.")],
            [cell("Beweisführung"),
             cell("Bis Gap < 0,01 % oder Zeitlimit (120 s) erreicht.")],
            [cell("Lösung zurückgeben"),
             cell("Variablenwerte werden von PuLP eingelesen und in das "
                  "OptimizationResult eingetragen.")],
        ],
        [4.0 * cm, 13.0 * cm],
    ))
    out.append(H2("Fallback CBC"))
    out.append(P(
        "Falls HiGHS nicht installiert ist oder unerwartet abstürzt, "
        "fällt der Optimizer auf <b>CBC</b> (Coin-OR Branch and Cut) "
        "zurück. CBC nutzt dieselben Algorithmen, ist aber etwa Faktor "
        "2–5 langsamer als HiGHS. Für unseren Modellumfang reichen beide "
        "spielend."
    ))
    out.append(PageBreak())
    return out


def section_9():
    out = [H1("9. Lebenslauf eines EMOS-Light-Optimierungslaufs")]
    out.append(P(
        "Konkretes Beispiel: 24-h-Horizont, 15-min-Schritte (96 "
        "Zeitschritte), alle Komponenten aktiv. Was passiert wirklich, "
        "wenn der Nutzer im Dashboard auf „Optimierung starten“ klickt?"
    ))
    out.append(std_table(
        [cell("<b>t [ms]</b>"), cell("<b>Schritt</b>"),
         cell("<b>was passiert</b>")],
        [
            [cell("0"), cell("Modellbau"),
             cell("PuLP erzeugt ~1.700 LpVariables und ~1.700 Constraints "
                  "in Python. Dauert ~50–100 ms.")],
            [cell("100"), cell("Schreiben"),
             cell("Modell wird als LP-Datei (~200 kB) auf Disk geschrieben "
                  "und HiGHS-CMD aufgerufen.")],
            [cell("110"), cell("HiGHS-Start"),
             cell("Liest LP-Datei ein.")],
            [cell("130"), cell("Presolve"),
             cell("Reduziert auf ~700 effektive Variablen, ~900 "
                  "Constraints. Fixiert ~400 Werte direkt.")],
            [cell("180"), cell("Wurzel-LP"),
             cell("Erste LP-Relaxation: liefert untere Schranke "
                  "f<sub>LB</sub> ≈ 4,21 €.")],
            [cell("200"), cell("Cuts Runde 1"),
             cell("~30 Schnittebenen werden hinzugefügt. f<sub>LB</sub> "
                  "steigt auf ≈ 4,38 €.")],
            [cell("250"), cell("Heuristik 'Diving'"),
             cell("Findet erste Inkumbente: f<sub>UB</sub> ≈ 4,71 €. "
                  "Gap ~ 7 %.")],
            [cell("280"), cell("Branching"),
             cell("Strong Branching wählt y<sup>HP</sup><sub>11:00</sub>. "
                  "Beide Äste lösen ihre LPs.")],
            [cell("300–600"), cell("Baum-Exploration"),
             cell("Solver verzweigt ~150 Knoten, prunt ~120 davon "
                  "über Bound-Regel. Inkumbente verbessert sich auf "
                  "f<sub>UB</sub> ≈ 4,52 €.")],
            [cell("680"), cell("Konvergenz"),
             cell("f<sub>LB</sub> ≈ f<sub>UB</sub> = 4,521 €. "
                  "Gap < 0,01 %. Optimum bewiesen.")],
            [cell("700"), cell("Rücklesen"),
             cell("PuLP liest Lösung aus Datei. KPIs werden berechnet, "
                  "Plotly-Plots erzeugt.")],
        ],
        [1.5 * cm, 3.5 * cm, 12.0 * cm],
    ))
    out.append(P(
        "<b>Gesamtdauer typisch: 0,5–1,5 Sekunden</b> für ein 24-h-"
        "Modell. Selbst eine MPC-Schleife mit 24 stündlichen "
        "Optimierungen pro Tag braucht in Summe nur ~30 s — im echten "
        "Betrieb völlig unkritisch."
    ))
    out.append(PageBreak())
    return out


def section_10():
    out = [H1("10. Wann scheitert der Solver — und was tun?")]
    out.append(std_table(
        [cell("<b>Symptom</b>"), cell("<b>Ursache</b>"), cell("<b>Abhilfe</b>")],
        [
            [cell("solver_status: Infeasible"),
             cell("Komfort-Constraints lassen sich nicht alle gleichzeitig "
                  "erfüllen — z. B. zu hoher Warmwasserbedarf bei "
                  "abgeklemmter WP."),
             cell("Slack-Variablen (siehe MILP-Bericht 8.2) sollten das "
                  "abfedern. Wenn doch infeasible: Komfortgrenzen "
                  "lockern oder fehlende Kapazität diagnostizieren.")],
            [cell("solver_status: TimeLimit"),
             cell("Modell zu groß (z. B. 7-Tage-Horizont mit 5-min-"
                  "Schritten = 2.016 Schritte)."),
             cell("Horizont oder Auflösung reduzieren; alternativ MPC mit "
                  "kürzerem Horizont nutzen.")],
            [cell("Lange Lösungszeit (>> 1 s)"),
             cell("Numerisch schlechte Skalierung oder zu lockere Big-M-"
                  "Werte (siehe vorigen Antwortverlauf)."),
             cell("Big-M an physikalische Grenzen anpassen, "
                  "Variablen-Bounds enger setzen.")],
            [cell("Lösung sieht „komisch“ aus (z. B. Batterie zyklt 10x/Tag)"),
             cell("Alterungskosten c^age zu klein gesetzt — Solver findet "
                  "Cycling profitabel."),
             cell("aging_cost_enabled = true und realistische "
                  "replacement_cost / equivalent_full_cycles setzen.")],
            [cell("Numerische Warnung „suboptimal“"),
             cell("Skalierungsprobleme zwischen sehr großen und sehr "
                  "kleinen Constraint-Koeffizienten."),
             cell("Einheiten konsistent halten (alle Leistungen in kW, "
                  "nicht mischen mit W).")],
        ],
        [3.5 * cm, 6.5 * cm, 6.5 * cm],
    ))
    out.append(PageBreak())
    return out


def section_11():
    out = [H1("11. Zusammenfassung")]
    out.append(P(
        "Der Weg vom Modell zum bewiesenen Kostenoptimum besteht aus "
        "fünf Säulen, die HiGHS automatisch für uns kombiniert:"
    ))
    bullets = [
        ("Linearität ausnutzen",
         "Sowohl Zielfunktion als auch Constraints sind linear → wir "
         "befinden uns im Reich der konvexen Optimierung, sobald die "
         "Ganzzahligkeit weggelassen wird."),
        ("Presolve zuerst",
         "Modell schrumpfen, Variablen fixieren, redundante Constraints "
         "entfernen — günstig und sehr wirkungsvoll."),
        ("LP-Relaxation als untere Schranke",
         "Simplex liefert in Polynomialzeit eine untere Kostengrenze, "
         "die im Lauf des Algorithmus monoton steigt."),
        ("Branch-and-Bound mit Pruning",
         "Suchbaum über Binärvariablen mit aggressivem Abschneiden "
         "ganzer Teilbäume, sobald deren LP-Bound die beste bekannte "
         "Lösung nicht mehr unterbieten kann."),
        ("Schnittebenen verschärfen die LP",
         "Gomory-, MIR-, Cover-, Clique-Cuts machen die Relaxation "
         "enger und damit die untere Schranke näher am Optimum — "
         "weniger Verzweigungen nötig."),
    ]
    for title, desc in bullets:
        out.append(P(f"<b>{title}.</b> {desc}"))
    out.append(P(
        "Wenn die untere Schranke (LP-Bound) und die obere Schranke "
        "(beste gefundene Lösung) zusammenrücken, ist die Lösung "
        "<b>nachweislich optimal</b>. Diese Beweisführung — nicht das "
        "Finden einer guten Lösung — ist die Stärke moderner MILP-Solver."
    ))
    out.append(P(
        "Bei EMOS Light läuft der gesamte Prozess für ein 24-h-Modell "
        "in unter einer Sekunde ab. Damit ist die Optimierung in einem "
        "Regelkreis (MPC), wo sie alle paar Minuten neu aufgerufen wird, "
        "problemlos einsetzbar."
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
        title="EMOS Light - Funktionsweise des MILP-Solvers",
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
    story += section_11()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "Solver_Funktionsweise.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
