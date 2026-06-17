"""Erzeugt eine PDF zur Recherche Leistungspreis Industrie vs. Privat.

Bewusst schlichter Stil — Serif-Schrift, kein Farbschema, wenig Tabellen,
viel Fliesstext.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


def build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {}
    styles["Title"] = ParagraphStyle(
        "Title", parent=base["Title"],
        fontName="Times-Bold", fontSize=18, leading=22,
        textColor=colors.black, alignment=0, spaceAfter=4,
    )
    styles["Subtitle"] = ParagraphStyle(
        "Subtitle", parent=base["Normal"],
        fontName="Times-Italic", fontSize=11, leading=14,
        textColor=colors.HexColor("#555555"), spaceAfter=18,
    )
    styles["H1"] = ParagraphStyle(
        "H1", parent=base["Heading1"],
        fontName="Times-Bold", fontSize=13, leading=16,
        textColor=colors.black,
        spaceBefore=14, spaceAfter=6,
    )
    styles["H2"] = ParagraphStyle(
        "H2", parent=base["Heading2"],
        fontName="Times-Bold", fontSize=11, leading=14,
        textColor=colors.black,
        spaceBefore=10, spaceAfter=4,
    )
    styles["Body"] = ParagraphStyle(
        "Body", parent=base["BodyText"],
        fontName="Times-Roman", fontSize=11, leading=15,
        textColor=colors.black, spaceAfter=6,
        alignment=4,  # justify
        firstLineIndent=0,
    )
    styles["Mono"] = ParagraphStyle(
        "Mono", parent=base["Code"],
        fontName="Courier", fontSize=9.5, leading=12,
        textColor=colors.HexColor("#333333"), spaceAfter=8,
        leftIndent=14,
    )
    styles["Caption"] = ParagraphStyle(
        "Caption", parent=base["Italic"],
        fontName="Times-Italic", fontSize=9.5, leading=12,
        textColor=colors.HexColor("#555555"), spaceAfter=8,
    )
    return styles


def thin_rule() -> HRFlowable:
    return HRFlowable(
        width="100%", thickness=0.4,
        color=colors.HexColor("#999999"),
        spaceBefore=6, spaceAfter=8,
    )


def build_story(styles) -> list:
    s = styles
    story = []

    # --- Titel ---
    story.append(Paragraph(
        "Flexibler Strompreis — Industrie vs. Privat",
        s["Title"],
    ))
    story.append(Paragraph(
        "Notizen zur Recherche · Schwerpunkt Leistungspreis und Modellierung",
        s["Subtitle"],
    ))
    story.append(thin_rule())

    # --- Einleitung ---
    story.append(Paragraph(
        "Im privaten Haushalt zahlt man im Wesentlichen für die kWh, die "
        "durch den Zähler laufen. Der Netzbetreiber unterstellt ein "
        "Standardlastprofil, abgerechnet wird einmal im Jahr. In der "
        "Industrie funktioniert das ab einem Jahresverbrauch von "
        "100 000 kWh nicht mehr: hier hängt eine registrierende "
        "Leistungsmessung am Anschluss, die jede Viertelstunde "
        "misst, und der höchste Wert des Jahres wird teuer abgerechnet. "
        "Das ist der Leistungspreis.",
        s["Body"],
    ))
    story.append(Paragraph(
        "Wer einmal im Januar um neun Uhr für eine Viertelstunde "
        "500 kW gezogen hat, zahlt dafür das ganze Jahr. Genau deshalb "
        "lohnt sich Lastmanagement oder ein Batteriespeicher in der "
        "Industrie oft deutlich schneller als beim Privatkunden.",
        s["Body"],
    ))

    # --- Tarifstrukturen ---
    story.append(Paragraph("Zwei Welten: SLP und RLM", s["H1"]))
    story.append(Paragraph(
        "Der Markt teilt sich an einer harten Schwelle von 100 000 kWh "
        "Jahresverbrauch. Darunter zählt man als SLP-Kunde "
        "(Standardlastprofil), darüber wird die registrierende "
        "Leistungsmessung (RLM) Pflicht. Der Unterschied ist nicht nur "
        "messtechnischer Natur — er ändert die ganze Logik der "
        "Stromrechnung:",
        s["Body"],
    ))
    story.append(Paragraph(
        "<b>SLP-Kunden</b> zahlen nur einen Arbeitspreis in ct/kWh. "
        "Lastverschiebung beeinflusst die Netzentgelte nicht, weil dem "
        "Kunden ohnehin ein fixes Referenzprofil unterstellt wird (H0 "
        "für Haushalte, G0–G6 für Gewerbe).",
        s["Body"],
    ))
    story.append(Paragraph(
        "<b>RLM-Kunden</b> zahlen zusätzlich einen Leistungspreis in "
        "Euro pro kW und Jahr — bezogen auf die höchste Viertelstunden-"
        "leistung im Abrechnungsjahr. Damit ist plötzlich jede einzelne "
        "Viertelstunde wirtschaftlich relevant.",
        s["Body"],
    ))

    # --- Der Leistungspreis im Detail ---
    story.append(Paragraph("Wie der Leistungspreis berechnet wird", s["H1"]))
    story.append(Paragraph(
        "Die Grundformel ist denkbar einfach:",
        s["Body"],
    ))
    story.append(Paragraph(
        "Netzentgelt = LP · P<sub>max</sub> + AP · E<sub>Jahr</sub>",
        s["Mono"],
    ))
    story.append(Paragraph(
        "wobei P<sub>max</sub> die höchste gemittelte Viertelstunden-"
        "leistung im Jahr ist, LP der Leistungspreis in €/(kW·a) und AP "
        "der Arbeitspreis in ct/kWh. Typische Werte auf Mittelspannung "
        "liegen bei 80 bis 180 €/(kW·a) für den Leistungspreis. Ein "
        "Betrieb mit 500 kW Jahresspitze zahlt damit 40 000 bis "
        "90 000 € allein für die Bereitstellung dieser Leistung — "
        "unabhängig davon, wie oft sie tatsächlich abgerufen wird.",
        s["Body"],
    ))
    story.append(Paragraph(
        "Jeder Netzbetreiber bietet zwei Tarifvarianten an, abhängig "
        "von der Benutzungsstundenzahl t<sub>B</sub> = E<sub>Jahr</sub> "
        "/ P<sub>max</sub>. Bei mehr als 2500 Benutzungsstunden im Jahr "
        "ist der Leistungspreis hoch und der Arbeitspreis niedrig — "
        "das passt zu Grundlast-Industrien, die das ganze Jahr "
        "durchlaufen. Unter 2500 Stunden ist es umgekehrt: kleiner "
        "Leistungspreis, höherer kWh-Preis. Saisonbetriebe profitieren "
        "von der zweiten Variante.",
        s["Body"],
    ))

    # --- Reduktionsmechanismen ---
    story.append(Paragraph("Rabatte für Industriekunden", s["H1"]))
    story.append(Paragraph(
        "Der § 19 StromNEV kennt zwei wichtige Reduktionspfade. Wer "
        "seine Jahreshöchstlast nachweislich außerhalb der vom "
        "Netzbetreiber definierten Hochlastzeitfenster abruft, kann "
        "ein individuelles Netzentgelt bekommen — die sogenannte "
        "atypische Netznutzung. Typisch sind Einsparungen von 20 bis "
        "40 Prozent. Die Hochlastzeitfenster veröffentlicht jeder "
        "Verteilnetzbetreiber jährlich neu, etwa werktags von acht "
        "bis dreizehn und von sechzehn bis zwanzig Uhr im Winter.",
        s["Body"],
    ))
    story.append(Paragraph(
        "Für stromintensive Letztverbraucher mit mindestens 7000 "
        "Benutzungsstunden und 10 GWh Jahresverbrauch gibt es zusätzlich "
        "pauschal reduzierte Netzentgelte — 20 Prozent bei 7000 h, "
        "15 Prozent bei 7500 h und nur noch 10 Prozent bei 8000 h des "
        "Standardentgelts.",
        s["Body"],
    ))

    # --- §14a EnWG ---
    story.append(Paragraph("Das Privat-Pendant: § 14a EnWG", s["H1"]))
    story.append(Paragraph(
        "Für Privatkunden mit steuerbaren Verbrauchseinrichtungen "
        "(Wärmepumpe, Wallbox, Klimagerät, Batteriespeicher ab "
        "4.2 kW) gibt es seit 2024 mit § 14a EnWG drei Module für "
        "Netzentgelt-Rabatte. Modul 1 ist eine pauschale Reduktion "
        "von etwa 110 bis 190 Euro pro Jahr und gilt automatisch. "
        "Modul 2 senkt den Arbeitspreis der Netzentgelte um "
        "60 Prozent, verlangt aber einen eigenen Zähler für die "
        "steuerbare Verbrauchseinrichtung. Modul 3 schließlich — "
        "verfügbar seit April 2025 — bringt zeitvariable "
        "Netzentgelte mit drei Preisstufen und kommt damit der "
        "Industrielogik am nächsten.",
        s["Body"],
    ))
    story.append(Paragraph(
        "Im Gegenzug für den Rabatt darf der Netzbetreiber die "
        "steuerbare Last im Bedarfsfall auf 4.2 kW drosseln. EMOS "
        "Light modelliert genau diese Drosselung bereits über das "
        "<i>par14a_curtailment_kw</i>-Feld.",
        s["Body"],
    ))

    # --- Beschaffung ---
    story.append(Paragraph("Beschaffungsmodelle in der Industrie", s["H1"]))
    story.append(Paragraph(
        "Während Privatkunden zwischen Festpreis und dynamischem "
        "Spottarif wählen, gibt es in der Industrie fünf etablierte "
        "Modelle: Vollversorgung (Festpreis, Lieferant trägt das "
        "Risiko), Tranchenmodell (gestaffelter Einkauf am "
        "Terminmarkt), spotmarktorientierte Direktanbindung, "
        "strukturierte Mischbeschaffung und Hybridmodelle aus "
        "Grundlast-Festpreis plus Spitzenlast-Spot. Beim Spotmodell "
        "zahlt der Industriekunde EPEX Day-Ahead beziehungsweise "
        "den Viertelstunden-Intraday-Preis (seit Oktober 2025 "
        "Standard), plus Bilanzkreismanagement, Lieferantenmarge, "
        "Netzentgelt, Steuern und Umlagen.",
        s["Body"],
    ))

    # --- Code-technische Umsetzung ---
    story.append(PageBreak())
    story.append(Paragraph(
        "Code-technische Umsetzung",
        s["H1"],
    ))
    story.append(Paragraph(
        "Würde man EMOS Light um ein Industrie-Tarifmodell "
        "erweitern, fallen drei Bausteine an. Erstens eine "
        "neue Variable für die Spitzenlast über den "
        "Optimierungshorizont. Zweitens Constraints, die jeden "
        "Netzbezug an diese Variable koppeln. Drittens ein "
        "zusätzlicher Term in der Zielfunktion.",
        s["Body"],
    ))
    story.append(Paragraph("Die Variable", s["H2"]))
    story.append(Paragraph(
        "P_peak = pulp.LpVariable(\"p_peak\", lowBound=0)",
        s["Mono"],
    ))
    story.append(Paragraph("Die Constraints", s["H2"]))
    story.append(Paragraph(
        "for t in range(num_steps):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;model += grid_buy[t] &lt;= P_peak",
        s["Mono"],
    ))
    story.append(Paragraph(
        "Damit ist P_peak automatisch das Maximum aller Bezugs-"
        "leistungen. Der Solver hat einen Anreiz, P_peak möglichst "
        "klein zu halten, weil dieser Wert in die Zielfunktion einfließt.",
        s["Body"],
    ))
    story.append(Paragraph("Die Zielfunktion", s["H2"]))
    story.append(Paragraph(
        "cost += LP_eur_per_kw_a * P_peak * (horizon_h / 8760)",
        s["Mono"],
    ))
    story.append(Paragraph(
        "Der Faktor horizon_h/8760 rechnet den Jahres-Leistungspreis "
        "anteilig auf den optimierten Horizont herunter. Bei einem "
        "Tagesoptimierungsfenster wird also nur etwa ein 365stel "
        "des Leistungspreises pro Tag wirksam.",
        s["Body"],
    ))

    story.append(Paragraph("Varianten", s["H2"]))
    story.append(Paragraph(
        "Für die atypische Netznutzung filtert man die Constraints "
        "über eine Hochlastzeitfenster-Maske: P_peak greift nur "
        "innerhalb der vom Netzbetreiber definierten Stunden. "
        "Außerhalb darf der Bezug höher gehen, ohne den Leistungs-"
        "preis zu treiben. Für US-typische monatliche Spitzen-"
        "preise legt man stattdessen zwölf P_peak-Variablen an "
        "und summiert ihre Beiträge.",
        s["Body"],
    ))

    story.append(Paragraph("Stolperfallen", s["H2"]))
    story.append(Paragraph(
        "Der größte Stolperstein liegt im rollierenden MPC-Horizont. "
        "Wenn das Solver-Fenster kleiner als der Abrechnungszeitraum "
        "ist, kennt der Solver den bisherigen Jahres-Peak nicht — er "
        "optimiert immer nur sein eigenes Fenster. Die saubere Lösung "
        "ist, den bislang erreichten Peak als Untergrenze für die "
        "neue P_peak-Variable mitzugeben:",
        s["Body"],
    ))
    story.append(Paragraph(
        "model += P_peak &gt;= P_peak_so_far",
        s["Mono"],
    ))
    story.append(Paragraph(
        "Damit darf der Solver den Peak nur dann anheben, wenn das "
        "wirtschaftlich sinnvoll ist — und nicht versehentlich "
        "vergessen, dass im Januar schon mal 480 kW gezogen wurden.",
        s["Body"],
    ))
    story.append(Paragraph(
        "Ein zweiter Punkt: Prognose­unsicherheit kann die ganze "
        "Strategie kaputt machen. Ein einziger nicht antizipierter "
        "Lastpeak verteuert das gesamte Jahr. In der Praxis arbeitet "
        "man deshalb mit einer Sicherheitsmarge unter der Peak-"
        "Schwelle, oder mit einem zusätzlichen Speicher-Buffer als "
        "Notreserve.",
        s["Body"],
    ))

    # --- Existierende Tools ---
    story.append(Paragraph("Existierende Frameworks", s["H1"]))
    story.append(Paragraph(
        "Wer das Rad nicht neu erfinden möchte: PyPSA, oemof.solph "
        "und Calliope können demand charges modellieren — Calliope "
        "am saubersten dokumentiert über das <i>cost.maximum_demand</i>-"
        "Konzept. Die kommerziellen Tools DER-CAM und AnyEnergy haben "
        "US-typische demand charges nativ eingebaut. Für EMOS Light "
        "wäre eine Eigenimplementierung in der oben skizzierten Form "
        "aber überschaubarer Aufwand und passt besser zur bestehenden "
        "MILP-Komponenten-Architektur.",
        s["Body"],
    ))

    # --- Schluss ---
    story.append(Paragraph("Zusammenfassung", s["H1"]))
    story.append(Paragraph(
        "Der Privatkunde optimiert über den Arbeitspreis, der "
        "Industriekunde zusätzlich über den Leistungspreis. Beide "
        "Welten konvergieren langsam — § 14a EnWG Modul 3 bringt "
        "Zeitvariabilität in die Privatnetzentgelte, und die "
        "Viertelstunden-Auktion an der EPEX ist seit Oktober 2025 "
        "Standard auch im Day-Ahead-Markt. Eine technische "
        "Erweiterung von EMOS Light um Industrietarife wäre also "
        "kein Sondergleis, sondern ein logischer nächster Schritt. "
        "Die mathematische Modellierung ist dabei der kleinere Teil "
        "des Aufwands — das eigentliche Detail steckt im Tarif-"
        "Datenmodell und in der Persistenz des Jahres-Peaks über "
        "die MPC-Fenstergrenzen hinweg.",
        s["Body"],
    ))

    return story


def _resolve_desktop() -> Path:
    home = Path.home()
    for c in (home / "OneDrive" / "Desktop",
              home / "OneDrive - Personal" / "Desktop",
              home / "Desktop"):
        if c.exists():
            return c
    raise FileNotFoundError("Kein Desktop-Ordner gefunden.")


def main(out_path: Path) -> None:
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.2*cm, bottomMargin=2.2*cm,
        title="EMOS Light — Leistungspreis und Flexibilität",
        author="EMOS Light Projektgruppe",
    )
    doc.build(build_story(styles))
    print(f"PDF erzeugt: {out_path}")


if __name__ == "__main__":
    desktop = _resolve_desktop()
    target = desktop / "leistungspreis_recherche.pdf"
    try:
        main(target)
    except PermissionError:
        tmp = target.with_suffix(".new.pdf")
        main(tmp)
        try:
            tmp.replace(target)
            print(f"Zieldatei ersetzt: {target}")
        except PermissionError:
            print(
                f"Hinweis: {target.name} ist von einem Viewer gesperrt. "
                f"Neue Version liegt unter {tmp.name}."
            )
