"""Erzeugt eine PDF-Roadmap für die Zwischenstands-Präsentation."

Speakers-Guide mit Zeiten, Talking-Points, Demo-Cues und Q&A-Prep.
Soll während der Präsentation neben dem Laptop liegen.
"""

import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, KeepTogether,
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
    name="H1", parent=styles["Heading1"], fontSize=16, leading=20,
    spaceBefore=6, spaceAfter=6, textColor=colors.HexColor("#0b3d91"),
))
styles.add(ParagraphStyle(
    name="H2", parent=styles["Heading2"], fontSize=12, leading=15,
    spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#143f7a"),
))
styles.add(ParagraphStyle(
    name="Talking", parent=styles["BodyText"], fontSize=10.5, leading=14,
    leftIndent=14, spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="Demo", parent=styles["BodyText"], fontSize=10.5, leading=14,
    leftIndent=14, spaceAfter=4, textColor=colors.HexColor("#0a6e2e"),
    backColor=colors.HexColor("#eaf6ed"),
    borderColor=colors.HexColor("#b9d9c0"),
    borderWidth=0.5, borderPadding=6,
))
styles.add(ParagraphStyle(
    name="Quote", parent=styles["BodyText"], fontSize=10, leading=14,
    leftIndent=14, spaceAfter=4, textColor=colors.HexColor("#1d3a6b"),
    backColor=colors.HexColor("#eef2fa"),
    borderColor=colors.HexColor("#c2d1e6"),
    borderWidth=0.5, borderPadding=6,
    fontName="Helvetica-Oblique",
))
styles.add(ParagraphStyle(
    name="Warn", parent=styles["BodyText"], fontSize=10, leading=14,
    leftIndent=14, spaceAfter=4, textColor=colors.HexColor("#7a4a00"),
    backColor=colors.HexColor("#fbf3e1"),
    borderColor=colors.HexColor("#e5c98f"),
    borderWidth=0.5, borderPadding=6,
))
styles.add(ParagraphStyle(
    name="Cell", parent=styles["BodyText"], fontSize=9.5, leading=12,
    alignment=TA_LEFT, spaceAfter=0,
))
styles.add(ParagraphStyle(
    name="TimeBox", parent=styles["BodyText"], fontSize=10.5, leading=14,
    alignment=1, textColor=colors.white, fontName="Helvetica-Bold",
))


def P(text, style="BodyDE"):
    return Paragraph(text, styles[style])


def H1(text):
    return Paragraph(text, styles["H1"])


def H2(text):
    return Paragraph(text, styles["H2"])


def cell(text):
    return Paragraph(text, styles["Cell"])


def talk(text):
    return Paragraph(f"&#9656; {text}", styles["Talking"])


def demo(text):
    return Paragraph(f"<b>Demo:</b> {text}", styles["Demo"])


def quote(text):
    return Paragraph(f"&#8220;{text}&#8221;", styles["Quote"])


def warn(text):
    return Paragraph(f"<b>Achtung:</b> {text}", styles["Warn"])


def section_header(num, title, minutes, total_at_end):
    """Großer Block-Header mit Zeitangabe."""
    title_para = Paragraph(
        f"<font size=18 color='#0b3d91'><b>{num}. {title}</b></font>",
        styles["H1"],
    )
    time_para = Paragraph(
        f"{minutes} min &nbsp;&nbsp;|&nbsp;&nbsp; bis Minute {total_at_end}",
        styles["TimeBox"],
    )
    t = Table(
        [[title_para, time_para]],
        colWidths=[12.5 * cm, 4.5 * cm],
        rowHeights=[1.0 * cm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#0b3d91")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


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
                      "EMOS Light — Roadmap Zwischenstands-Präsentation")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Seite {doc.page}")
    canvas.restoreState()


# ----------------------------------------------------------------------
# Cover
# ----------------------------------------------------------------------

def build_cover():
    return [
        Spacer(1, 3 * cm),
        Paragraph("EMOS Light",
                  ParagraphStyle("CovTop", parent=styles["Title"],
                                 fontSize=32, leading=38,
                                 textColor=colors.HexColor("#0b3d91"),
                                 alignment=1)),
        Spacer(1, 0.4 * cm),
        Paragraph("Roadmap für die Zwischenstands-Präsentation",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=18, leading=22,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.5 * cm),
        Paragraph(
            "Speakers-Guide — Schritt für Schritt durch die "
            "Präsentation, mit Talking-Points, Demo-Cues, "
            "Zeitvorgaben und Q&amp;A-Prep.",
            ParagraphStyle("CovSub2", parent=styles["BodyText"],
                           fontSize=12, leading=15,
                           textColor=colors.HexColor("#555"),
                           alignment=1),
        ),
        Spacer(1, 1.2 * cm),

        # Gesamtüberblick als Tabelle
        Paragraph(
            "<b>Gesamtablauf (~30 min + Q&amp;A)</b>",
            ParagraphStyle("OverHead", parent=styles["BodyText"],
                           fontSize=12, alignment=1,
                           textColor=colors.HexColor("#143f7a")),
        ),
        Spacer(1, 0.3 * cm),
        Table(
            [
                ["#", "Block", "Dauer", "kumuliert"],
                ["1", "Begrüßung & Agenda", "1 min", "1"],
                ["2", "Projekt-Kontext & Motivation", "3 min", "4"],
                ["3", "Was ist EMOS Light? (Architektur-Überblick)", "4 min", "8"],
                ["4", "Live-Demo Dashboard", "7 min", "15"],
                ["5", "Mathematischer Kern (MILP)", "5 min", "20"],
                ["6", "Stand der Implementierung & Refactoring", "4 min", "24"],
                ["7", "Ausblick / nächste Schritte", "3 min", "27"],
                ["8", "Diskussion / Q&A", "≥ 5 min", "≥ 32"],
            ],
            colWidths=[1.0 * cm, 9.0 * cm, 2.5 * cm, 2.5 * cm],
        ).setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaa")),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, ROW_ALT]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])) or None,

        PageBreak(),
    ]


# Workaround: setStyle gibt None zurück, daher müssen wir die Tabelle separat erzeugen
def build_cover_clean():
    overview_data = [
        ["#", "Block", "Dauer", "kumuliert"],
        ["1", "Begrüßung & Agenda", "1 min", "1"],
        ["2", "Projekt-Kontext & Motivation", "3 min", "4"],
        ["3", "Was ist EMOS Light? (Architektur-Überblick)", "4 min", "8"],
        ["4", "Live-Demo Dashboard", "7 min", "15"],
        ["5", "Mathematischer Kern (MILP)", "5 min", "20"],
        ["6", "Stand der Implementierung & Refactoring", "4 min", "24"],
        ["7", "Ausblick / nächste Schritte", "3 min", "27"],
        ["8", "Diskussion / Q&A", "≥ 5 min", "≥ 32"],
    ]
    t = Table(overview_data, colWidths=[1.0 * cm, 9.0 * cm, 2.5 * cm, 2.5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaa")),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, ROW_ALT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [
        Spacer(1, 3 * cm),
        Paragraph("EMOS Light",
                  ParagraphStyle("CovTop", parent=styles["Title"],
                                 fontSize=32, leading=38,
                                 textColor=colors.HexColor("#0b3d91"),
                                 alignment=1)),
        Spacer(1, 0.4 * cm),
        Paragraph("Roadmap für die Zwischenstands-Präsentation",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=18, leading=22,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.5 * cm),
        Paragraph(
            "Speakers-Guide — Schritt für Schritt durch die "
            "Präsentation, mit Talking-Points, Demo-Cues, "
            "Zeitvorgaben und Q&amp;A-Prep.",
            ParagraphStyle("CovSub2", parent=styles["BodyText"],
                           fontSize=12, leading=15,
                           textColor=colors.HexColor("#555"),
                           alignment=1),
        ),
        Spacer(1, 1.2 * cm),
        Paragraph(
            "<b>Gesamtablauf (~30 min + Q&amp;A)</b>",
            ParagraphStyle("OverHead", parent=styles["BodyText"],
                           fontSize=12, alignment=1,
                           textColor=colors.HexColor("#143f7a")),
        ),
        Spacer(1, 0.3 * cm),
        t,
        Spacer(1, 1 * cm),
        Paragraph(
            "<b>Legende:</b><br/>"
            "&#9656; = Sprech-Punkt (Talking-Point)<br/>"
            "<font color='#0a6e2e'>Grüner Kasten</font> = Demo-Aktion am Laptop<br/>"
            "<font color='#1d3a6b'>Blauer Kasten</font> = Beispiel-Zitat / Formulierung<br/>"
            "<font color='#7a4a00'>Gelber Kasten</font> = wo du aufpassen solltest",
            ParagraphStyle("Legend", parent=styles["BodyText"],
                           fontSize=10, leading=14,
                           textColor=colors.HexColor("#444"),
                           alignment=1),
        ),
        PageBreak(),
    ]


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------

def sec_1_intro():
    out = []
    out.append(section_header(1, "Begrüßung & Agenda", 1, 1))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Erstes Bild aufbauen — wer du bist, was sie gleich hören "
        "werden, und in welcher Reihenfolge."
    ))
    out.append(H2("Talking-Points"))
    out.append(talk("Begrüßung, kurz vorstellen — Name + Rolle "
                    "(Softwarekoordinator des EMOS-Light-Teams)."))
    out.append(talk("Heute: <b>Zwischenstand</b> — nicht das fertige "
                    "Produkt, sondern was bisher steht und wo es hingeht."))
    out.append(talk("Agenda kurz nennen: Kontext → Architektur → "
                    "Live-Demo → Mathematik → Stand → Ausblick → Fragen."))
    out.append(quote(
        "Vielen Dank, dass ich heute den Zwischenstand von EMOS Light "
        "vorstellen darf. Ich bin Jakob, koordiniere die Software"
        "entwicklung im Team. Ich zeige Ihnen in den nächsten gut "
        "30 Minuten erst das Konzept, dann eine kurze Demo, dann den "
        "mathematischen Kern — und am Ende, wo wir gerade stehen "
        "und wohin wir noch wollen. Im Anschluss freue ich mich auf "
        "Ihre Fragen."
    ))
    out.append(Spacer(1, 0.4 * cm))
    out.append(PageBreak())
    return out


def sec_2_context():
    out = []
    out.append(section_header(2, "Projekt-Kontext & Motivation", 3, 4))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Klarmachen, warum es das Projekt gibt — und warum es relevant ist. "
        "Nicht zu technisch, hier hörst du noch Professoren und Fach-"
        "Fremde gleichzeitig."
    ))
    out.append(H2("Talking-Points"))
    out.append(talk(
        "<b>Energiewende-Kontext:</b> dynamische Strompreise sind "
        "Realität (Tibber, aWATTar, Ostrom). Im Tagesverlauf "
        "Schwankungen von 5 ct bis &gt; 40 ct/kWh — bis hin zu "
        "negativen Preisen."
    ))
    out.append(talk(
        "<b>Gleichzeitig</b>: Wärmepumpe, PV, Batteriespeicher, "
        "Wallbox — diese Komponenten sind alle <b>steuerbar</b>. "
        "Aber Hand-Steuerung ist nicht praktikabel."
    ))
    out.append(talk(
        "<b>Lücke:</b> bezahlbares, transparentes Tool, das die "
        "Steuerung automatisch optimiert. Kommerzielle Systeme sind "
        "Black-Boxes; akademische Modelle nicht für den Heimanwender."
    ))
    out.append(talk(
        "<b>EMOS Light</b> = Energie-Management- und Optimierungs-"
        "System; Light, weil das Vorläuferprojekt EMOS auf ein "
        "konkretes Gebäude zugeschnitten war — Light ist generisch + "
        "konfigurierbar."
    ))
    out.append(talk(
        "<b>Team:</b> 15 Personen, ich koordiniere die "
        "Softwareentwicklung; andere arbeiten an Komponenten-Modellen "
        "(Wärmepumpe, Gebäude, PV-Prognose etc.). Ihre Formeln und "
        "Kennlinien fließen in den Code ein."
    ))
    out.append(H2("Mögliche Quote"))
    out.append(quote(
        "Wer 2026 dynamischen Strom bezieht, kann pro Jahr 200–500 €"
        "sparen — aber nur, wenn die Geräte zur richtigen Zeit laufen. "
        "Genau das ist EMOS Lights Aufgabe."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_3_architecture():
    out = []
    out.append(section_header(3, "Was ist EMOS Light? (Architektur)", 4, 8))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Ohne in Code zu springen: was sind die Bausteine, was kommt "
        "rein, was kommt raus."
    ))
    out.append(H2("Talking-Points"))
    out.append(talk(
        "<b>Eingaben:</b> Strompreise (Day-Ahead), Wetter (für PV), "
        "Verbrauchsprofile, Komfort-Anforderungen, Anlagen-Setup."
    ))
    out.append(talk(
        "<b>Ausgabe:</b> Steuerschema für 24 h — wann läuft die WP, "
        "wann lädt die Batterie, wann das Auto, wann wird PV "
        "eingespeist vs. selbst genutzt."
    ))
    out.append(talk(
        "<b>Komponenten</b> (kurz zeigen, einzelne hervorheben): "
        "PV, Batterie, Wärmepumpe (SG-Ready), Fußbodenheizung mit "
        "Estrich-Speicher, Warmwasserspeicher, Frischwasserstation, "
        "Wallbox, E-Auto, Gebäudemodell."
    ))
    out.append(talk(
        "<b>Sektorenkopplung Strom ↔ Wärme</b>: Wärmepumpe verbindet "
        "die beiden — kann elektrische Überschüsse in Wärme umwandeln "
        "und speichern. <b>Das ist der entscheidende Hebel.</b>"
    ))
    out.append(talk(
        "<b>Wie wird optimiert:</b> mathematisches Modell, gemischt-"
        "ganzzahliges lineares Programm (MILP) — kommt gleich im "
        "Mathe-Block ausführlich. Open-Source-Solver (HiGHS), unter "
        "1 Sekunde Lösungszeit."
    ))
    out.append(talk(
        "<b>UI:</b> Streamlit-Dashboard im Browser, lokal lauffähig. "
        "Konfiguration in YAML, exportierbar / teilbar."
    ))
    out.append(H2("Diagramm zeichnen (optional auf Whiteboard)"))
    out.append(P(
        "Wenn ein Whiteboard verfügbar ist — den Datenfluss als 5 "
        "Kästchen skizzieren: <i>Config → Komponenten → Eingangsdaten "
        "→ Optimierer → Ergebnis</i>. Das hilft beim Verständnis im "
        "nächsten Block (Demo)."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_4_demo():
    out = []
    out.append(section_header(4, "Live-Demo Dashboard", 7, 15))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Das System einmal in echt zeigen. <b>Wichtigster Block der "
        "Präsentation</b> — alles davor und danach gewinnt durch das "
        "konkrete Bild auf dem Bildschirm."
    ))
    out.append(warn(
        "VOR dem Termin: Dashboard schon im Browser geöffnet haben "
        "(Doppelklick auf EMOS_Light_starten.bat). Sicherstellen, "
        "dass eine Beispiel-Optimierung schon einmal durchgelaufen "
        "ist (Cache warm). Browser-Zoom auf 110–125 % für gute "
        "Sichtbarkeit im Saal."
    ))

    out.append(H2("Demo-Ablauf (5 Schritte)"))

    out.append(P("<b>Schritt 1 — Reiter Setup konfigurieren</b> (1 min)"))
    out.append(demo(
        "Expander <b>Standort & Netz</b> öffnen. Auf Koordinaten, "
        "Anschlussleistung, Einspeisevergütung hinweisen — das ist "
        "der lokale Rahmen."
    ))
    out.append(talk(
        "Hier konfiguriert der Nutzer seinen Standort und den"
        "Hausanschluss. Alle Daten kommen aus dem typischen "
        "Energieversorger-Vertrag."
    ))

    out.append(P("<b>Schritt 2 — Komponenten</b> (2 min)"))
    out.append(demo(
        "Expander <b>PV-Anlage & Batterie</b> öffnen. Zeigen: "
        "PV mit Dachflächen (Mehrfacheinträge), Azimut + Neigung. "
        "Batterie mit Kapazität, Wirkungsgrad und Alterungskosten-Block."
    ))
    out.append(talk(
        "Jede Komponente hat eine ‚aktiv‘-Checkbox — das ganze"
        "System ist modular, Komponenten können einzeln zu- oder "
        "abgeschaltet werden. Hier sieht man auch die Alterungskosten "
        "der Batterie als Beispiel für ein Detail-Modell — die "
        "Speicher-Gruppe im Team hat dazu eine eigene Formel erarbeitet, "
        "die ist 1:1 implementiert."
    ))
    out.append(demo(
        "Expander <b>Wärmepumpe & SG-Ready</b> öffnen. Zeigen: "
        "Vorlauftemperatur-Trennung Heizung/WW, SG-Ready-Zustände."
    ))
    out.append(talk(
        "Die Wärmepumpe ist hardware-realistisch modelliert —"
        "Vaillant aroTHERM mit echtem 2D-COP-Kennfeld. Die SG-Ready-"
        "Schnittstelle nach BWP v1.1 ist genau wie in echt: Zustand 1 "
        "ist Lastabwurf, 3 ist verstärkter Betrieb für billigen Strom."
    ))

    out.append(P("<b>Schritt 3 — Gebäude</b> (1 min)"))
    out.append(demo(
        "Expander <b>Fußbodenheizung & Gebäude</b> öffnen. "
        "Auf die <b>Live-Vorschau-Kennzahlen</b> hinweisen: "
        "UA-Wert, τ, t_aus."
    ))
    out.append(talk(
        "Das Gebäude liefert die Heizlast — über U-Werte,"
        "Geometrie und Lüftungsrate. Diese drei Kennzahlen unten "
        "zeigen, wie das Haus wärmetechnisch ‚tickt‘: Zeitkonstante "
        "τ und Ausroll-Zeit t_aus sind die Stellgrößen, die der "
        "Optimierer nutzt, um in teuren Stunden die WP auszusetzen."
    ))

    out.append(P("<b>Schritt 4 — Optimierung starten</b> (1 min)"))
    out.append(demo(
        "Reiter <b>Optimierung</b> öffnen, Knopf <b>Optimierung "
        "starten</b> drücken. Dauer ~1 s."
    ))
    out.append(talk(
        "Der MILP-Solver löst jetzt das gesamte 24-Stunden-Modell"
        "in einer Sekunde — etwa 1.700 Variablen, 580 davon "
        "ganzzahlig. Die mathematische Brille zeige ich Ihnen "
        "gleich nach der Demo."
    ))

    out.append(P("<b>Schritt 5 — Ergebnisse</b> (2 min)"))
    out.append(demo(
        "<b>Plot Elektrische Leistungsbilanz</b> zeigen. Auf den "
        "PV-Block am Mittag zeigen, dann auf die Batterie-Ladezeit "
        "(während PV-Überschuss) und Entladezeit (Abend, hoher Preis)."
    ))
    out.append(demo(
        "<b>Plot Strompreis vs. Verhalten</b> zeigen. Korrelation "
        "auf einen Blick: günstige Stunden = Komponenten laufen."
    ))
    out.append(demo(
        "<b>Kostenvergleich</b> ganz oben: MILP-Optimum vs. Baseline. "
        "Ersparnis in € und % nennen."
    ))
    out.append(talk(
        "Hier sehen Sie das Ergebnis: links der Vergleich zur"
        "naiven Regelung — typisch X € pro Tag, Y % gespart. Im "
        "Plot sehen Sie, wie die Batterie genau dann lädt, wenn die "
        "Sonne scheint oder der Strompreis im Keller ist, und entlädt, "
        "wenn’s teuer wird. Das ist nichts, was ein Hand-Schalter "
        "noch effizient kann."
    ))
    out.append(warn(
        "Falls Demo abstürzt oder Browser hängt: keine Panik, kurz "
        "sagen kommt manchmal vor in der Entwicklungsversion, "
        "neu starten oder direkt zum nächsten Block springen — die "
        "PDFs zeigen das Ergebnis genauso."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_5_math():
    out = []
    out.append(section_header(5, "Mathematischer Kern (MILP)", 5, 20))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Den Professoren zeigen, dass solide Mathematik dahintersteckt. "
        "Genug Tiefe für Glaubwürdigkeit, nicht so viel, dass die "
        "Kommilitonen abschalten."
    ))
    out.append(H2("Talking-Points"))
    out.append(talk(
        "<b>Was wird optimiert?</b> Gesamtkosten über den Horizont — "
        "Summe aus Netzbezugskosten − Einspeise-Erlös + Batterie-"
        "Alterungskosten + Strafkosten für Komfortverletzung."
    ))
    out.append(talk(
        "<b>Wozu MILP?</b> Lineare Constraints + lineare Zielfunktion → "
        "konvexes Problem, global lösbar. Binärvariablen für "
        "Schalt-Entscheidungen (WP an/aus, Batterie laden/entladen, "
        "SG-Ready-Zustände)."
    ))
    out.append(talk(
        "<b>Wichtigste Constraints:</b> Knotenbilanz Strom (Kirchhoff), "
        "SOC-Bilanz Batterie und Speicher, Modulationsbereiche der WP, "
        "Mindestlauf-/Pausenzeiten, Wallbox-Ladegarantie, "
        "Komfort-Mindesttemperaturen."
    ))
    out.append(talk(
        "<b>Knackpunkt:</b> COP der Wärmepumpe wird "
        "<b>vorberechnet</b> aus Außen- und Vorlauftemperatur — "
        "damit bleibt das Problem linear (sonst bilinear → "
        "deutlich teurer zu lösen)."
    ))
    out.append(talk(
        "<b>Lösungsweg:</b> HiGHS (Open Source) löst per Branch-and-"
        "Bound + Schnittebenen. Untere Schranke aus LP-Relaxation, "
        "obere aus heuristisch gefundener Inkumbente. Beweis bei "
        "Gap &lt; 0,01 %."
    ))
    out.append(talk(
        "<b>Größenordnung:</b> 24-h-Horizont, 15-min-Schritte → "
        "~1.700 Variablen, davon ~580 binär. Suchraum theoretisch "
        "10¹⁷⁴, praktisch werden nur einige Tausend Knoten besucht. "
        "Lösungszeit &lt; 1 s auf normalem Laptop."
    ))
    out.append(H2("Wenn jemand warum nicht KI / neuronales Netz?"
                    " fragt"))
    out.append(quote(
        "Für unsere Problemstellung haben wir bewiesen optimale"
        "Lösungen — MILP garantiert das. Ein neuronales Netz "
        "würde eine ‚gute‘ Lösung liefern, aber ohne Optimalitäts-"
        "garantie. Außerdem braucht es Trainingsdaten, die wir bei "
        "den schnell wechselnden Strompreisen nicht haben. Und "
        "die Erklärbarkeit ist bei MILP perfekt — jede Entscheidung "
        "ist auf eine Constraint zurückführbar."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_6_status():
    out = []
    out.append(section_header(6, "Stand der Implementierung & Refactoring",
                              4, 24))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Ehrlich zeigen: was fertig ist, was gerade läuft, was noch "
        "fehlt. Professoren sehen gerne, dass man den Stand "
        "realistisch einschätzt."
    ))

    out.append(H2("Was steht (fertig)"))
    out.append(std_table(
        [cell("<b>Bereich</b>"), cell("<b>Status</b>")],
        [
            [cell("Komponenten-Modelle"),
             cell("Alle 9 Komponenten implementiert, mit realen "
                  "Parametern (aroTHERM-Kennfeld, BWP-SG-Ready, "
                  "DIN-basierte Gebäudewerte)")],
            [cell("MILP-Optimierer + MPC"),
             cell("Day-Ahead-MILP funktioniert, MPC-Schleife läuft, "
                  "Baseline-Vergleich integriert")],
            [cell("Dashboard"),
             cell("Streamlit-UI mit allen Konfigurationsfeldern, "
                  "interaktiven Plots, YAML-Import/-Export")],
            [cell("Datenanbindung"),
             cell("Day-Ahead-Preise (EPEX/SMARD), Wetter (Open-Meteo), "
                  "vier vermessene Lastprofile, eigene CSV-Importe")],
            [cell("PV-Ertragsprognose"),
             cell("Perez-Transposition (Default) und Liu-Jordan "
                  "(isotrop, Vergleich) implementiert")],
            [cell("Refactoring"),
             cell("Erste Stufe abgeschlossen: zwei-stufige Basisklasse, "
                  "MILP-Helfer-Modul, alle Komponenten migriert. "
                  "Code 26 % kürzer, weniger Bug-Oberfläche.")],
        ],
        [4.5 * cm, 12.0 * cm],
    ))

    out.append(H2("Was gerade läuft"))
    out.append(talk(
        "Verfeinerung Gebäudemodell — die Gebäudegruppe arbeitet an "
        "einem 2R2C-Ansatz (Raum- und Hüllknoten getrennt). Wenn das "
        "kommt, wird die Außentemperatur-Sensitivität deutlich besser."
    ))
    out.append(talk(
        "PV-Prognose — Vergleich von Wettermodell-basierter Prognose "
        "und der HTW-Intraday-Methode. Erste Ergebnisse zeigen, dass "
        "ein Hybrid (Wetter + laufende Messwert-Korrektur) bei "
        "Cloud-Enhancement und dichter Bewölkung deutlich besser ist."
    ))

    out.append(H2("Refactoring-Effekt erläutern"))
    out.append(talk(
        "Vor dem Refactoring: jede Komponente hat ihre MILP-Constraints "
        "wörtlich ausgeschrieben — viel Duplikat. Jetzt: zentrale "
        "Helfer (z. B. <font face='Courier'>add_state_balance</font>, "
        "<font face='Courier'>add_on_off_power_link</font>), "
        "Komponenten schreiben Intent statt Boilerplate."
    ))
    out.append(talk(
        "<b>Praktischer Effekt:</b> eine neue Komponente "
        "(z. B. Heizstab, BHKW) lässt sich in 2–4 h statt einem Tag "
        "implementieren."
    ))

    out.append(H2("Was fehlt noch"))
    out.append(talk(
        "Optimizer-Modularisierung (zweite Refactoring-Stufe): "
        "generische Schleife über Komponenten statt 500-Zeilen-Block. "
        "Voraussetzung für saubere Plugin-Erweiterung."
    ))
    out.append(talk(
        "Automatisierte Tests — heute nur durch Live-Lauf validiert. "
        "Smoketests pro Komponente sind nächster Schritt."
    ))
    out.append(talk(
        "Validierung mit Realdaten — wir haben Messdaten aus dem "
        "InfluxDB-Setup. Vergleich Prognose vs. Realität läuft an."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_7_outlook():
    out = []
    out.append(section_header(7, "Ausblick / nächste Schritte", 3, 27))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Ziel"))
    out.append(P(
        "Klare Richtung zeigen — kein und dann mal sehen, sondern "
        "konkrete nächste Meilensteine."
    ))

    out.append(H2("Drei klare nächste Meilensteine"))
    out.append(std_table(
        [cell("<b>Meilenstein</b>"), cell("<b>Wer</b>"), cell("<b>Ziel</b>")],
        [
            [cell("<b>2R2C-Gebäudemodell</b>"),
             cell("Gebäudegruppe + Software"),
             cell("Außentemperatur-Sensitivität verbessern; "
                  "Lüftung und Transmission separat als Constraints")],
            [cell("<b>Hybrid-PV-Prognose</b>"),
             cell("Prognose-Team"),
             cell("Day-Ahead-Wetterprognose + HTW-Intraday-Korrektur "
                  "kombinieren; soll typische Fehler von "
                  "&gt; 100 % bei Bewölkung halbieren")],
            [cell("<b>Optimizer-Refactoring Stufe 2</b>"),
             cell("Software (Jakob)"),
             cell("Generische Komponenten-Schleife; "
                  "dict-basiertes OptimizationResult; "
                  "Plugin-Registry für neue Komponenten")],
            [cell("<b>Validierung gegen Realdaten</b>"),
             cell("Mess-/Validierungs-Team"),
             cell("Optimierer-Ergebnis vs. echte Messung im "
                  "Pilotgebäude, Ersparnis quantifizieren")],
        ],
        [4.5 * cm, 4.0 * cm, 8.0 * cm],
    ))

    out.append(H2("Erweiterte Komponenten — auf der Wunschliste"))
    out.append(talk(
        "Heizstab im WW-Speicher (für Notfälle / sehr billigen Strom). "
        "Ist nach dem Refactoring in unter einem Tag machbar."
    ))
    out.append(talk(
        "BHKW (Mini-Blockheizkraftwerk) — produziert Strom + Wärme "
        "aus Gas. Schöner Anwendungsfall für die Sektorenkopplung. "
        "Etwa 2–3 Tage Aufwand."
    ))
    out.append(talk(
        "Solarthermie als zusätzliche Wärmequelle für den WW-Speicher."
    ))

    out.append(H2("Abschluss-Quote"))
    out.append(quote(
        "Wir haben in den letzten Wochen ein Tool gebaut, das schon"
        "heute den Hauptnutzen liefert — mathematisch fundiert, "
        "physikalisch realistisch parametriert, modular erweiterbar. "
        "Die nächsten Schritte zielen auf bessere Eingangsdaten "
        "(Wetter und Gebäudemodell) und Validierung gegen echte "
        "Messungen. Damit haben wir am Semesterende ein vorzeigbares, "
        "lauffähiges System."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_8_qa():
    out = []
    out.append(section_header(8, "Diskussion / Q&A", "≥ 5", "≥ 32"))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("Vorbereitete Antworten auf Standard-Fragen"))

    qa = [
        ("Wie unterscheidet sich EMOS Light von kommerziellen Lösungen "
         "wie SMA Sunny Home Manager oder Tibber Pulse?",
         "Kommerzielle Systeme sind Black-Boxes mit proprietären "
         "Algorithmen, oft an eine Hardware gebunden. EMOS Light ist "
         "Open Source, hardware-agnostisch, mit bewiesener Optimalität "
         "(MILP). Außerdem konfigurierbar bis ins Detail — was "
         "kommerzielle Systeme nicht erlauben."),

        ("Wie genau ist die Vorhersage? Wetter-Prognosen sind oft "
         "schlecht.",
         "Genau das ist ein Schwerpunkt. Wir vergleichen aktuell "
         "drei Modelle: Perez (anisotrop, Standard), Liu & Jordan "
         "(isotrop, robuster), und HTW Intraday (lernt aus aktuellen "
         "Messwerten). Erste Auswertungen zeigen: bei Cloud-Enhancement "
         "unterschätzen die Wettermodelle um 7–22 %; bei dichter "
         "Bewölkung überschätzen sie um bis zu 190 %. Hybrid-Ansatz "
         "(Day-Ahead Wetter + HTW Intraday-Korrektur) löst beide Fälle."),

        ("Was passiert, wenn die Optimierung infeasible wird, z. B. "
         "weil Komfort nicht zu halten ist?",
         "Wir haben Slack-Variablen mit hohen Strafkosten "
         "(500 ct/kWh) für die Komfort-Constraints. Der Solver "
         "verletzt also Komfort nur, wenn es absolut nötig ist, "
         "und meldet es als KPI im Ergebnis."),

        ("Wie real sind die Komponenten-Modelle?",
         "WP: 2D-Kennfeld der Vaillant aroTHERM plus VWL 105/8.1 A "
         "nach EN 14511, direkt vom Hersteller. SG-Ready: BWP-"
         "Spezifikation v1.1. Pufferspeicher: Zwei-Zonen-Modell nach "
         "oemof-thermal, geometriebasierte Verlustberechnung. Batterie: "
         "Standard-Modell mit Wirkungsgrad + Alterungskostenmodell "
         "(Vollzyklen, Wiederbeschaffungs-Annuität)."),

        ("Wie schnell ist die Optimierung wirklich? Skaliert das für "
         "Mehrtages-Horizonte oder ganze Wochen?",
         "Heute: 24 h, 15 min, ~1.700 Variablen → unter 1 Sekunde. "
         "Wochenweise (672 Zeitschritte) wäre ~12.000 Variablen — "
         "etwa 10–30 s. Das ist für ein Tagesplanungs-Tool kein "
         "Problem. MPC läuft sowieso mit kürzerem Horizont rollierend."),

        ("Warum MILP und nicht heuristische Regelung oder "
         "Reinforcement Learning?",
         "MILP: bewiesen optimale Lösung, erklärbar (jede Entscheidung "
         "auf Constraints zurückführbar), schnell genug. Heuristik: "
         "ist unsere Baseline zum Vergleich — typisch 10–25 % "
         "schlechter. RL: braucht Trainingsdaten, die wir bei "
         "wechselnden Strompreisen nicht stabil haben, und kein "
         "Optimalitätsbeweis."),

        ("Wer kann das Tool nutzen? Open Source?",
         "Ja — GitHub-Repo (öffentlich/teilbar), MIT-kompatible "
         "Abhängigkeiten (PuLP, HiGHS, Streamlit). Lauffähig auf "
         "jedem normalen Laptop — wir nutzen Python, kein "
         "Spezial-Solver mit Lizenz."),

        ("Wie ist die Aufgabenverteilung im 15-Personen-Team?",
         "Mehrere Untergruppen: Komponenten-Modellierer (Wärmepumpe, "
         "Gebäude, Speicher, PV), Datenanbindung, Softwarearchitektur "
         "(meine Rolle), Validierung. Jede Gruppe liefert Formeln "
         "und Spezifikationen — die werden in den Code aufgenommen."),
    ]

    for i, (q, a) in enumerate(qa, 1):
        out.append(Paragraph(
            f"<b>F{i}: {q}</b>",
            ParagraphStyle("Q", parent=styles["BodyText"],
                           fontSize=11, leading=14,
                           textColor=colors.HexColor("#0b3d91"),
                           spaceBefore=6, spaceAfter=2),
        ))
        out.append(Paragraph(
            f"<i>A:</i> {a}",
            ParagraphStyle("A", parent=styles["BodyText"],
                           fontSize=10.5, leading=14,
                           leftIndent=10, spaceAfter=4),
        ))

    out.append(H2("Falls eine Frage zu detailliert wird"))
    out.append(quote(
        "Das ist eine sehr gute Frage, das beantworte ich gerne im"
        "Detail nach der Präsentation — oder wir vereinbaren einen "
        "kurzen Termin. Wir haben dazu auch ausführliche "
        "Dokumentation, die ich Ihnen zukommen lassen kann."
    ))
    out.append(Spacer(1, 0.3 * cm))
    out.append(PageBreak())
    return out


def sec_checklist():
    out = []
    out.append(Paragraph("Anhang: Pre-Flight-Check",
                          styles["Part"]))
    out.append(Spacer(1, 0.2 * cm))
    out.append(H2("30 Minuten vor der Präsentation"))
    out.append(P(
        "Schnell-Checkliste — Stress reduzieren durch "
        "Vorab-Verifikation."
    ))
    checklist = [
        ("Laptop am Strom + Netzkabel oder vollgeladen",
         "Streamlit-Sessions sind speicherintensiv."),
        ("Beamer / Bildschirm getestet, Auflösung passt",
         "Browser-Zoom 110-125 % für gute Sichtbarkeit."),
        ("Dashboard läuft (Doppelklick EMOS_Light_starten.bat)",
         "Port 8502 sollte frei sein — die .bat räumt selbst auf."),
        ("Beispiel-Optimierung schon einmal durchgelaufen",
         "Cache warm, PuLP/HiGHS hat Modell schon gesehen."),
        ("Internet-Verbindung getestet",
         "Falls Live-Daten von API gezogen werden sollen."),
        ("PDFs auf dem Desktop verfügbar",
         "Als Backup, falls Dashboard hängt: "
         "EMOS_Light_MILP_Bericht.pdf, _Codebase_Refactored.pdf, "
         "_Solver.pdf, _GUI_Anleitung.pdf."),
        ("Diese Roadmap-PDF ausgedruckt oder auf 2. Bildschirm",
         "Zum Querlesen während du sprichst."),
        ("Wasser / Glas in Reichweite",
         "Bei 30+ min Vortrag oft vergessen."),
        ("Handy lautlos",
         "Selbsterklärend."),
        ("Erste zwei Sätze laut geübt",
         "Reduziert Aufregung in den ersten 30 Sekunden."),
    ]

    rows = [[cell(f"☐ {item}"), cell(why)] for item, why in checklist]
    out.append(std_table(
        [cell("<b>Punkt</b>"), cell("<b>Warum</b>")],
        rows,
        [9.0 * cm, 8.0 * cm],
    ))

    out.append(H2("Wenn du den Faden verlierst"))
    out.append(P(
        "Tief atmen. Zu dieser Roadmap-PDF schauen — dort steht "
        "der nächste Block mit den ersten Talking-Points. Notfall-"
        "Übergang: <i>Lassen Sie mich kurz zusammenfassen, wo wir"
        "sind: …</i> — gibt dir 5 Sekunden Zeit zum Sortieren."
    ))

    out.append(H2("Wenn der Beamer ausfällt"))
    out.append(P(
        "Die fünf zentralen PDFs sind dein Fallback — du kannst "
        "die Demo dann mit den darin enthaltenen Bildern und "
        "Tabellen verbal nachzeichnen. Schlimmer als ohne Beamer "
        "ist, mit Beamer aber ohne Inhalt zu wirken."
    ))

    out.append(H2("Letzte 30 Sekunden"))
    out.append(P(
        "Vor dem Start kurz innehalten, ein bisschen Lächeln, "
        "Augenkontakt mit zwei bis drei Personen im Publikum. "
        "Das signalisiert Souveränität und stellt eine Verbindung "
        "her, die du den ganzen Vortrag über hältst."
    ))
    out.append(Spacer(1, 0.4 * cm))
    out.append(quote(
        "Du hast das Material, du kennst dein Projekt, dein Team "
        "steht hinter dir. Jetzt geh raus und zeig es."
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
        title="EMOS Light - Roadmap Zwischenstands-Praesentation",
        author="EMOS Light Projektteam",
    )

    story = []
    story += build_cover_clean()
    story += sec_1_intro()
    story += sec_2_context()
    story += sec_3_architecture()
    story += sec_4_demo()
    story += sec_5_math()
    story += sec_6_status()
    story += sec_7_outlook()
    story += sec_8_qa()
    story += sec_checklist()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "EMOS_Light_Praesentation_Roadmap.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
