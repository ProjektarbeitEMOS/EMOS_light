"""Kurze Beschreibungs-PDF fuer das Modul weitere_preise.py."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

BLUE = colors.HexColor("#0B3D91")
DARK = colors.HexColor("#222222")
GREY = colors.HexColor("#555555")

# Schriftnamen — werden in register_fonts() auf DejaVu gesetzt, sobald die
# TTF-Dateien gefunden werden (DejaVu hat ₂, ₀, →, −, × — Helvetica nicht).
FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FONT_I = "Helvetica-Oblique"


def register_fonts():
    """DejaVu-TTFs aus matplotlib registrieren, damit Sonderzeichen (Index,
    Pfeil, echtes Minus) nicht als Kaestchen erscheinen. Faellt still auf
    Helvetica zurueck, falls matplotlib/Fonts fehlen."""
    global FONT, FONT_B, FONT_I
    try:
        import matplotlib
        ttf = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
        faces = {
            "DejaVu": "DejaVuSans.ttf",
            "DejaVu-Bold": "DejaVuSans-Bold.ttf",
            "DejaVu-Obl": "DejaVuSans-Oblique.ttf",
            "DejaVu-BoldObl": "DejaVuSans-BoldOblique.ttf",
        }
        for name, fn in faces.items():
            pdfmetrics.registerFont(TTFont(name, str(ttf / fn)))
        pdfmetrics.registerFontFamily(
            "DejaVu", normal="DejaVu", bold="DejaVu-Bold",
            italic="DejaVu-Obl", boldItalic="DejaVu-BoldObl",
        )
        FONT, FONT_B, FONT_I = "DejaVu", "DejaVu-Bold", "DejaVu-Obl"
    except Exception as exc:   # pragma: no cover - Fallback
        print(f"Hinweis: DejaVu nicht registriert ({exc}); nutze Helvetica.")


def styles():
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("t", parent=base["Title"], fontName=FONT_B,
                                fontSize=20, textColor=BLUE, spaceAfter=4)
    s["sub"] = ParagraphStyle("s", parent=base["Normal"], fontName=FONT_I,
                              fontSize=11, textColor=GREY, spaceAfter=14)
    s["h"] = ParagraphStyle("h", parent=base["Heading1"], fontName=FONT_B,
                            fontSize=14, textColor=BLUE, spaceBefore=12, spaceAfter=6)
    s["body"] = ParagraphStyle("b", parent=base["BodyText"], fontName=FONT,
                               fontSize=10.5, leading=14, textColor=DARK, spaceAfter=6)
    s["cap"] = ParagraphStyle("c", parent=base["Italic"], fontName=FONT_I,
                              fontSize=9, textColor=GREY, spaceAfter=10)
    return s


def table(headers, rows, widths):
    data = [headers] + rows
    t = Table(data, colWidths=widths)
    st = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_B),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F2F6FB"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(st))
    return t


def build(s):
    e = []
    P = lambda txt, st="body": e.append(Paragraph(txt, s[st]))

    P("weitere_preise.py", "title")
    P("Zusätzliche Preis-Eingangsgrößen für ein (Industrie-)EMOS — "
      "CO₂-Preis, Gaspreis, Fernwärmepreis, Einspeisevergütung", "sub")

    P("Überblick", "h")
    P("Das Modul ergänzt die bestehenden Daten-Module (prices, weather, solar) "
      "um vier weitere Preisgrößen. Reines Python (nur datetime), überall "
      "einbindbar. Werte Stand 2026, jährlich zu aktualisieren.")

    P("Datenverfügbarkeit (wichtig fürs Design):", "body")
    e.append(table(
        ["Größe", "Quelle", "Automatisch?"],
        [
            ["CO₂ national (BEHG/nEHS)", "gesetzlich festgelegt", "Konstante/Jahr"],
            ["CO₂ EU-ETS (EUA)", "Markt (EEX/ICE)", "nur manuell/Anbieter"],
            ["Gas-Großhandel (THE)", "Markt (EEX)", "nur manuell/Anbieter"],
            ["Fernwärme", "Versorger-Preisblatt", "nein (Preisgleitklausel)"],
            ["Einspeisevergütung", "EEG / BNetzA", "Tabelle (keine Zeitreihe)"],
        ],
        [6.0 * cm, 5.0 * cm, 4.5 * cm],
    ))
    e.append(Spacer(1, 4))
    P("Keiner der vier Werte ist über eine kostenlose offizielle API "
      "abrufbar — anders als der Strom-Spotpreis.", "cap")

    # 1 CO2
    P("1. CO₂-Preis", "h")
    P("<b>national_co2_price_eur_per_t(year)</b> → €/t. Nationaler Preis nach "
      "BEHG; 2026 Korridor 55–65 €/t (Default 55).")
    P("<b>co2_surcharge_ct_per_kwh(preis_eur_t, emissionsfaktor_t_mwh)</b> → "
      "ct/kWh. Rechnet den CO₂-Preis in einen Aufschlag um, z. B. Erdgas: "
      "55 €/t × 0,201 t/MWh = 1,11 ct/kWh. So fließt CO₂ in den Gas-/Wärmepreis.")

    # 2 Gas
    P("2. Gaspreis", "h")
    P("<b>gas_consumer_price_ct_kwh(wholesale_ct_kwh, …)</b> → ct/kWh. "
      "Industrie-Endpreis = Großhandel (THE Day-Ahead, manuell/Anbieter) + "
      "Netzentgelt Gas + Energiesteuer + weitere Aufschläge + CO₂-Aufschlag "
      "(BEHG). Der Großhandelspreis ist der einzige Pflicht-Input.")

    # 3 Fernwärme
    P("3. Fernwärmepreis", "h")
    P("<b>fernwaerme_arbeitspreis_ct_kwh(base_ap_ct_kwh, …)</b> → ct/kWh. "
      "Kein Markt, kein API: versorgerspezifisch, meist über eine "
      "Preisgleitklausel an Indizes (Gas, Lohn) gekoppelt. Die Funktion bildet "
      "die typische Formel AP = AP₀·(w_fix + w_gas·Gas/Gas₀ + w_lohn·Lohn/Lohn₀) "
      "ab. Ohne Indexdaten einfach AP₀ als Konstante nutzen.")

    # 4 Einspeisevergütung
    P("4. Einspeisevergütung (EEG)", "h")
    P("<b>einspeiseverguetung_ct_kwh(kwp, einspeisetyp)</b> → ct/kWh. Keine "
      "Zeitreihe, sondern feste Sätze je Größe/Typ. Der Satz wird "
      "<b>leistungsgewichtet</b> über die Stufen gemittelt (z. B. 15 kWp "
      "Teileinspeisung = 7,43 ct/kWh). Garantiert 20 Jahre ab Inbetriebnahme.")
    P("Sätze für Inbetriebnahme Feb–Jul 2026 (ct/kWh):", "body")
    e.append(table(
        ["Leistungsklasse", "Teileinspeisung", "Volleinspeisung"],
        [
            ["bis 10 kWp", "7,78", "12,34"],
            ["über 10 bis 40 kWp", "6,73", "10,35"],
            ["über 40 bis 100 kWp", "5,50", "10,35"],
        ],
        [6.0 * cm, 4.75 * cm, 4.75 * cm],
    ))
    e.append(Spacer(1, 4))
    P("Halbjährliche Degression −1 %; über 100 kWp gilt verpflichtende "
      "Direktvermarktung (Marktprämie).", "cap")

    # Einbindung
    P("Einbindung in den Optimierer", "h")
    P("Alle Funktionen liefern Werte in ct/kWh bzw. €/t. CO₂-, Gas- und "
      "Fernwärmepreis fließen wie der Strompreis als Kosten pro kWh in die "
      "jeweilige Energiebilanz/Zielfunktion ein; der CO₂-Aufschlag wird auf "
      "Gas/Wärme addiert. Die Einspeisevergütung ist ein Erlös pro "
      "eingespeister kWh (negativer Kostenbeitrag).")

    # Quellen
    P("Quellen (Stand 2026)", "h")
    P("CO₂ (BEHG/nEHS): DEHSt. — Einspeisevergütung: BNetzA / ADAC-Übersicht "
      "(Feb–Jul 2026). — Gas-Großhandel: THE / EEX. — Fernwärme: "
      "Versorger-Preisblatt / AGFW. Netzentgelte, EEG-Sätze und CO₂-Preise "
      "ändern sich jährlich und sind dann im Modul zu aktualisieren.")

    return e


def main(out: Path):
    register_fonts()
    doc = SimpleDocTemplate(str(out), pagesize=A4,
                            leftMargin=2.0 * cm, rightMargin=2.0 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                            title="weitere_preise.py — Beschreibung")
    doc.build(build(styles()))
    print(f"PDF erzeugt: {out}")


def _desktop():
    h = Path.home()
    for c in (h / "OneDrive" / "Desktop", h / "Desktop"):
        if c.exists():
            return c
    raise FileNotFoundError("Kein Desktop gefunden.")


if __name__ == "__main__":
    target = _desktop() / "emos_data_modules" / "weitere_preise_beschreibung.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        main(target)
    except PermissionError:
        tmp = target.with_suffix(".new.pdf")
        main(tmp)
        try:
            tmp.replace(target)
            print(f"Zieldatei ersetzt: {target}")
        except PermissionError:
            print(f"Hinweis: {target.name} gesperrt. Neue Version: {tmp.name}")
