"""PV-Anlage Komponentenmodell fuer EMOS.

Berechnet die PV-Erzeugung standortbasiert mit Sonnenstandsberechnung,
POA-Transposition und Temperaturkorrektur. Keine Optimierungsvariablen,
da die Erzeugung ein gegebener Input ist — daher Component, nicht MILPComponent.
"""

import datetime

import numpy as np

from emos_light.components.base import Component
from emos_light.data.solar import (
    solar_position,
    ghi_to_poa,
    estimate_pv_power,
    estimate_cell_temperature,
    detect_timezone_offset,
)


class PVSystem(Component):
    """Photovoltaik-Anlage mit standortbasierter Ertragsprognose.

    Berechnet den PV-Ertrag basierend auf:
    - Standort (Breitengrad, Laengengrad) -> Sonnenstand
    - Modulausrichtung (Neigung, Azimut) -> POA-Einstrahlung
    - Temperaturkorrektur (NOCT-basiert)
    - Systemverluste (Wechselrichter, Kabel, Verschmutzung)
    - Altersdegradation

    Config-Parameter:
        peak_power_kwp (float): Nennleistung in kWp.
        tilt_deg (float): Neigungswinkel in Grad (0=horizontal, optimal ~30-35 fuer DE).
        azimuth_deg (float): Azimutwinkel in Grad (0=Nord, 90=Ost, 180=Sued, 270=West).
        system_efficiency (float): Systemwirkungsgrad inkl. Wechselrichter (0-1).
        age_years (float): Alter der Anlage in Jahren.
        degradation_rate_per_year (float): Jaehrliche Degradationsrate (z.B. 0.005).
        temp_coefficient (float): Temperaturkoeffizient in 1/K (Standard: -0.004).
        noct (float): Nominal Operating Cell Temperature in Grad C (Standard: 45).
        albedo (float): Bodenreflexion (Standard: 0.2).
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.peak_power_kwp = config.get("peak_power_kwp", 10.0)
        self.tilt_deg = config.get("tilt_deg", 35.0)
        # Azimut: 0=Nord, 90=Ost, 180=Sued, 270=West (Standardkonvention)
        self.azimuth_deg = config.get("azimuth_deg", 180.0)
        self.system_efficiency = config.get(
            "system_efficiency", config.get("efficiency", 0.85)
        )
        self.age_years = config.get("age_years", 0.0)
        self.degradation_rate = config.get(
            "degradation_rate_per_year",
            config.get("degradation_pct_per_year", 0.5) / 100.0,
        )
        self.temp_coefficient = config.get("temp_coefficient", -0.004)
        self.noct = config.get("noct", 45.0)
        self.albedo = config.get("albedo", 0.2)

    def _degradation_factor(self) -> float:
        """Berechnet den Degradationsfaktor basierend auf dem Anlagenalter."""
        return (1.0 - self.degradation_rate) ** self.age_years

    def estimate_generation(
        self,
        ghi_series: np.ndarray,
        timestamps: list[datetime.datetime] | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        ambient_temp_c: np.ndarray | None = None,
        wind_speed_m_s: np.ndarray | None = None,
        dni_series: np.ndarray | None = None,
        dhi_series: np.ndarray | None = None,
    ) -> np.ndarray:
        """Schaetzt die PV-Erzeugung standortbasiert.

        Wenn Standortdaten (timestamps, lat, lon) vorhanden sind, wird
        die vollstaendige Sonnenstandsberechnung mit POA-Transposition
        und Temperaturkorrektur verwendet. Andernfalls Fallback auf
        vereinfachtes Modell.

        Args:
            ghi_series: Globalstrahlung (GHI) in W/m^2.
            timestamps: Zeitstempel (fuer Sonnenstandsberechnung).
            latitude: Breitengrad des Standorts.
            longitude: Laengengrad des Standorts.
            ambient_temp_c: Umgebungstemperatur in Grad C (optional).
            wind_speed_m_s: Windgeschwindigkeit in m/s (optional).
            dni_series: DNI aus API [W/m²] (optional, Fallback: DISC).
            dhi_series: DHI aus API [W/m²] (optional, Fallback: DISC).

        Returns:
            PV-Erzeugung in kW.
        """
        if timestamps is not None and latitude is not None and longitude is not None:
            return self._estimate_location_based(
                ghi_series, timestamps, latitude, longitude,
                ambient_temp_c, wind_speed_m_s, dni_series, dhi_series,
            )
        return self._estimate_simple(ghi_series)

    def _estimate_location_based(
        self,
        ghi_series: np.ndarray,
        timestamps: list[datetime.datetime],
        latitude: float,
        longitude: float,
        ambient_temp_c: np.ndarray | None = None,
        wind_speed_m_s: np.ndarray | None = None,
        dni_series: np.ndarray | None = None,
        dhi_series: np.ndarray | None = None,
    ) -> np.ndarray:
        """Standortbasierte PV-Ertragsberechnung mit Sonnenstand und POA."""
        # Zeitzonenoffset erkennen
        tz_offset = detect_timezone_offset(timestamps[0].date())

        # Sonnenstand berechnen
        sun_elevation, sun_azimuth = solar_position(
            timestamps, latitude, longitude, tz_offset
        )

        # GHI -> POA-Einstrahlung (Perez-Modell mit optionalen API-DNI/DHI)
        doy = timestamps[0].timetuple().tm_yday
        poa = ghi_to_poa(
            ghi_series, sun_elevation, sun_azimuth,
            self.tilt_deg, self.azimuth_deg, self.albedo, doy,
            dni_override=dni_series, dhi_override=dhi_series,
        )

        # Zelltemperatur schaetzen
        cell_temp = None
        if ambient_temp_c is not None:
            cell_temp = estimate_cell_temperature(
                ambient_temp_c, poa, wind_speed_m_s, self.noct
            )

        # Systemverluste = 1 - system_efficiency (z.B. 0.85 -> 15% Verluste)
        system_losses = 1.0 - self.system_efficiency

        # PV-Leistung berechnen
        power_kw = estimate_pv_power(
            poa, self.peak_power_kwp,
            temp_coefficient=self.temp_coefficient,
            cell_temperature_c=cell_temp,
            system_losses=system_losses,
        )

        # Degradation anwenden
        power_kw *= self._degradation_factor()

        return np.maximum(power_kw, 0.0)

    def _estimate_simple(self, ghi_series: np.ndarray) -> np.ndarray:
        """Vereinfachtes Modell (Fallback ohne Standortdaten)."""
        ghi_stc = 1000.0
        normalized_ghi = ghi_series / ghi_stc
        correction = self._degradation_factor() * self.system_efficiency
        generation_kw = self.peak_power_kwp * normalized_ghi * correction
        return np.maximum(generation_kw, 0.0)
