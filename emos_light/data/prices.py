"""Day-Ahead Strompreise abrufen und Endverbraucherpreise berechnen."""

import datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests


def calculate_consumer_price(
    spot_prices_ct_kwh: np.ndarray,
    tariff_config: dict,
) -> np.ndarray:
    """Berechnet den Endverbraucherpreis aus Boersenpreisen + Abgaben.

    Formel:
        Endpreis = (Boersenpreis + Aufschlag + Netzentgelt + Konzession
                    + Stromsteuer + Umlagen) x (1 + MwSt/100)

    Args:
        spot_prices_ct_kwh: Boersenpreise in ct/kWh (EPEX Spot Day-Ahead).
        tariff_config: Tarif-Konfiguration mit allen Preisbestandteilen.

    Returns:
        Array mit Endverbraucherpreisen in ct/kWh (brutto).
    """
    # Fixe Bestandteile (netto, ct/kWh)
    markup = tariff_config.get("provider_markup_ct_kwh", 2.15)
    grid_fee = tariff_config.get("grid_fee_ct_kwh", 9.26)
    concession = tariff_config.get("concession_fee_ct_kwh", 1.66)
    elec_tax = tariff_config.get("electricity_tax_ct_kwh", 2.05)
    kwkg = tariff_config.get("kwkg_surcharge_ct_kwh", 0.446)
    stromnev = tariff_config.get("stromnev_surcharge_ct_kwh", 1.559)
    offshore = tariff_config.get("offshore_surcharge_ct_kwh", 0.941)
    vat = tariff_config.get("vat_pct", 19.0)

    fixed_surcharges = grid_fee + concession + elec_tax + kwkg + stromnev + offshore
    vat_factor = 1.0 + vat / 100.0

    # Endpreis berechnen
    net_price = spot_prices_ct_kwh + markup + fixed_surcharges
    gross_price = net_price * vat_factor

    return np.round(gross_price, 3)


def get_surcharges_summary(tariff_config: dict) -> dict:
    """Gibt eine Zusammenfassung aller Preisbestandteile zurueck.

    Returns:
        Dict mit: fixed_netto, fixed_brutto, vat_pct, monthly_fees,
        breakdown (Liste aller Posten mit Name und Wert).
    """
    markup = tariff_config.get("provider_markup_ct_kwh", 2.15)
    grid_fee = tariff_config.get("grid_fee_ct_kwh", 9.26)
    concession = tariff_config.get("concession_fee_ct_kwh", 1.66)
    elec_tax = tariff_config.get("electricity_tax_ct_kwh", 2.05)
    kwkg = tariff_config.get("kwkg_surcharge_ct_kwh", 0.446)
    stromnev = tariff_config.get("stromnev_surcharge_ct_kwh", 1.559)
    offshore = tariff_config.get("offshore_surcharge_ct_kwh", 0.941)
    vat = tariff_config.get("vat_pct", 19.0)
    monthly_base = tariff_config.get("monthly_base_fee_eur", 5.99)
    monthly_grid = tariff_config.get("monthly_grid_fee_eur", 10.0)

    fixed_netto = markup + grid_fee + concession + elec_tax + kwkg + stromnev + offshore

    breakdown = [
        ("Anbieter-Aufschlag", markup),
        ("Netzentgelt", grid_fee),
        ("Konzessionsabgabe", concession),
        ("Stromsteuer", elec_tax),
        ("KWKG-Umlage", kwkg),
        ("§19 StromNEV-Umlage", stromnev),
        ("Offshore-Netzumlage", offshore),
    ]

    return {
        "fixed_netto_ct_kwh": round(fixed_netto, 3),
        "fixed_brutto_ct_kwh": round(fixed_netto * (1 + vat / 100), 3),
        "vat_pct": vat,
        "monthly_total_eur": monthly_base + monthly_grid,
        "breakdown": breakdown,
    }


def fetch_day_ahead_prices(
    date: Optional[datetime.date] = None,
    bidding_zone: str = "DE-LU",
) -> pd.DataFrame:
    """Ruft Day-Ahead-Strompreise von der Energy-Charts API ab.

    Verwendet die oeffentliche Energy-Charts API (Fraunhofer ISE).
    Als Fallback werden synthetische Preise generiert.

    Args:
        date: Datum fuer die Preise (Standard: morgen).
        bidding_zone: Gebotszone (Standard: DE-LU fuer Deutschland/Luxemburg).

    Returns:
        DataFrame mit Spalten ['timestamp', 'price_eur_mwh', 'price_ct_kwh'].
    """
    if date is None:
        date = datetime.date.today() + datetime.timedelta(days=1)

    try:
        return _fetch_from_api(date, bidding_zone)
    except Exception:
        return generate_synthetic_prices(date)


def _fetch_from_api(date: datetime.date, bidding_zone: str) -> pd.DataFrame:
    """Versucht Preise von der Energy-Charts API zu laden."""
    date_str = date.strftime("%Y-%m-%d")
    url = (
        f"https://api.energy-charts.info/price"
        f"?bzn={bidding_zone}&start={date_str}&end={date_str}"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    timestamps = [
        datetime.datetime.fromtimestamp(ts) for ts in data["unix_seconds"]
    ]
    prices = data["price"]  # EUR/MWh

    df = pd.DataFrame({
        "timestamp": timestamps,
        "price_eur_mwh": prices,
    })
    df["price_ct_kwh"] = df["price_eur_mwh"] / 10.0
    return df


def generate_synthetic_prices(
    date: datetime.date, num_steps: int = 96
) -> pd.DataFrame:
    """Generiert synthetische Day-Ahead-Preise fuer Tests.

    Typisches deutsches Tagesprofil mit:
    - Basispreis ~80 EUR/MWh
    - Morgen-Peak 6-9h: +40
    - Abend-Peak 17-21h: +50
    - Solar-Dip 11-15h: -30
    - Nacht-Tal 0-5h: -25
    - Zufaelliges Rauschen +/-5
    - Geclippt auf [-10, 300] EUR/MWh

    Args:
        date: Datum (wird als Seed fuer Reproduzierbarkeit verwendet).
        num_steps: Anzahl Zeitschritte (Standard: 96 = 15-min fuer 24h).

    Returns:
        DataFrame mit synthetischen Preisen.
    """
    hours = np.linspace(0, 24, num_steps, endpoint=False)

    # Basisprofil: typischer DE Day-Ahead Verlauf
    base_price = 80  # EUR/MWh Grundpreis

    # Morgen-Peak (6-9 Uhr)
    morning_peak = 40 * np.exp(-0.5 * ((hours - 7.5) / 1.5) ** 2)
    # Abend-Peak (17-21 Uhr)
    evening_peak = 50 * np.exp(-0.5 * ((hours - 19) / 2) ** 2)
    # Solar-Dip mittags (11-15 Uhr)
    solar_dip = -30 * np.exp(-0.5 * ((hours - 13) / 2) ** 2)
    # Nacht-Tal (0-5 Uhr)
    night_valley = -25 * np.exp(-0.5 * ((hours - 3) / 2.5) ** 2)

    prices = base_price + morning_peak + evening_peak + solar_dip + night_valley

    # Reproduzierbares Rauschen basierend auf Datum
    rng = np.random.default_rng(seed=int(date.strftime("%Y%m%d")))
    prices += rng.normal(0, 5, num_steps)
    prices = np.clip(prices, -10, 300)

    timestamps = [
        datetime.datetime.combine(date, datetime.time())
        + datetime.timedelta(minutes=int(i * 1440 / num_steps))
        for i in range(num_steps)
    ]

    df = pd.DataFrame({
        "timestamp": timestamps,
        "price_eur_mwh": np.round(prices, 2),
    })
    df["price_ct_kwh"] = np.round(df["price_eur_mwh"] / 10.0, 3)
    return df
