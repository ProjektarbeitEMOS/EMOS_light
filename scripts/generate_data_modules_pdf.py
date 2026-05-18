"""Erzeugt eine Beschreibungs-PDF fuer die drei Datenmodule prices/solar/weather.

Wird auf den Desktop gelegt, neben den kopierten .py-Dateien.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {}
    styles["Title"] = ParagraphStyle(
        "Title", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=22, leading=26,
        textColor=colors.HexColor("#0B3D91"), spaceAfter=6,
    )
    styles["Subtitle"] = ParagraphStyle(
        "Subtitle", parent=base["Normal"],
        fontName="Helvetica-Oblique", fontSize=12, leading=15,
        textColor=colors.HexColor("#444444"), spaceAfter=16,
    )
    styles["H1"] = ParagraphStyle(
        "H1", parent=base["Heading1"],
        fontName="Helvetica-Bold", fontSize=17, leading=21,
        textColor=colors.HexColor("#0B3D91"),
        spaceBefore=14, spaceAfter=8,
    )
    styles["H2"] = ParagraphStyle(
        "H2", parent=base["Heading2"],
        fontName="Helvetica-Bold", fontSize=13, leading=17,
        textColor=colors.HexColor("#1F4E79"),
        spaceBefore=12, spaceAfter=6,
    )
    styles["H3"] = ParagraphStyle(
        "H3", parent=base["Heading3"],
        fontName="Helvetica-Bold", fontSize=11, leading=14,
        textColor=colors.HexColor("#333333"),
        spaceBefore=10, spaceAfter=4,
    )
    styles["Body"] = ParagraphStyle(
        "Body", parent=base["BodyText"],
        fontName="Helvetica", fontSize=10.5, leading=14,
        textColor=colors.black, spaceAfter=6, alignment=0,
    )
    styles["Mono"] = ParagraphStyle(
        "Mono", parent=base["Code"],
        fontName="Courier", fontSize=9, leading=12,
        textColor=colors.HexColor("#222222"), spaceAfter=8,
        leftIndent=10,
    )
    styles["Caption"] = ParagraphStyle(
        "Caption", parent=base["Italic"],
        fontName="Helvetica-Oblique", fontSize=9, leading=12,
        textColor=colors.HexColor("#555555"), spaceAfter=10,
    )
    return styles


def io_table(rows: list[list[str]]) -> Table:
    """Tabelle fuer Input/Output-Beschreibungen."""
    t = Table(rows, colWidths=[3.6*cm, 2.4*cm, 10.5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Courier-Bold"),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica-Oblique"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F2F6FB"), colors.HexColor("#FFFFFF")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def func_block(
    story, styles,
    name: str,
    purpose: str,
    inputs: list[tuple[str, str, str]],
    outputs: list[tuple[str, str, str]],
    notes: str = "",
):
    """Fuegt einen Funktionsblock zur Story hinzu."""
    story.append(Paragraph(f"<font face='Courier-Bold'>{name}</font>",
                           styles["H3"]))
    story.append(Paragraph(purpose, styles["Body"]))

    if inputs:
        story.append(Paragraph("<b>Eingaben:</b>", styles["Body"]))
        rows = [["Parameter", "Typ", "Bedeutung"]] + [list(r) for r in inputs]
        story.append(io_table(rows))
        story.append(Spacer(1, 4))

    if outputs:
        story.append(Paragraph("<b>Ausgaben:</b>", styles["Body"]))
        rows = [["Feld", "Typ", "Bedeutung"]] + [list(r) for r in outputs]
        story.append(io_table(rows))
        story.append(Spacer(1, 4))

    if notes:
        story.append(Paragraph(f"<i>Hinweis:</i> {notes}", styles["Body"]))
    story.append(Spacer(1, 6))


def build_story(styles) -> list:
    story = []

    # ===== Titelseite =====
    story.append(Paragraph(
        "Datenmodule für die Energieoptimierung",
        styles["Title"],
    ))
    story.append(Paragraph(
        "EMOS Light — Externe Datenanbindung (prices · solar · weather)",
        styles["Subtitle"],
    ))
    story.append(Paragraph(
        "Diese drei Module holen sich die für eine Energieoptimierung nötigen "
        "Zeitreihen aus dem Internet bzw. berechnen sie aus Standortdaten:",
        styles["Body"],
    ))
    story.append(Paragraph(
        "• <b>prices.py</b> — Day-Ahead-Strompreise (EPEX über Energy-Charts-API) "
        "und Endverbraucher-Preisberechnung aus Tarifbestandteilen.<br/>"
        "• <b>weather.py</b> — Wetter- und Strahlungsprognose (Open-Meteo-API) "
        "mit Temperatur, GHI/DNI/DHI, Wind und Bewölkung.<br/>"
        "• <b>solar.py</b> — Sonnenstandsberechnung, GHI→POA-Transposition "
        "(Perez 1990 oder Liu &amp; Jordan 1963), PV-Leistungsmodell.",
        styles["Body"],
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Externe Abhängigkeiten:</b> nur <i>numpy</i>, <i>pandas</i>, "
        "<i>requests</i> (alles auf PyPI). Keine internen Verknüpfungen mit "
        "anderen EMOS-Modulen — die drei Dateien sind frei portierbar.",
        styles["Body"],
    ))
    story.append(Paragraph(
        "<b>API-Schlüssel:</b> keine. Beide verwendeten APIs (Energy-Charts "
        "und Open-Meteo) sind frei und ohne Registrierung nutzbar.",
        styles["Body"],
    ))
    story.append(Paragraph(
        "<b>Fallback-Verhalten:</b> Beide API-Funktionen fangen Netz-/HTTP-"
        "Fehler ab und liefern statt einer Exception ein synthetisch erzeugtes "
        "Tagesprofil — damit lassen sich Tests offline ausführen.",
        styles["Body"],
    ))

    # ============================================================
    # 1. prices.py
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("1 prices.py — Strompreise", styles["H1"]))
    story.append(Paragraph(
        "Holt die Day-Ahead-Börsenpreise (EPEX Spot) für die deutsch-"
        "luxemburgische Gebotszone und ergänzt sie auf Wunsch um Tarif-"
        "bestandteile zum Endverbraucherpreis. Stündliche Auflösung, "
        "24 Werte je Tag.",
        styles["Body"],
    ))

    story.append(Paragraph("1.1 Funktionen", styles["H2"]))

    func_block(
        story, styles,
        "fetch_day_ahead_prices(date=None, bidding_zone='DE-LU')",
        "Holt die EPEX-Day-Ahead-Preise eines Tages von der Energy-Charts-"
        "API (Fraunhofer ISE). Bei Netzfehler wird automatisch auf "
        "<i>generate_synthetic_prices()</i> umgeschaltet.",
        inputs=[
            ("date", "date | None",
             "Gewünschter Tag. Default: morgen (datetime.date.today() + 1)."),
            ("bidding_zone", "str",
             "Gebotszone. Default 'DE-LU'. Weitere möglich: 'AT', 'CH', "
             "'FR', 'BE', 'NL' usw."),
        ],
        outputs=[
            ("timestamp", "datetime",
             "Zeitstempel jedes Stundenintervalls (Anfang)."),
            ("price_eur_mwh", "float",
             "Börsenpreis in EUR/MWh (kann negativ werden)."),
            ("price_ct_kwh", "float",
             "Börsenpreis in ct/kWh (= price_eur_mwh / 10)."),
        ],
        notes="Rückgabetyp ist ein pandas.DataFrame mit 24 Zeilen.",
    )

    func_block(
        story, styles,
        "calculate_consumer_price(spot_prices_ct_kwh, tariff_config)",
        "Rechnet Börsenpreise in Endverbraucherpreise um. Reine Berechnung — "
        "kein Internet. Formel: <i>(Spot + Aufschläge) × (1 + MwSt/100)</i>.",
        inputs=[
            ("spot_prices_ct_kwh", "np.ndarray",
             "Börsenpreis-Zeitreihe in ct/kWh (z.B. aus "
             "fetch_day_ahead_prices()['price_ct_kwh'])."),
            ("tariff_config", "dict",
             "Tarif-Dict mit Schlüsseln provider_markup_ct_kwh, "
             "grid_fee_ct_kwh, concession_fee_ct_kwh, electricity_tax_ct_kwh, "
             "kwkg_surcharge_ct_kwh, stromnev_surcharge_ct_kwh, "
             "offshore_surcharge_ct_kwh, vat_pct."),
        ],
        outputs=[
            ("rückgabe", "np.ndarray",
             "Endpreis brutto in ct/kWh, auf 3 Nachkommastellen gerundet, "
             "gleiche Länge wie spot_prices_ct_kwh."),
        ],
    )

    func_block(
        story, styles,
        "get_surcharges_summary(tariff_config)",
        "Liefert eine Aufschlüsselung aller Preisbestandteile — nützlich für "
        "Reports und Dashboard-Anzeige.",
        inputs=[
            ("tariff_config", "dict",
             "Gleiches Schema wie bei calculate_consumer_price()."),
        ],
        outputs=[
            ("fixed_netto_ct_kwh", "float",
             "Summe der festen Aufschläge ohne MwSt."),
            ("fixed_brutto_ct_kwh", "float",
             "dito, inkl. MwSt."),
            ("vat_pct", "float", "Mehrwertsteuersatz."),
            ("monthly_total_eur", "float",
             "Summe monatlicher Grundgebühren (Anbieter + Netz)."),
            ("breakdown", "list[tuple]",
             "Liste (Bezeichnung, Wert in ct/kWh) aller Einzelpositionen."),
        ],
    )

    func_block(
        story, styles,
        "generate_synthetic_prices(date, num_steps=96)",
        "Erzeugt ein synthetisches, reproduzierbares Tagesprofil mit "
        "typischer Charakteristik: Nacht-Tal, Morgen-Peak, Solar-Dip, "
        "Abend-Peak. Wird als Fallback verwendet, wenn die API nicht "
        "erreichbar ist.",
        inputs=[
            ("date", "date", "Datum (dient gleichzeitig als Zufalls-Seed)."),
            ("num_steps", "int",
             "Anzahl Zeitschritte über 24 h. Default 96 (= 15 min)."),
        ],
        outputs=[
            ("timestamp", "datetime", "Zeitstempel je Slot."),
            ("price_eur_mwh", "float", "Synthetischer Preis in EUR/MWh."),
            ("price_ct_kwh", "float", "Synthetischer Preis in ct/kWh."),
        ],
    )

    story.append(Paragraph("1.2 Beispiel", styles["H2"]))
    story.append(Paragraph(
        "<font face='Courier'>"
        "import datetime<br/>"
        "from prices import fetch_day_ahead_prices, calculate_consumer_price<br/>"
        "<br/>"
        "df = fetch_day_ahead_prices(datetime.date(2026, 5, 17))<br/>"
        "spot = df['price_ct_kwh'].values<br/>"
        "<br/>"
        "tarif = {<br/>"
        "&nbsp;&nbsp;'provider_markup_ct_kwh': 2.15,<br/>"
        "&nbsp;&nbsp;'grid_fee_ct_kwh': 9.26,<br/>"
        "&nbsp;&nbsp;'concession_fee_ct_kwh': 1.66,<br/>"
        "&nbsp;&nbsp;'electricity_tax_ct_kwh': 2.05,<br/>"
        "&nbsp;&nbsp;'kwkg_surcharge_ct_kwh': 0.446,<br/>"
        "&nbsp;&nbsp;'stromnev_surcharge_ct_kwh': 1.559,<br/>"
        "&nbsp;&nbsp;'offshore_surcharge_ct_kwh': 0.941,<br/>"
        "&nbsp;&nbsp;'vat_pct': 19.0,<br/>"
        "}<br/>"
        "endpreis = calculate_consumer_price(spot, tarif)"
        "</font>",
        styles["Body"],
    ))

    # ============================================================
    # 2. weather.py
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("2 weather.py — Wetter &amp; Strahlung", styles["H1"]))
    story.append(Paragraph(
        "Holt die meteorologische Tagesprognose von der Open-Meteo-API "
        "(kostenlos, kein API-Key). Die Daten kommen stündlich und werden "
        "intern auf die gewünschte Zeitauflösung (z.B. 15 min) linear "
        "interpoliert.",
        styles["Body"],
    ))

    story.append(Paragraph("2.1 Funktionen", styles["H2"]))

    func_block(
        story, styles,
        "fetch_weather_forecast(lat, lon, date=None, num_steps=96, step_minutes=15)",
        "Liefert Temperatur, Globalstrahlung (GHI), direkte Normalstrahlung "
        "(DNI), Diffusstrahlung (DHI), Bewölkungsgrad und Windgeschwindigkeit "
        "als zeitaufgelöste Prognose für den angegebenen Standort. "
        "Bei API-Fehler Rückfall auf <i>generate_synthetic_weather()</i>.",
        inputs=[
            ("lat", "float", "Breitengrad in Grad (z.B. 49.33 für Schwandorf)."),
            ("lon", "float", "Längengrad in Grad (z.B. 12.11 Schwandorf)."),
            ("date", "date | None", "Startdatum. Default: heute."),
            ("num_steps", "int",
             "Wie viele Zeitschritte zurückgegeben werden. "
             "Default 96 (24 h × 4 Quartelstunden)."),
            ("step_minutes", "int",
             "Schrittweite der Ausgabe in Minuten. Default 15."),
        ],
        outputs=[
            ("timestamp", "datetime", "Zeitstempel jedes Slots."),
            ("temperature_c", "float", "Lufttemperatur in 2 m Höhe (°C)."),
            ("ghi_w_m2", "float",
             "Globalstrahlung horizontal (W/m²) — Summe aus Direkt- und "
             "Diffusstrahlung."),
            ("dni_w_m2", "float",
             "Direkte Normalstrahlung (W/m²), wenn von der API geliefert."),
            ("dhi_w_m2", "float", "Diffusstrahlung horizontal (W/m²)."),
            ("cloud_cover_pct", "float", "Gesamtbewölkung in Prozent."),
            ("wind_speed_m_s", "float",
             "Windgeschwindigkeit in 10 m Höhe (m/s)."),
        ],
        notes="Rückgabetyp ist pandas.DataFrame mit num_steps Zeilen.",
    )

    func_block(
        story, styles,
        "generate_synthetic_weather(date, num_steps=96)",
        "Erzeugt ein jahreszeit­abhängiges Wetterprofil mit Sinus-Temperatur, "
        "Glockenkurven-Globalstrahlung und plausibler Bewölkung. Reproduzierbar "
        "über den Datums-Seed.",
        inputs=[
            ("date", "date", "Datum (Monat steuert Saison, Tag dient als Seed)."),
            ("num_steps", "int", "Anzahl Zeitschritte. Default 96."),
        ],
        outputs=[
            ("DataFrame", "pd.DataFrame",
             "Gleiches Spalten-Schema wie fetch_weather_forecast(). DNI und "
             "DHI bleiben 0 — gegebenenfalls über solar.py rekonstruieren."),
        ],
    )

    story.append(Paragraph("2.2 Beispiel", styles["H2"]))
    story.append(Paragraph(
        "<font face='Courier'>"
        "from weather import fetch_weather_forecast<br/>"
        "<br/>"
        "df = fetch_weather_forecast(lat=49.33, lon=12.11,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;num_steps=96, step_minutes=15)<br/>"
        "ghi = df['ghi_w_m2'].values<br/>"
        "temp = df['temperature_c'].values"
        "</font>",
        styles["Body"],
    ))

    # ============================================================
    # 3. solar.py
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("3 solar.py — Sonnenstand &amp; PV-Ertrag",
                           styles["H1"]))
    story.append(Paragraph(
        "Dieses Modul ist <b>komplett offline</b> — es braucht kein "
        "Internet. Es berechnet den Sonnenstand für beliebige Koordinaten "
        "und Zeitpunkte, transponiert die Globalstrahlung auf die geneigte "
        "Modulfläche (POA = Plane of Array) und schätzt daraus die PV-Leistung.",
        styles["Body"],
    ))
    story.append(Paragraph(
        "Verwendete Modelle: Spencer (1971) für Deklination und Zeit-"
        "gleichung, Maxwell (1987, DISC) für die GHI→DNI-Dekomposition, "
        "Perez (1990) für anisotrope Diffusstrahlung sowie Liu &amp; Jordan "
        "(1963) als isotropes Fallback-Modell.",
        styles["Body"],
    ))

    story.append(Paragraph("3.1 Funktionen", styles["H2"]))

    func_block(
        story, styles,
        "solar_position(timestamps, latitude, longitude, timezone_offset_h=1.0)",
        "Berechnet Sonnenhöhe (Elevation) und Sonnenazimut für eine Liste "
        "von Zeitpunkten. Basis: Deklination und Zeitgleichung nach Spencer "
        "(1971).",
        inputs=[
            ("timestamps", "list[datetime]",
             "Liste der Auswertungszeitpunkte (Lokalzeit)."),
            ("latitude", "float", "Breitengrad in Grad, positiv = Nord."),
            ("longitude", "float", "Längengrad in Grad, positiv = Ost."),
            ("timezone_offset_h", "float",
             "Zeitzonenversatz in Stunden. 1.0 = MEZ, 2.0 = MESZ. "
             "Mit detect_timezone_offset() automatisch bestimmbar."),
        ],
        outputs=[
            ("elevation_deg", "np.ndarray",
             "Sonnenhöhe über dem Horizont in Grad. Negativ → Sonne unter "
             "dem Horizont (Nacht)."),
            ("azimuth_deg", "np.ndarray",
             "Sonnenazimut in Grad. 0 = Nord, 90 = Ost, 180 = Süd, 270 = West."),
        ],
        notes="Rückgabe ist ein Tupel (elevation, azimuth).",
    )

    func_block(
        story, styles,
        "ghi_to_poa(ghi, solar_elevation_deg, solar_azimuth_deg, panel_tilt_deg, "
        "panel_azimuth_deg, albedo=0.2, doy=1, dni_override=None, dhi_override=None, "
        "model='perez')",
        "Transponiert die horizontale Globalstrahlung auf die geneigte "
        "Modulfläche. Das Ergebnis ist die nutzbare Einstrahlung in der "
        "Modulebene (POA).",
        inputs=[
            ("ghi", "np.ndarray", "Globalstrahlung horizontal in W/m²."),
            ("solar_elevation_deg", "np.ndarray",
             "Sonnenhöhe je Zeitschritt (aus solar_position())."),
            ("solar_azimuth_deg", "np.ndarray",
             "Sonnenazimut je Zeitschritt (aus solar_position())."),
            ("panel_tilt_deg", "float",
             "Modulneigung: 0° = horizontal, 90° = senkrecht."),
            ("panel_azimuth_deg", "float",
             "Modulausrichtung: 0 = N, 90 = O, 180 = S, 270 = W."),
            ("albedo", "float",
             "Bodenreflexion (typisch 0.2 für Wiese, 0.1 für Asphalt, "
             "0.8 für Schnee)."),
            ("doy", "int",
             "Tag des Jahres (1..366). Wird für die Exzentrizitäts-"
             "korrektur und das Perez-Modell benötigt."),
            ("dni_override", "np.ndarray | None",
             "Direkte Normalstrahlung in W/m², falls aus API bekannt. "
             "Default: aus GHI über DISC-Modell schätzen."),
            ("dhi_override", "np.ndarray | None",
             "Diffusstrahlung in W/m², ebenfalls optional."),
            ("model", "str",
             "Transpositionsmodell: 'perez' (anisotrop, Standard) oder "
             "'isotropic' (Liu &amp; Jordan)."),
        ],
        outputs=[
            ("rückgabe", "np.ndarray",
             "POA-Einstrahlung in W/m², gleiche Länge wie ghi. "
             "Werte ≥ 0."),
        ],
        notes="POA = Beam-Anteil (DNI·cos(AOI)) + Diffus-Anteil + Boden-"
              "Reflexion. Bei Modell 'perez' werden zusätzlich Circumsolar- "
              "und Horizont-Aufhellung berücksichtigt.",
    )

    func_block(
        story, styles,
        "estimate_pv_power(poa_w_m2, peak_power_kwp, module_efficiency=0.20, "
        "temp_coefficient=-0.004, cell_temperature_c=None, system_losses=0.14)",
        "Schätzt die elektrische PV-Leistung aus der POA-Einstrahlung. "
        "Optional mit Temperaturkorrektur über die Zelltemperatur.",
        inputs=[
            ("poa_w_m2", "np.ndarray",
             "POA-Einstrahlung in W/m² (z.B. aus ghi_to_poa())."),
            ("peak_power_kwp", "float",
             "Anlagen-Nennleistung in kWp (Wert vom Datenblatt unter STC)."),
            ("module_efficiency", "float",
             "Modulwirkungsgrad bei STC (typisch 0.18 bis 0.22). "
             "Wird in dieser Formulierung nur informativ mitgeführt — "
             "P_peak enthält den Wirkungsgrad bereits."),
            ("temp_coefficient", "float",
             "Temperaturkoeffizient der Leistung in 1/K. Typisch -0.004 "
             "(d.h. -0.4 % pro Kelvin über 25 °C)."),
            ("cell_temperature_c", "np.ndarray | None",
             "Zelltemperatur je Zeitschritt in °C. Wenn None, wird keine "
             "Temperaturkorrektur angewendet."),
            ("system_losses", "float",
             "Pauschale Systemverluste (Wechselrichter, Verkabelung, "
             "Mismatch, Verschmutzung). Default 0.14 = 14 %."),
        ],
        outputs=[
            ("rückgabe", "np.ndarray",
             "Wechselrichter-Wirkleistung in kW, gedeckelt auf peak_power_kwp."),
        ],
    )

    func_block(
        story, styles,
        "estimate_cell_temperature(ambient_temp_c, poa_w_m2, "
        "wind_speed_m_s=None, noct=45.0)",
        "Schätzt die PV-Zelltemperatur nach dem NOCT-Modell, optional mit "
        "Windkühlung. T_cell = T_amb + (NOCT-20)/800 · POA.",
        inputs=[
            ("ambient_temp_c", "np.ndarray", "Umgebungstemperatur in °C."),
            ("poa_w_m2", "np.ndarray", "POA-Einstrahlung in W/m²."),
            ("wind_speed_m_s", "np.ndarray | None",
             "Windgeschwindigkeit in m/s — höhere Werte senken T_cell."),
            ("noct", "float",
             "Nominal Operating Cell Temperature in °C, vom Datenblatt. "
             "Default 45 °C (gängig für kristalline Module)."),
        ],
        outputs=[
            ("rückgabe", "np.ndarray", "Zelltemperatur je Zeitschritt in °C."),
        ],
    )

    func_block(
        story, styles,
        "detect_timezone_offset(date)",
        "Erkennt für ein gegebenes Datum, ob in Deutschland MEZ (1 h) oder "
        "MESZ (2 h) gilt. Reine Datumsarithmetik nach der EU-"
        "Sommerzeitregel (letzter Sonntag im März bzw. Oktober).",
        inputs=[
            ("date", "date", "Datum, für das der Offset gewünscht ist."),
        ],
        outputs=[
            ("rückgabe", "float",
             "1.0 für MEZ (Winter), 2.0 für MESZ (Sommer)."),
        ],
    )

    # 3.2 Beispiel-Pipeline
    story.append(Paragraph("3.2 Beispiel — komplette PV-Tagesprognose",
                           styles["H2"]))
    story.append(Paragraph(
        "<font face='Courier'>"
        "import datetime, numpy as np<br/>"
        "from weather import fetch_weather_forecast<br/>"
        "from solar import (solar_position, ghi_to_poa,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;estimate_cell_temperature, estimate_pv_power,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;detect_timezone_offset)<br/>"
        "<br/>"
        "date = datetime.date(2026, 5, 17)<br/>"
        "lat, lon = 49.33, 12.11<br/>"
        "tz = detect_timezone_offset(date)<br/>"
        "<br/>"
        "wx = fetch_weather_forecast(lat, lon, date, num_steps=96)<br/>"
        "ts = wx['timestamp'].tolist()<br/>"
        "<br/>"
        "elev, azim = solar_position(ts, lat, lon, tz)<br/>"
        "poa = ghi_to_poa(wx['ghi_w_m2'].values, elev, azim,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;panel_tilt_deg=30, panel_azimuth_deg=180,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;doy=date.timetuple().tm_yday,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;dni_override=wx['dni_w_m2'].values,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;dhi_override=wx['dhi_w_m2'].values)<br/>"
        "<br/>"
        "t_cell = estimate_cell_temperature(wx['temperature_c'].values,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;poa, wx['wind_speed_m_s'].values)<br/>"
        "power_kw = estimate_pv_power(poa, peak_power_kwp=10.0,<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;cell_temperature_c=t_cell)"
        "</font>",
        styles["Body"],
    ))

    # ============================================================
    # Anhang
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("Anhang A — Abhängigkeiten &amp; Installation",
                           styles["H1"]))
    story.append(Paragraph(
        "Die drei Module brauchen außer der Python-Standardbibliothek nur "
        "drei Pakete von PyPI:",
        styles["Body"],
    ))
    rows = [
        ["Paket", "Modul", "Wofür"],
        ["numpy", "prices, weather, solar", "Numerische Arrays, Vektor-Operationen."],
        ["pandas", "prices, weather", "DataFrames, Resampling der Wetterdaten."],
        ["requests", "prices, weather",
         "HTTP-Aufrufe an Energy-Charts und Open-Meteo."],
    ]
    t = Table(rows, colWidths=[3.5*cm, 5*cm, 8*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Courier-Bold"),
        ("FONTNAME", (1, 1), (1, -1), "Courier"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#F2F6FB"), colors.HexColor("#FFFFFF")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Installation per pip:",
        styles["Body"],
    ))
    story.append(Paragraph(
        "<font face='Courier'>pip install numpy pandas requests</font>",
        styles["Body"],
    ))

    story.append(Paragraph("Anhang B — APIs", styles["H1"]))
    story.append(Paragraph(
        "<b>Energy-Charts (Fraunhofer ISE)</b> — "
        "<font face='Courier'>https://api.energy-charts.info/price</font><br/>"
        "Liefert die EPEX-Day-Ahead-Preise für mehrere europäische "
        "Gebotszonen. Keine Registrierung, keine Limits für moderate "
        "Anfragen. Antwortet als JSON mit Unix-Zeitstempeln und Preisen "
        "in EUR/MWh.",
        styles["Body"],
    ))
    story.append(Paragraph(
        "<b>Open-Meteo</b> — "
        "<font face='Courier'>https://api.open-meteo.com/v1/forecast</font><br/>"
        "Wetter- und Strahlungsprognose für jeden Punkt der Welt. Stündliche "
        "Auflösung, bis zu 16 Tage in die Zukunft. Auch hier keine "
        "Registrierung nötig. Antwortet als JSON.",
        styles["Body"],
    ))

    story.append(Paragraph(
        "Wenn man einmal größere Mengen abruft (etwa Backtests über ein "
        "ganzes Jahr), empfiehlt sich Caching auf der Festplatte, damit "
        "wiederholte Aufrufe nicht jedes Mal die API belasten.",
        styles["Body"],
    ))

    story.append(Paragraph("Anhang C — Konventionen", styles["H1"]))
    story.append(Paragraph(
        "• Alle Energie-Werte in <b>kW</b> bzw. <b>kWh</b> (nicht W).<br/>"
        "• Strahlung in <b>W/m²</b>.<br/>"
        "• Temperaturen in <b>°C</b>.<br/>"
        "• Preise in <b>ct/kWh</b> (Ausnahme: API-Rohwerte in EUR/MWh).<br/>"
        "• Azimut-Konvention: 0 = Nord, 90 = Ost, 180 = Süd, 270 = West "
        "(meteorologisch, im Uhrzeigersinn).<br/>"
        "• Zeitachsen werden in Lokalzeit (MEZ/MESZ) geführt; "
        "Zeitzonenversatz über <i>detect_timezone_offset()</i> bestimmen.",
        styles["Body"],
    ))

    return story


def main(out_path: Path) -> None:
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=2.0*cm, rightMargin=2.0*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="EMOS Light — Datenmodule prices/solar/weather",
        author="EMOS Light Projektgruppe",
    )
    story = build_story(styles)
    doc.build(story)
    print(f"PDF erzeugt: {out_path}")


def _resolve_desktop() -> Path:
    """Findet den richtigen Desktop-Pfad (OneDrive bevorzugt, sonst lokal)."""
    home = Path.home()
    candidates = [
        home / "OneDrive" / "Desktop",
        home / "OneDrive - Personal" / "Desktop",
        home / "Desktop",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Kein Desktop-Ordner gefunden.")


if __name__ == "__main__":
    desktop = _resolve_desktop()
    out = desktop / "emos_data_modules" / "README_datenmodule.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    main(out)
