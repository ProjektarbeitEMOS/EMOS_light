"""Erzeugt eine PDF-Anleitung für die EMOS-Light-GUI.

Listet alle Eingabefelder des Streamlit-Dashboards systematisch auf —
strukturiert nach Sidebar, Setup-Reiter und seinen Expander-Blöcken.
Pro Feld: was es einstellt, Bereich, Default und Auswirkung im Modell.
"""

import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle,
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


def field_table(rows):
    """Standard-Tabelle: Feld | Bereich / Default | Bedeutung."""
    header = [
        cell("<b>Feld</b>"),
        cell("<b>Bereich / Default</b>"),
        cell("<b>Bedeutung</b>"),
    ]
    return std_table(
        header,
        [[cell(name), cell(rng), cell(desc)] for name, rng, desc in rows],
        [4.5 * cm, 3.5 * cm, 9.0 * cm],
    )


# ----------------------------------------------------------------------
# Page header / footer
# ----------------------------------------------------------------------

def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666"))
    canvas.drawString(2 * cm, 1.2 * cm,
                      "EMOS Light — Dashboard-Anleitung")
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
        Paragraph("Dashboard-Anleitung",
                  ParagraphStyle("CovSub", parent=styles["Title"],
                                 fontSize=20, leading=24,
                                 textColor=colors.HexColor("#333"),
                                 alignment=1)),
        Spacer(1, 0.6 * cm),
        Paragraph(
            "Alle Eingabefelder der GUI erklärt — was sie tun, welcher "
            "Wertebereich erlaubt ist, wie sich Änderungen auf das "
            "Optimierungsergebnis auswirken.",
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

    out.append(Paragraph("Vorab", styles["TocPart"]))
    out.append(toc_row("0", "Aufbau des Dashboards", 3))

    out.append(Paragraph("Sidebar (linke Spalte)", styles["TocPart"]))
    out.append(toc_row("1.1", "Konfiguration laden / exportieren", 4))
    out.append(toc_row("1.2", "Optimierungsdatum und Datenquelle", 4))
    out.append(toc_row("1.3", "Lastgang-Import (eigene CSV)", 4))
    out.append(toc_row("1.4", "Optimierungsmodus", 5))

    out.append(Paragraph("Setup konfigurieren — Hauptbereich", styles["TocPart"]))
    out.append(toc_row("2.1", "Standort & Netz", 6))
    out.append(toc_row("2.2", "Dynamischer Stromtarif", 7))
    out.append(toc_row("2.3", "PV-Anlage", 8))
    out.append(toc_row("2.4", "Batteriespeicher", 9))
    out.append(toc_row("2.5", "Wärmepumpe & SG-Ready", 10))
    out.append(toc_row("2.6", "Warmwasserspeicher & Frischwasserstation", 11))
    out.append(toc_row("2.7", "Fußbodenheizung", 13))
    out.append(toc_row("2.8", "Gebäude", 14))
    out.append(toc_row("2.9", "Verbrauch (Lastprofil)", 15))
    out.append(toc_row("2.10", "Wallboxen", 16))
    out.append(toc_row("2.11", "E-Autos", 16))

    out.append(Paragraph("Weitere Reiter", styles["TocPart"]))
    out.append(toc_row("3", "Eingabedaten und Optimierung", 18))

    out.append(PageBreak())
    return out


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------

def sec_intro():
    out = [H1("0. Aufbau des Dashboards")]
    out.append(P(
        "Das EMOS-Light-Dashboard besteht aus zwei Bereichen:"
    ))
    out.append(P(
        "<b>Sidebar (linke Spalte)</b> — fasst die Einstellungen zusammen, "
        "die du typischerweise pro Optimierungslauf änderst: Datum, "
        "Modus, eigene Lastgang-CSV. Außerdem Konfiguration importieren "
        "und exportieren."
    ))
    out.append(P(
        "<b>Hauptbereich</b> mit drei Reitern: <b>Setup konfigurieren</b> "
        "(alle Anlagenparameter), <b>Eingabedaten</b> "
        "(Vorschau der Preise, Wetter, Lastprofile), <b>Optimierung</b> "
        "(Lauf starten und Ergebnisse anschauen)."
    ))
    out.append(P(
        "Diese Anleitung führt durch <b>jedes Eingabefeld</b> in der "
        "gleichen Reihenfolge, wie es im Dashboard erscheint. Sie ist "
        "auch zum Querlesen gedacht — die Inhaltsverzeichnis-Seitenzahlen "
        "verweisen auf die jeweiligen Abschnitte."
    ))
    out.append(H2("Konventionen"))
    out.append(P(
        "<b>Default</b> = Voreinstellung, die das Modell ohne weitere "
        "Anpassung verwendet. <b>Bereich</b> = erlaubtes Wertespektrum "
        "im Feld. <b>Wirkung im Modell</b> = wo dieser Wert in die "
        "Optimierung einfließt."
    ))
    out.append(PageBreak())
    return out


# ----------- Sidebar -----------

def sec_sidebar():
    out = [Paragraph("Sidebar (linke Spalte)", styles["Part"])]

    out.append(H1("1.1 Konfiguration laden / exportieren"))
    out.append(field_table([
        ("YAML-Konfiguration importieren",
         "Datei-Upload",
         "Lädt eine vorher exportierte YAML-Konfig zurück ins Dashboard. "
         "Praktisch um zwischen Setups zu wechseln (z. B. Sommer- vs. "
         "Winter-Setup). Die Datei muss aus dem Export-Knopf "
         "darunter stammen."),
        ("Konfiguration exportieren (.yaml)",
         "Download-Knopf",
         "Speichert die aktuelle Konfiguration als YAML-Datei. "
         "Versionierbar via Git, teilbar mit Team-Mitgliedern."),
    ]))

    out.append(H1("1.2 Optimierungsdatum und Datenquelle"))
    out.append(field_table([
        ("Optimierungsdatum",
         "Default: morgen",
         "Tag, für den das Modell die Steuerung berechnet. Bei MILP "
         "(Day-Ahead) wird das vollständige 24-h-Profil ab Mitternacht "
         "dieses Tages optimiert."),
        ("Echte Daten (API)",
         "Checkbox, Default aus",
         "An: lädt Day-Ahead-Preise von der EPEX/SMARD-API und "
         "Wetterprognose von Open-Meteo. Aus: nutzt synthetische "
         "Daten — gut für Demos und Test, weil reproduzierbar."),
    ]))

    out.append(H1("1.3 Lastgang-Import (eigene CSV)"))
    out.append(P(
        "Optional. Wenn du eine eigene Smart-Meter-CSV mit Zeitreihen "
        "des Stromverbrauchs hochlädst, wird diese statt des vermessenen "
        "Profils verwendet."
    ))
    out.append(field_table([
        ("Strom-Lastgang (CSV)",
         "Datei-Upload",
         "CSV mit Zeitstempel + Leistungs- oder Verbrauchsspalte. "
         "Erlaubt sind 15-, 30-, 60-min-Aufflösungen. Wird automatisch "
         "auf den gewählten Zeitschritt resamplet."),
        ("Lastgang enthält Wärmepumpe",
         "Checkbox, Default aus",
         "Wenn der Smart-Meter den WP-Verbrauch mitmisst, muss er für "
         "die Optimierung wieder abgezogen werden — sonst zählt der "
         "Verbrauch doppelt. An: Modell schätzt den WP-Anteil und "
         "subtrahiert ihn."),
    ]))

    out.append(H1("1.4 Optimierungsmodus"))
    out.append(field_table([
        ("Optimierungsmodus",
         "Radio: Day-Ahead / MPC / Baseline",
         "<b>Day-Ahead (MILP):</b> einmalig über den vollen Horizont "
         "(Default 48 h) optimieren — Referenzlauf mit perfekter "
         "Vorausschau auf die Prognosen.<br/>"
         "<b>MPC (rollierend):</b> mehrere kurze Optimierungen "
         "hintereinander, mit Zustandsübernahme — näher an Realbetrieb.<br/>"
         "<b>Baseline (regelbasiert):</b> kein MILP, sondern naive "
         "Steuerung (PV-Überschuss in Batterie, Hysterese-WP, sofort-"
         "Laden für die Wallbox). Dient als Vergleichswert."),
        ("MPC Ausführungsfenster (h)",
         "1–6, Default 1",
         "Nur sichtbar bei MPC. Wieviele Stunden des Optimierungs"
         "ergebnisses werden tatsächlich übernommen, bevor neu "
         "geplant wird. Kürzer = reaktiver, aber mehr Rechenaufwand."),
    ]))
    out.append(P(
        "<b>Day-Ahead-konformer MPC-Vorhersagehorizont (seit Apr 2026):</b> "
        "Der MPC nutzt keinen festen Vorhersagehorizont mehr — er passt "
        "sich an die EPEX-SPOT-Day-Ahead-Publikation an. <b>Vor 13 Uhr</b> "
        "Ortszeit reicht das Fenster bis Tagesende heute (morgige Preise "
        "noch nicht verfügbar), <b>ab 13 Uhr</b> bis Tagesende morgen. "
        "Hard-Cap: nie über die bereitgestellten Eingangsdaten hinaus "
        "(<font face='Courier'>optimization_horizon_hours</font>, "
        "Default 48 h)."
    ))
    out.append(P(
        "<b>Dynamische Horizont-Anpassung bei Echtdaten (Mai 2026):</b> "
        "Wenn die Checkbox 'Echte Daten (API)' gesetzt ist, prüft EMOS "
        "Light vor dem Lauf, ob die Day-Ahead-Preise für den Folgetag "
        "schon an der EPEX publiziert sind. Falls nicht (typisch vor "
        "13 Uhr), wird der Horizont automatisch von 48 h auf 24 h "
        "verkürzt — es wird nie über einen Zeitraum optimiert, für den "
        "keine echten Marktpreise vorliegen. Ein Info-Banner im "
        "Eingabedaten- und Optimierungs-Tab macht das transparent."
    ))
    out.append(P(
        "<b>Planungshorizont-Panel (Mai 2026):</b> Im Optimierungs-Tab "
        "erscheint nach dem Lauf ein Gantt-ähnliches Panel, das pro "
        "MPC-Iteration einen Balken zeigt — dunkler Teil = "
        "Ausführungsfenster, heller Teil = Planungs-Lookahead. "
        "Vertikale 13:00-Marker (Day-Ahead-Publikation) und "
        "Mitternacht-Marker als Tagesgrenze sind eingezeichnet. "
        "Damit ist auf einen Blick zu sehen, wie weit der MPC in "
        "jeder Iteration vorausschaut."
    ))
    out.append(P(
        "Unter den Modus-Einstellungen sieht man eine Live-Liste der "
        "<b>aktiven Komponenten</b> (+/− pro Komponente) und unten die "
        "Modellgröße (Zeitschritt, Horizont)."
    ))
    out.append(PageBreak())
    return out


# ----------- Setup tab -----------

def sec_standort_netz():
    out = [Paragraph("Setup konfigurieren — Hauptbereich",
                     styles["Part"])]
    out.append(H1("2.1 Standort & Netz"))
    out.append(P(
        "Geographische und elektrische Anschluss-Parameter. Wirken "
        "auf alle wetter- und strompreisabhängigen Größen."
    ))
    out.append(field_table([
        ("Breitengrad",
         "−90 bis 90, Default 49,33°",
         "Geographische Breite des Hauses. Geht in Sonnenstand und "
         "damit in die PV-Ertragsprognose ein."),
        ("Längengrad",
         "−180 bis 180, Default 12,11°",
         "Geographische Länge. Wirkt auf Zeitzone und Sonnenstand "
         "(Default Bayern)."),
        ("Max. Netzleistung (kW)",
         "5–100, Default 25",
         "Hausanschlussgrenze. Beschränkt sowohl Netzbezug als auch "
         "Einspeisung. Bei Überschreitung wird das Modell unzulässig — "
         "sinnvoll auf die echte Anschluss­kapazität setzen "
         "(Standard-EFH 25 kW)."),
        ("Einspeisevergütung (ct/kWh)",
         "0–99, Default 8,2",
         "Erlös pro eingespeister kWh. Aktuelle EEG-Festvergütung "
         "Photovoltaik 2026 etwa 7,9–8,2 ct/kWh. Geht direkt in die "
         "Zielfunktion als negativer Kostenterm ein."),
    ]))
    out.append(PageBreak())
    return out


def sec_tarif():
    out = [H1("2.2 Dynamischer Stromtarif")]
    out.append(P(
        "Hier wird zusammengesetzt, was der Nutzer pro bezogener kWh "
        "real bezahlt: Day-Ahead-Börsenpreis (kommt aus der Preis-API) "
        "plus die folgenden Tarif­komponenten plus Mehrwertsteuer."
    ))
    out.append(field_table([
        ("Anbieter-Vorlage",
         "Tibber / Ostrom / aWATTar / 1KOMMA5 / Benutzerdefiniert",
         "Voreingestellte Werte für typische deutsche Dynamik-"
         "Anbieter. „Benutzerdefiniert“ lässt die Felder unverändert."),
        ("Anbieter-Aufschlag (ct/kWh)",
         "0–10, Default 2,15",
         "Marge des Anbieters auf den Börsenpreis. Tibber ~2,15, "
         "Ostrom 0,0 etc."),
        ("Netzentgelt (ct/kWh)",
         "0–20, Default 9,26",
         "Netznutzungsentgelt — regional unterschiedlich. Steht "
         "auf der letzten Stromrechnung."),
        ("Stromsteuer (ct/kWh)",
         "0–5, Default 2,05",
         "Bundesweit einheitlich (Stand 2026). Wird normalerweise "
         "nicht geändert."),
        ("Konzessionsabgabe (ct/kWh)",
         "0–5, Default 1,66",
         "Kommunale Abgabe — kleinere Kommunen 1,32, größere bis "
         "2,39. Steht auf der Stromrechnung."),
    ]))
    out.append(P(
        "Unten erscheint live die Summe der Aufschläge netto + brutto "
        "(inkl. 19 % MwSt.). Diese Aufschläge werden zum stündlich "
        "schwankenden Börsenpreis addiert, um den effektiven "
        "Endpreis π<sub>t</sub> für die Optimierung zu erhalten."
    ))
    out.append(PageBreak())
    return out


def sec_pv_battery():
    out = [H1("2.3 PV-Anlage")]
    out.append(P(
        "Im Block <b>PV-Anlage & Batterie</b>, linke Spalte. "
        "Du kannst mehrere Dachflächen mit unterschiedlicher Größe, "
        "Ausrichtung und Neigung anlegen."
    ))
    out.append(field_table([
        ("PV aktiviert",
         "Checkbox",
         "Komponente ein-/ausschalten. Aus = keine PV-Erzeugung im Modell."),
        ("Name (pro Fläche)",
         "Text",
         "Frei wählbar — z. B. „Süddach“, „Nordseite Garage“."),
        ("Leistung (kWp)",
         "0,1–100, Default 5,0",
         "Modul-Peakleistung dieser Teilfläche. Summe aller Flächen "
         "wird unten angezeigt."),
        ("Azimut",
         "0–360°, Default 180 (Süd)",
         "Ausrichtung: 0/360 = Nord, 90 = Ost, 180 = Süd, 270 = West."),
        ("Neigung",
         "0–90°, Default 30",
         "Modulneigung gegen Horizontale. Steildach 35–45°, "
         "Flachdach mit Aufständerung 10–15°."),
        ("+ PV-Fläche hinzufügen",
         "Knopf",
         "Fügt eine weitere Dachfläche an die Liste. Praktisch für "
         "Ost-West-Anlagen mit zwei separaten Strings."),
        ("Transpositionsmodell GHI → POA",
         "Perez / Liu&Jordan, Default Perez",
         "Wie wird die Horizontalstrahlung auf die geneigte Modulfläche "
         "umgerechnet? Perez berücksichtigt Zirkumsolar- und Horizont-"
         "Helligkeit (genauer); Liu & Jordan nimmt isotrope Diffusion "
         "(robuster, leicht zu niedrig). Default Perez ist Standard."),
    ]))

    out.append(H1("2.4 Batteriespeicher"))
    out.append(P(
        "Im selben Expander, rechte Spalte. Standard-Heimspeicher mit "
        "Lade-/Entlade-Wirkungsgrad und Zyklen-Alterungsmodell."
    ))
    out.append(field_table([
        ("Batterie aktiviert",
         "Checkbox",
         "Komponente ein-/ausschalten."),
        ("Kapazität (kWh)",
         "1–200, Default 10",
         "Brutto-Speicherkapazität. Typisch EFH: 5–15 kWh."),
        ("Max. Ladeleistung (kW)",
         "0,5–50, Default 5",
         "Maximale AC-Ladeleistung. Beschränkt, wie schnell der "
         "Speicher gefüllt werden kann."),
        ("Max. Entladeleistung (kW)",
         "0,5–50, Default 5",
         "Maximale AC-Entladeleistung."),
        ("SOC-Bereich (%)",
         "Slider 0–100, Default 10–90",
         "Erlaubter Ladezustand. 10–90 schont den Akku; 0–100 holt "
         "mehr Kapazität raus, kostet aber Lebensdauer. Außerhalb "
         "dieses Bereichs darf der Solver nicht laden/entladen."),
        ("Start-SOC (%)",
         "Slider innerhalb SOC-Bereich, Default 50 %",
         "Ladezustand zu Beginn der Optimierung (t = 0)."),
    ]))
    out.append(H2("Alterungskosten (Zyklus-Verschleiß)"))
    out.append(P(
        "Damit der Optimierer nicht „Cycling-Sucht“ entwickelt (jede "
        "0,1-ct-Preisdifferenz ausnutzt), werden Verschleißkosten in "
        "die Zielfunktion aufgenommen."
    ))
    out.append(field_table([
        ("Alterungskosten berücksichtigen",
         "Checkbox, Default an",
         "Schaltet den Verschleißterm in der Zielfunktion an/aus."),
        ("Wiederbeschaffungswert (EUR/kWh)",
         "100–1500, Default 500",
         "Was ein neuer Speicher heute pro kWh kostet. Heimspeicher "
         "2026 typisch 400–700 €/kWh."),
        ("Äquivalent-Vollzyklen bis EOL",
         "1000–15000, Default 6000",
         "Wie viele Vollzyklen der Hersteller garantiert, bis nur "
         "noch 80 % der Kapazität verfügbar sind. LFP-Speicher 6000–"
         "10000, NMC 3000–5000."),
        ("Restwert am Lebensende (0–1)",
         "0–0,5, Default 0",
         "Anteil des Kaufpreises, der nach EOL noch erlös­bar ist "
         "(z. B. 0,1 = 10 %). Üblich 0."),
    ]))
    out.append(P(
        "Unten erscheint live die spezifische Alterungskosten in ct/kWh "
        "Durchsatz — das ist die Hürde, die eine Lade-Entlade-Differenz "
        "übersteigen muss, damit sie sich überhaupt lohnt."
    ))
    out.append(PageBreak())
    return out


def sec_heatpump():
    out = [H1("2.5 Wärmepumpe & SG-Ready")]
    out.append(P(
        "Modelliert ist eine Vaillant aroTHERM plus VWL 105/8.1 A "
        "(Luft-Wasser-WP) mit realem 2D-COP-Kennfeld nach EN 14511."
    ))
    out.append(field_table([
        ("WP aktiviert",
         "Checkbox",
         "Komponente ein-/ausschalten."),
        ("Max. el. Leistung (kW)",
         "1–30, Default 3,7",
         "Elektrische Aufnahmeleistung bei Volllast. Begrenzt, wie "
         "viel Wärme in einer Stunde maximal erzeugt werden kann."),
        ("Min. el. Leistung (kW)",
         "0,5–5, Default 1,0",
         "Modulationsuntergrenze. Wenn die WP an ist, läuft sie "
         "mindestens auf dieser Leistung — darunter taktet sie."),
        ("VL-Temp Heizkreis (°C)",
         "25–55, Default 35",
         "Vorlauftemperatur für die Fußbodenheizung. Bestimmt den "
         "COP der Heizung (niedriger = besser, weil näher an "
         "Außentemperatur). Bei FBH typisch 30–40 °C."),
        ("VL-Temp Warmwasser (°C)",
         "45–70, Default 55",
         "Vorlauftemperatur für die Warmwasserbereitung. Höher = "
         "schlechterer COP, aber nötig für Komfort und Hygiene "
         "(Legionellenschutz typisch ≥ 60 °C einmal/Tag)."),
        ("Max. Einschaltvorgänge pro Tag",
         "0–48, Default 8",
         "Verdichter-Schonung: jedes OFF→ON belastet die WP "
         "mechanisch. Umschalten zwischen Heizkreis und WW zählt "
         "<b>nicht</b>, solange die WP an bleibt — nur das echte "
         "OFF→ON. 0 = kein Limit. Im Dashboard zeigt eine eigene "
         "Kennzahl pro Tag, wie viele Starts verbraucht wurden."),
    ]))
    out.append(H2("SG-Ready (BWP v1.1) — vier Zustände, einziger Steuerkanal"))
    out.append(P(
        "Seit Mai 2026 ist SG-Ready die <b>einzige</b> Schaltlogik der "
        "WP (statt zusätzlich neben einem freien EIN/AUS-Schalter zu "
        "stehen). Pro Zeitschritt ist genau einer der vier Zustände "
        "aktiv:"
    ))
    out.append(P(
        "<b>Zustand 1</b> (Zwangsabschaltung): WP ist hart aus — z. B. "
        "EVU-Sperre oder § 14a EnWG.<br/>"
        "<b>Zustand 2</b> (Normalbetrieb): WP läuft regulär.<br/>"
        "<b>Zustand 3</b> (Einschaltempfehlung): WW-Sollwert wird "
        "angehoben — günstige Strompreise gezielt nutzen.<br/>"
        "<b>Zustand 4</b> (Zwangseinschaltung): zusätzlich auch der "
        "Estrich-Pufferspeicher wird angehoben — maximale "
        "Energie­einlagerung in Niedrigpreiszeiten."
    ))
    out.append(field_table([
        ("SG-Ready aktiviert",
         "Checkbox, Default an",
         "Wenn aus: nur Zustand 2 (kein Lastabwurf, kein verstärkter "
         "Betrieb möglich)."),
        ("Zustand 1: Max. Leistung (kW)",
         "0–10, Default 0",
         "Hard-Cap während Lastabwurf. 0 = komplette EVU-Sperre; "
         ">0 = Leistungsbegrenzung (z. B. § 14a 4,2 kW)."),
        ("Zustand 3: Temp-Erhöhung WW (K)",
         "0–15, Default 5",
         "Um wie viel Kelvin der WW-Speicher in SG3 über seinen "
         "regulären Maximalwert geheizt werden darf. 5 K ≈ "
         "+15 % Speicherkapazität."),
        ("Zustand 4: Temp-Erhöhung WW + Estrich (K)",
         "0–20, Default 10 (muss ≥ SG3)",
         "In SG4 wird sowohl der WW-Speicher als auch der "
         "Estrich-Pufferspeicher um diesen Wert angehoben. "
         "Erlaubt die volle Day-Ahead-Speicherbewirtschaftung."),
        ("Min. Haltezeit SG-Zustand (min)",
         "0–60, Default 10",
         "Verhindert schnelles Umschalten zwischen SG-Zuständen. "
         "Hardware-Schutz."),
    ]))
    out.append(PageBreak())
    return out


def sec_ww_fws():
    out = [H1("2.6 Warmwasserspeicher & Frischwasserstation")]

    out.append(H2("Warmwasserspeicher (linke Spalte)"))
    out.append(P(
        "Zwei-Zonen-Schichtenspeicher mit geometriebasierter "
        "Verlustberechnung."
    ))
    out.append(field_table([
        ("WW-Speicher aktiviert",
         "Checkbox",
         "Komponente ein-/ausschalten."),
        ("Volumen (L)",
         "50–2000, Default 500",
         "Brutto-Speichervolumen in Litern. EFH typisch 300–500 L; "
         "größere Haushalte 500–1000 L."),
        ("Temp.-Bereich (°C)",
         "Slider 30–90, Default 30–65",
         "Minimal- und Maximaltemperatur des Speichers. Unter "
         "Mindesttemp. darf der Solver nie fallen; bis Max. darf er "
         "laden. Spanne = nutzbare Kapazität."),
        ("Komforttemperatur (°C)",
         "Default 55",
         "Mindesttemperatur während definierter Komfort-Zeiten "
         "(z. B. morgens, abends). Höher als die normale Mindesttemp."),
    ]))
    out.append(H3("Komfort-Zeiträume"))
    out.append(P(
        "Liste von Zeitfenstern, in denen die Komforttemperatur "
        "gilt — typisch 5–9 Uhr (morgens duschen) und 17–22 Uhr "
        "(abends). Außerhalb dieser Zeiten reicht die niedrigere "
        "Mindesttemperatur."
    ))
    out.append(field_table([
        ("Von (Uhr) / Bis (Uhr)",
         "0–24",
         "Stundenbereich des Komfortfensters. Mehrere Fenster pro "
         "Tag möglich (Frühschicht + Abendschicht)."),
        ("X (entfernen)",
         "Checkbox",
         "Fenster löschen."),
        ("+ Zeitraum hinzufügen",
         "Knopf",
         "Neues Komfortfenster anlegen (Default 12–14)."),
    ]))

    out.append(H2("Frischwasserstation (rechte Spalte)"))
    out.append(P(
        "Plattenwärmetauscher, der Trinkwasser im Durchlauf aus dem "
        "Pufferspeicher erwärmt. Kein eigener Tank, daher kein stehendes "
        "Warmwasser = inhärenter Legionellenschutz."
    ))
    out.append(field_table([
        ("FWS aktiviert",
         "Checkbox",
         "Komponente ein-/ausschalten."),
        ("Ziel-Warmwassertemp. (°C)",
         "40–60, Default 50",
         "Temperatur, mit der das Trinkwasser am Hahn ankommen soll."),
        ("WT-Wirkungsgrad",
         "0,70–0,98, Default 0,90",
         "Wirkungsgrad des Plattenwärmetauschers. Reale Geräte "
         "0,85–0,95. Schlechter Wirkungsgrad = mehr Wärme muss "
         "dem Speicher entnommen werden, um die gleiche Trinkwasser-"
         "Menge zu erwärmen."),
        ("Min. Speichertemp. für WW (°C)",
         "45–70, Default 55",
         "Mindesttemperatur, die der Pufferspeicher haben muss, damit "
         "der Wärmetauscher die Zieltemperatur am Hahn erreicht. "
         "Faustregel: Ziel + 5 K Grädigkeit. Wirkt als untere Schranke "
         "auf die WW-Speicherenergie."),
    ]))
    out.append(PageBreak())
    return out


def sec_ufh():
    out = [H1("2.7 Fußbodenheizung")]
    out.append(P(
        "Linke Spalte im Expander <b>Fußbodenheizung & Gebäude</b>. "
        "Der Estrich ist im Modell der einzige Wärmespeicher für "
        "die Raumheizung."
    ))
    out.append(field_table([
        ("FBH aktiviert",
         "Checkbox",
         "Komponente ein-/ausschalten."),
        ("Beheizte Fläche (m²)",
         "30–500, Default 150",
         "Wohnfläche, die per FBH beheizt wird. Bestimmt die Estrich-"
         "Masse (Fläche × Dicke × Dichte) und damit die thermische "
         "Speicherfähigkeit."),
        ("Estrichdicke (cm)",
         "3–12, Default 6 cm",
         "Stärke des Estrichs. Mehr Estrich = mehr Speicher = mehr "
         "Spielraum für die Optimierung, in günstigen Stunden "
         "vorzuheizen."),
        ("Komfort-Temperaturband (°C)",
         "Slider 18–30, Default 20–26",
         "Erlaubter Bereich der Bodentemperatur. Im Modell darf "
         "der Estrich nicht unter Untergrenze fallen (Komfort) "
         "und nicht über Obergrenze steigen (Material­schutz, "
         "VDI 6035 max. 29 °C). Spanne = nutzbare Speicherenergie."),
    ]))
    out.append(P(
        "Live-Anzeige unten: Estrich-Wärmekapazität in kWh/K, nutzbarer "
        "Speicher in kWh (typisch 30–50 kWh für 150 m² EFH). "
        "<b>Seit Mai 2026:</b> Mit aktivem Gebäude (§2.8) wird der "
        "Wärmestrom Estrich → Raum als eigene MILP-Variable "
        "<font face='Courier'>q_floor_to_room</font> geführt — keine "
        "implizite Verlustrate mehr. Ohne Gebäude fällt das Modell auf "
        "die alte Verlustraten-Bilanz zurück."
    ))
    out.append(PageBreak())
    return out


def sec_building():
    out = [H1("2.8 Gebäude")]
    out.append(P(
        "Rechte Spalte im Expander <b>Fußbodenheizung & Gebäude</b>. "
        "Bestimmt den Heizwärmebedarf <b>und die thermische Trägheit "
        "der Gebäudehülle</b>: seit Mai 2026 ist die Raumlufttemperatur "
        "<font face='Courier'>T_innen</font> eine eigene MILP-Zustands"
        "variable mit Komfortband-Slacks (Soft-Constraint, "
        "Penalty 500 ct/kWh)."
    ))
    out.append(field_table([
        ("Gebäudestandard",
         "Neubau EnEV (50) / KfW55 (35) / KfW40 (25) / Passivhaus (15)",
         "Spezifischer Heizwärmebedarf in kWh/(m²·a). Wird mit der "
         "beheizten Fläche multipliziert, um den Jahres-Heizenergiebedarf "
         "zu erhalten."),
        ("Beheizte Fläche (m²)",
         "30–500, Default 150",
         "Wohnfläche. Skaliert Jahresheizbedarf und ist Grundlage für "
         "die abgeleitete Grundfläche, wenn Länge/Breite nicht "
         "explizit gesetzt sind."),
        ("Bewohner",
         "1–10, Default 4",
         "Personenzahl. Bestimmt den Warmwasserbedarf mit "
         "2 kWh/Person/Tag."),
    ]))
    out.append(H2("Geometrie"))
    out.append(field_table([
        ("Länge l (m)",
         "5–50, Default 15",
         "Gebäude-Außenmaß Länge. Default oder Wurzel(Fläche) wenn "
         "nicht explizit gesetzt."),
        ("Breite b (m)",
         "5–50, Default 10",
         "Gebäude-Außenmaß Breite."),
        ("Höhe h (m)",
         "2–15, Default 2,5",
         "Raumhöhe eines Stockwerks (oder Gesamthöhe bei einstöckig). "
         "Geht in Wandfläche und Volumen (Lüftungsverluste) ein."),
        ("Fensterfläche A_F (m²)",
         "0–500, Default 15 % der Bruttowandfläche",
         "Gesamte Fensterfläche. Wird von der Wand abgezogen und "
         "separat mit höherem U-Wert gerechnet."),
    ]))
    out.append(H2("U-Werte (Wärmedurchgangskoeffizienten)"))
    out.append(field_table([
        ("U Wand W/(m²K)",
         "0,05–2,0, Default 0,2",
         "Wärmeverlust durch Außenwand pro m² und K. "
         "KfW55 ≈ 0,2; Bestand ohne Dämmung 1,2–1,5."),
        ("U Fenster W/(m²K)",
         "0,5–5,0, Default 0,9",
         "Verglasung. 3-fach modern 0,8–1,0; alt 2-fach 1,4–1,8."),
        ("U Dach+Boden W/(m²K)",
         "0,1–2,0, Default 0,4",
         "Mittelwert Dach + Bodenplatte. Dach typisch 0,15, Boden "
         "zum Erdreich 0,3–0,5."),
    ]))
    out.append(H2("Temperaturen und Komfortband"))
    out.append(field_table([
        ("Referenztemperatur T_ref (°C)",
         "15–25, Default 22",
         "Bezugstemperatur für die gespeicherte Wärme Q_Gebäude. "
         "Energie über T_ref wird als Speicherreserve gerechnet."),
        ("Komfort-Untergrenze T_min (°C)",
         "14–22, Default 21",
         "Untergrenze des T_innen-Komfortbands. Unterschreitung wird "
         "über die Slack-Variable <font face='Courier'>"
         "t_innen_slack_low</font> in der Zielfunktion mit "
         "<b>500 ct/kWh</b> bestraft (Soft-Constraint). Geht zusätzlich "
         "in die Ausroll-Zeit t_aus ein (Diagnose-Anzeige)."),
        ("Komfort-Obergrenze T_max (°C)",
         "T_min+1 bis 30, Default T_min+3",
         "Obergrenze des T_innen-Komfortbands. Überschreitung wird "
         "analog mit <font face='Courier'>t_innen_slack_high</font> "
         "bestraft (verhindert Überheizen bei billigem Strom)."),
    ]))
    out.append(P(
        "Live-Anzeige unten: Transmissions- und Lüftungsverluste in "
        "W/K, Estrich-Wärmekapazität in kWh/K, sowie Zeitkonstante τ "
        "und Ausroll-Zeit t_aus für drei Beispieltemperaturen "
        "(−10 °C, 0 °C, 10 °C außen)."
    ))
    out.append(PageBreak())
    return out


def sec_consumption():
    out = [H1("2.9 Verbrauch (Lastprofil)")]
    out.append(P(
        "Setzt den Haushaltsstromverbrauch — getrennt vom Wärmepumpen­"
        "verbrauch, der intern aus dem Heizbedarf gerechnet wird."
    ))
    out.append(field_table([
        ("Personenanzahl (Lastprofil)",
         "Dropdown: 1 Person / 2 Personen / 2P+1K / 2P+2K",
         "Wählt eines von vier vermessenen Jahresprofilen (15-min-"
         "Auflösung, ohne WP-Anteil). Bestimmt das Tagesmuster — "
         "wann typischerweise viel Last anliegt."),
        ("Jahresstromverbrauch (kWh)",
         "500–50000, Default 4500",
         "Zielwert. Das gewählte Profil wird linear auf diesen "
         "Verbrauch hoch-/runterskaliert. Original-Werte: 1P 2287, "
         "2P 3304, 2P+1K 3929, 2P+2K 4308 kWh/a."),
        ("Skalierungsfaktor",
         "Anzeige",
         "Verhältnis Zielwert / Profil-Original. Zeigt, wie weit "
         "der Pegel vom vermessenen Referenzhaushalt abweicht."),
    ]))
    out.append(P(
        "Darunter zwei Anzeigen <b>Heizwärme</b> und <b>Warmwasser</b> "
        "(kWh/a) — werden automatisch aus Gebäudestandard und "
        "Bewohnerzahl berechnet, hier nicht direkt änderbar."
    ))
    out.append(PageBreak())
    return out


def sec_emob():
    out = [H1("2.10 Wallboxen")]
    out.append(P(
        "Linke Spalte im Expander <b>E-Mobilität</b>. Mehrere Wallboxen "
        "(z. B. Carport links + rechts) sind möglich — jede mit "
        "eigenen Parametern."
    ))
    out.append(field_table([
        ("Wallbox aktiviert",
         "Checkbox",
         "Pro Wallbox einzeln. Aus = wird nicht ins Modell aufgenommen."),
        ("Name",
         "Text",
         "Frei wählbar — z. B. „Carport links“, „Garage“."),
        ("Max. Ladeleistung (kW)",
         "1,4–22, Default 11",
         "Hard-Cap der Wallbox. 11 kW = 3-phasig 16 A, "
         "22 kW = 3-phasig 32 A. Einphasig max. 3,7 kW."),
        ("+ Wallbox hinzufügen / Wallbox entfernen",
         "Knöpfe",
         "Liste erweitern oder einkürzen."),
    ]))

    out.append(H1("2.11 E-Autos"))
    out.append(P(
        "Rechte Spalte. Pro Auto Akku, Anwesenheit und Ladestrategie. "
        "Jedes Auto wird einer aktivierten Wallbox zugeordnet."
    ))
    out.append(field_table([
        ("E-Auto aktiviert",
         "Checkbox",
         "Pro Fahrzeug einzeln."),
        ("Name",
         "Text",
         "Frei wählbar — z. B. „ID.3 Lisa“."),
        ("Akkukapazität (kWh)",
         "10–200, Default 58",
         "Nutzbare Batteriekapazität. Realistische Werte: Kleinwagen "
         "30–45, Kompakt 50–75, Mittelklasse 75–100, Premium 100+."),
        ("Aktueller SOC (%)",
         "0–100, Default 30 %",
         "Ladezustand bei Ankunft. Bestimmt zusammen mit Ziel-SOC die "
         "geforderte Lademenge."),
        ("Verbrauch (kWh/100km)",
         "5–40, Default 16",
         "Realer Fahrverbrauch inkl. Ladeverluste. Kleinwagen ~14, "
         "Kompakt ~16, Mittelklasse ~18, SUV ~21, Transporter ~25."),
    ]))
    out.append(H2("Mindestreichweite (garantiertes Ladeziel)"))
    out.append(field_table([
        ("Mindestreichweite garantieren",
         "Checkbox, Default an",
         "An: das Modell stellt sicher, dass das Fahrzeug bis zur "
         "Abfahrt mindestens die angegebene Reichweite hat. Setzt "
         "voraus, dass Wallbox und Fahrzeug den SOC kommunizieren "
         "(z. B. via ISO 15118). Aus: keine Garantie, nur Lade-"
         "Empfehlung über das Strompreis-Perzentil unten."),
        ("Mindestreichweite (km)",
         "0–500, Default 150",
         "Garantierte Reichweite zur Abfahrtszeit. Wird über "
         "Verbrauch und Akkukapazität in den Ziel-SOC umgerechnet "
         "(unten als „Ziel-SOC“ angezeigt)."),
        ("Ankunft (h)",
         "0–24, Default 17",
         "Stunde, ab der das Auto an der Wallbox steht."),
        ("Abfahrt (h)",
         "0–24, Default 7",
         "Stunde, zu der das Auto die Wallbox verlässt. Über Nacht-"
         "Szenario (Ankunft 17, Abfahrt 7) wird automatisch erkannt."),
        ("Wallbox (Zuordnung)",
         "Dropdown aktivierter Wallboxen",
         "Welche Wallbox lädt dieses Auto? Wechseln möglich, falls "
         "mehrere vorhanden."),
    ]))
    out.append(H2("Preisgesteuerte Ladestrategie"))
    out.append(field_table([
        ("Strompreis-Perzentil zum Laden (%)",
         "Slider 10–100, Default 100",
         "Erlaubt das Laden nur in den günstigsten X % der "
         "Anwesenheitsstunden des Fahrzeugs. 100 % = keine "
         "Beschränkung. 25 % = nur in den günstigsten 25 % der "
         "Stunden, die das Auto an der Wallbox steht. Bezugsgröße "
         "sind die Anwesenheitsstunden, nicht der ganze Tag — so "
         "sind immer Lade-Slots verfügbar."),
    ]))
    out.append(P(
        "Wenn Mindestreichweite an + Perzentil < 100 sind beide "
        "Strategien aktiv: Slots werden vorzugsweise im günstigen "
        "Perzentil belegt, aber wenn die Reichweite sonst nicht "
        "garantiert ist, wird auch in teureren Slots geladen."
    ))
    out.append(PageBreak())
    return out


def sec_other_tabs():
    out = [H1("3. Eingabedaten und Optimierung")]

    out.append(H2("Reiter: Eingabedaten"))
    out.append(P(
        "Kein Eingabebereich — reine Vorschau der Daten, die das Modell "
        "für den gewählten Tag verwendet. Drei Sektionen:"
    ))
    out.append(P(
        "<b>Strompreise:</b> Day-Ahead-Börsenpreis + Tarifkomponenten "
        "über den Tag, plus die Summe als effektiver Endpreis π<sub>t</sub>.<br/>"
        "<b>Wetter & PV-Prognose:</b> Globalstrahlung, Außentemperatur, "
        "berechneter PV-Ertrag.<br/>"
        "<b>Verbrauchsprofile:</b> Haushalts-Last, Heizbedarf, "
        "Warmwasserbedarf."
    ))
    out.append(P(
        "Hier kontrollierst du, ob die Eingangsdaten plausibel aussehen, "
        "bevor du optimierst."
    ))

    out.append(H2("Reiter: Optimierung"))
    out.append(P(
        "Hier startest du den Lauf und siehst die Ergebnisse."
    ))
    out.append(field_table([
        ("Optimierung starten",
         "Knopf",
         "Löst das MILP-Problem mit HiGHS (typisch < 1 s) oder führt "
         "MPC / Baseline aus."),
    ]))
    out.append(P(
        "Nach dem Lauf erscheinen mehrere Ergebnis-Sektionen:"
    ))
    out.append(P(
        "<b>Kostenvergleich</b> — MILP-Optimum vs. Baseline mit "
        "Ersparnis in € und %.<br/>"
        "<b>Elektrische Leistungsbilanz</b> — gestapeltes Plot über "
        "den Tag: PV / Netzbezug / Batterie / Wallbox / Last.<br/>"
        "<b>Thermische Übersicht</b> — gestapelte Subplots: "
        "<b>Raumtemperatur</b> T_innen mit Komfortband (seit Mai 2026), "
        "<b>Estrich-Temperatur</b>, <b>WW-Speichertemperatur</b>, plus "
        "Wärmestrom-Plot mit Q FBH (WP → Estrich), Q WW (WP → Speicher), "
        "Q Estrich → Raum und Q Verlust (Raum → Außen).<br/>"
        "<b>SG-Ready-Zustand</b> (falls aktiv) — wann hat der Optimierer "
        "welchen SG-Zustand vorgeschlagen.<br/>"
        "<b>Strompreis vs. Verhalten</b> — visuelle Korrelation: laden "
        "die Komponenten wirklich in den günstigen Stunden?"
    ))
    out.append(P(
        "Alle Plots sind interaktive Plotly-Charts (zoom, hover, "
        "PNG-Export per Hover-Toolbar)."
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
        title="EMOS Light - Dashboard-Anleitung",
        author="EMOS Light Projektteam",
    )

    story = []
    story += build_cover()
    story += build_toc()
    story += sec_intro()
    story += sec_sidebar()
    story += sec_standort_netz()
    story += sec_tarif()
    story += sec_pv_battery()
    story += sec_heatpump()
    story += sec_ww_fws()
    story += sec_ufh()
    story += sec_building()
    story += sec_consumption()
    story += sec_emob()
    story += sec_other_tabs()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "EMOS_Light_GUI_Anleitung.pdf"
    out_abs = os.path.abspath(out)
    build_pdf(out_abs)
    print(f"PDF geschrieben: {out_abs}")
