"""Sonnenstandsberechnung und PV-Ertragsmodell basierend auf Standort.

Berechnet den Sonnenstand (Hoehe, Azimut) fuer beliebige Koordinaten
und Zeitpunkte und konvertiert GHI in Plane-of-Array (POA)
Einstrahlung fuer geneigte PV-Module.

Algorithmen basieren auf:
- Spencer (1971): Deklination und Zeitgleichung
- Maxwell (1987): DISC-Modell fuer GHI -> DNI Dekomposition (Fallback)
- Perez (1990): Anisotropes Transpositionsmodell fuer Diffusstrahlung
"""

import datetime
import math

import numpy as np


# Physikalische Grenzen
_SOLAR_CONSTANT_W_M2 = 1370.0  # Solarkonstante (DISC verwendet 1370, nicht 1361)
_MIN_ELEVATION_DEG = 1.0        # Unter 1 Grad: kein nutzbarer PV-Ertrag
_MAX_ZENITH_DEG = 87.0          # DISC-Grenze: DNI = 0 fuer Zenith > 87 Grad
_MAX_AIRMASS = 12.0             # Maximale Luftmasse (Grenze aus DISC-Kalibrierung)
_MIN_COS_ZENITH = 0.065         # Minimum cos(zenith) fuer kt-Berechnung (pvlib-Default)


def solar_position(
    timestamps: list[datetime.datetime],
    latitude: float,
    longitude: float,
    timezone_offset_h: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Berechnet Sonnenhoehe und Sonnenazimut fuer gegebene Zeitpunkte.

    Args:
        timestamps: Liste von datetime-Objekten (Lokalzeit).
        latitude: Breitengrad in Grad (positiv = Nord).
        longitude: Laengengrad in Grad (positiv = Ost).
        timezone_offset_h: Zeitzonenoffset in Stunden (1 = MEZ, 2 = MESZ).

    Returns:
        Tuple (elevation_deg, azimuth_deg):
            elevation_deg: Sonnenhoehe ueber Horizont in Grad (negativ = unter Horizont).
            azimuth_deg: Sonnenazimut in Grad (0=Nord, 90=Ost, 180=Sued, 270=West).
    """
    lat_rad = math.radians(latitude)
    n = len(timestamps)
    elevation = np.zeros(n)
    azimuth = np.zeros(n)

    for i, ts in enumerate(timestamps):
        # Tag des Jahres
        doy = ts.timetuple().tm_yday

        # Deklination (Spencer, 1971)
        gamma = 2 * math.pi * (doy - 1) / 365.0
        decl = (
            0.006918
            - 0.399912 * math.cos(gamma)
            + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma)
            + 0.00148 * math.sin(3 * gamma)
        )

        # Zeitgleichung in Minuten (Spencer, 1971)
        eqt = 229.18 * (
            0.000075
            + 0.001868 * math.cos(gamma)
            - 0.032077 * math.sin(gamma)
            - 0.014615 * math.cos(2 * gamma)
            - 0.04089 * math.sin(2 * gamma)
        )

        # Wahre Sonnenzeit (True Solar Time)
        solar_time_min = (
            ts.hour * 60
            + ts.minute
            + ts.second / 60.0
            + eqt
            + 4.0 * (longitude - 15.0 * timezone_offset_h)
        )

        # Stundenwinkel (positiv = Nachmittag)
        hour_angle = math.radians((solar_time_min / 60.0 - 12.0) * 15.0)

        # Sonnenhoehe (elevation)
        sin_elev = (
            math.sin(lat_rad) * math.sin(decl)
            + math.cos(lat_rad) * math.cos(decl) * math.cos(hour_angle)
        )
        sin_elev = max(-1.0, min(1.0, sin_elev))
        elev_rad = math.asin(sin_elev)

        # Sonnenazimut
        cos_elev = math.cos(elev_rad)
        if cos_elev > 0.001:
            cos_az = (
                math.sin(decl) - math.sin(lat_rad) * sin_elev
            ) / (math.cos(lat_rad) * cos_elev)
            cos_az = max(-1.0, min(1.0, cos_az))
            az_rad = math.acos(cos_az)
            if hour_angle > 0:
                az_rad = 2 * math.pi - az_rad
        else:
            az_rad = math.pi  # Sonne unter Horizont -> Sued

        elevation[i] = math.degrees(elev_rad)
        azimuth[i] = math.degrees(az_rad)

    return elevation, azimuth


def _kasten_airmass(zenith_deg: float) -> float:
    """Relative Luftmasse nach Kasten (1966).

    Genauer als 1/cos(zenith) fuer grosse Zenitwinkel (> 80 Grad).

    AM = 1 / (cos(z) + 0.50572 * (96.07995 - z)^(-1.6364))

    Args:
        zenith_deg: Zenitwinkel in Grad.

    Returns:
        Relative Luftmasse (dimensionslos).
    """
    if zenith_deg >= 90.0:
        return _MAX_AIRMASS

    z = zenith_deg
    cos_z = math.cos(math.radians(z))
    denom = cos_z + 0.50572 * max(0.001, 96.07995 - z) ** (-1.6364)
    if denom <= 0:
        return _MAX_AIRMASS

    am = 1.0 / denom
    return min(am, _MAX_AIRMASS)


def _disc_kn(kt: float, am: float) -> float:
    """DISC-Kernalgorithmus: Berechnet Kn (direkte Klarheit) aus kt und Luftmasse.

    Basiert auf Maxwell (1987), implementiert nach pvlib-python.
    Kn = Knc - delta_Kn, wobei:
    - Knc: Clear-sky Kn (4th-order Polynom in Luftmasse)
    - delta_Kn: Abweichung (piecewise Polynome in kt + exp(c*am))

    Args:
        kt: Clearness Index (0 bis 1).
        am: Luftmasse (begrenzt auf _MAX_AIRMASS).

    Returns:
        Kn: Direkte Klarheit (dimensionslos, >= 0).
    """
    am = min(am, _MAX_AIRMASS)

    # Knc: Clear-sky Kn (Horner-Schema fuer 4th-order Polynom)
    knc = 0.866 + am * (-0.122 + am * (0.0121 + am * (-0.000653 + 1.4e-05 * am)))

    # delta_Kn: piecewise Polynome in kt, kombiniert mit exp(c * am)
    if kt <= 0.6:
        a = 0.512 + kt * (-1.56 + kt * (2.286 - 2.222 * kt))
        b = 0.37 + 0.962 * kt
        c = -0.28 + kt * (0.932 - 2.048 * kt)
    else:
        a = -5.743 + kt * (21.77 + kt * (-27.49 + 11.56 * kt))
        b = 41.4 + kt * (-118.5 + kt * (66.05 + 31.9 * kt))
        c = -47.01 + kt * (184.2 + kt * (-222.0 + 73.81 * kt))

    delta_kn = a + b * math.exp(c * am)
    kn = knc - delta_kn

    return max(0.0, kn)


def _disc_decomposition(
    ghi: float,
    cos_zenith: float,
    doy: int,
) -> tuple[float, float]:
    """DISC-Dekomposition: Berechnet DNI und DHI aus GHI (Maxwell 1987).

    Verwendet den DISC-Algorithmus mit Luftmasse-Korrektur.
    Vermeidet die problematische Division durch cos(zenith) der Erbs-Methode.

    Args:
        ghi: Global Horizontal Irradiance in W/m^2.
        cos_zenith: Kosinus des Zenitwinkels (= sin(elevation)).
        doy: Tag des Jahres (1-366).

    Returns:
        Tuple (dni, dhi) in W/m^2.
    """
    if ghi <= 0 or cos_zenith < _MIN_COS_ZENITH:
        return 0.0, 0.0

    # Extraterrestrische Strahlung mit Exzentrizitaetskorrektur (Spencer)
    gamma = 2 * math.pi * (doy - 1) / 365.0
    eccentricity = (
        1.00011
        + 0.034221 * math.cos(gamma)
        + 0.001280 * math.sin(gamma)
        + 0.000719 * math.cos(2 * gamma)
        + 0.000077 * math.sin(2 * gamma)
    )
    i0 = _SOLAR_CONSTANT_W_M2 * eccentricity

    # Clearness Index (begrenzt auf physikalisch sinnvollen Bereich)
    kt = ghi / (i0 * cos_zenith)
    kt = max(0.0, min(1.0, kt))

    # Zenitwinkel in Grad fuer Luftmasse
    zenith_deg = math.degrees(math.acos(max(0.0, min(1.0, cos_zenith))))

    # Luftmasse (Kasten 1966)
    am = _kasten_airmass(zenith_deg)

    # DISC: Direkte Klarheit Kn
    kn = _disc_kn(kt, am)

    # DNI = Kn * I0 (extraterrestrisch)
    dni = kn * i0

    # DNI = 0 bei Zenith > 87 Grad
    if zenith_deg > _MAX_ZENITH_DEG:
        dni = 0.0

    # DHI = GHI - DNI * cos(zenith) (Closure-Gleichung)
    dhi = max(0.0, ghi - dni * cos_zenith)

    return dni, dhi


# ============================================================
# Perez (1990) — Anisotropes Transpositionsmodell
# Koeffizienten: allsitescomposite1990 (Perez et al., 1990)
# ============================================================

_PEREZ_EPSILON_BINS = np.array([1.000, 1.065, 1.230, 1.500, 1.950, 2.800, 4.500, 6.200])

# F1-Koeffizienten (Circumsolar-Helligkeit): [f11, f12, f13] pro Bin
_PEREZ_F1 = np.array([
    [-0.0083,  0.5877, -0.0621],   # Bin 1: ε < 1.065 (stark bewoelkt)
    [ 0.1299,  0.6826, -0.1514],   # Bin 2
    [ 0.3297,  0.4869, -0.2211],   # Bin 3
    [ 0.5682,  0.1875, -0.2951],   # Bin 4
    [ 0.8730, -0.3920, -0.3616],   # Bin 5
    [ 1.1326, -1.2367, -0.4118],   # Bin 6
    [ 1.0602, -1.5999, -0.3589],   # Bin 7
    [ 0.6777, -0.3273, -0.2504],   # Bin 8: ε >= 6.200 (klar)
])

# F2-Koeffizienten (Horizont-Helligkeit): [f21, f22, f23] pro Bin
_PEREZ_F2 = np.array([
    [-0.0596,  0.0721, -0.0220],
    [-0.0189,  0.0660, -0.0289],
    [ 0.0554, -0.0640, -0.0261],
    [ 0.1089, -0.1519, -0.0140],
    [ 0.2256, -0.4620,  0.0012],
    [ 0.2878, -0.8230,  0.0559],
    [ 0.2642, -1.1272,  0.1311],
    [ 0.1561, -1.3765,  0.2506],
])

_PEREZ_KAPPA_DEG = 5.535e-6  # Grad^-3


def _perez_bin(epsilon: float) -> int:
    """Bestimmt den Perez-Epsilon-Bin-Index (0-7) fuer Sky Clearness."""
    for i in range(1, len(_PEREZ_EPSILON_BINS)):
        if epsilon < _PEREZ_EPSILON_BINS[i]:
            return i - 1
    return 7


def _perez_diffuse(
    dhi: float,
    dni: float,
    cos_zenith: float,
    zenith_rad: float,
    cos_aoi: float,
    tilt_rad: float,
    am: float,
    doy: int,
) -> float:
    """Perez (1990) anisotrope Diffusstrahlung auf geneigter Flaeche.

    Beruecksichtigt drei Komponenten:
      1. Isotroper Himmelshintergrund
      2. Circumsolar-Aufhellung (um die Sonnenscheibe)
      3. Horizont-Aufhellung

    POA_diff = DHI * [(1-F1)*(1+cos(β))/2 + F1*(a/b) + F2*sin(β)]

    Args:
        dhi: Diffuse Horizontal Irradiance [W/m²].
        dni: Direct Normal Irradiance [W/m²].
        cos_zenith: cos(Zenitwinkel).
        zenith_rad: Zenitwinkel [rad].
        cos_aoi: cos(Einfallswinkel) auf Modulflaeche (>= 0).
        tilt_rad: Modulneigung [rad].
        am: Luftmasse (Kasten).
        doy: Tag des Jahres.

    Returns:
        Diffuse Einstrahlung auf geneigter Flaeche [W/m²].
    """
    if dhi <= 0:
        return 0.0

    # Extraterrestrische Normalstrahlung (fuer Sky Brightness)
    gamma = 2.0 * math.pi * (doy - 1) / 365.0
    eccentricity = (
        1.00011
        + 0.034221 * math.cos(gamma)
        + 0.001280 * math.sin(gamma)
        + 0.000719 * math.cos(2 * gamma)
        + 0.000077 * math.sin(2 * gamma)
    )
    i0n = _SOLAR_CONSTANT_W_M2 * eccentricity

    # Sky Brightness (Δ)
    delta = max(0.0, dhi * am / i0n)

    # Sky Clearness (ε)
    zenith_deg = math.degrees(zenith_rad)
    kappa_term = _PEREZ_KAPPA_DEG * zenith_deg ** 3
    epsilon = ((dhi + dni) / dhi + kappa_term) / (1.0 + kappa_term)

    # Bin-Lookup und Koeffizienten
    b_idx = _perez_bin(epsilon)

    f1 = (_PEREZ_F1[b_idx, 0]
          + _PEREZ_F1[b_idx, 1] * delta
          + _PEREZ_F1[b_idx, 2] * zenith_rad)
    f1 = max(f1, 0.0)  # F1 physikalisch >= 0

    f2 = (_PEREZ_F2[b_idx, 0]
          + _PEREZ_F2[b_idx, 1] * delta
          + _PEREZ_F2[b_idx, 2] * zenith_rad)
    # F2 darf negativ sein (physikalisch korrekt)

    # a/b: Circumsolar-Geometrie
    a = max(0.0, cos_aoi)
    b = max(math.cos(math.radians(85.0)), cos_zenith)

    # Drei Diffus-Komponenten
    term_iso = (1.0 - f1) * (1.0 + math.cos(tilt_rad)) / 2.0
    term_circum = f1 * (a / b)
    term_horizon = f2 * math.sin(tilt_rad)

    poa_diffuse = dhi * (term_iso + term_circum + term_horizon)
    return max(poa_diffuse, 0.0)


def ghi_to_poa(
    ghi: np.ndarray,
    solar_elevation_deg: np.ndarray,
    solar_azimuth_deg: np.ndarray,
    panel_tilt_deg: float,
    panel_azimuth_deg: float,
    albedo: float = 0.2,
    doy: int = 1,
    dni_override: np.ndarray | None = None,
    dhi_override: np.ndarray | None = None,
) -> np.ndarray:
    """Konvertiert GHI zu POA (Plane-of-Array) Einstrahlung.

    Verwendet das Perez (1990) anisotrope Transpositionsmodell:
        POA = DNI * cos(AOI) + POA_diffuse_perez + GHI * albedo * (1-cos(tilt))/2

    DNI und DHI werden direkt aus API-Daten uebernommen (wenn vorhanden)
    oder ueber das DISC-Modell (Maxwell 1987) aus GHI geschaetzt.

    Args:
        ghi: Global Horizontal Irradiance in W/m^2.
        solar_elevation_deg: Sonnenhoehe in Grad.
        solar_azimuth_deg: Sonnenazimut in Grad (0=N, 180=S).
        panel_tilt_deg: Modulneigung in Grad (0=horizontal, 90=vertikal).
        panel_azimuth_deg: Modulausrichtung in Grad (0=N, 90=O, 180=S, 270=W).
        albedo: Bodenreflexion (Standard 0.2).
        doy: Tag des Jahres (1-366).
        dni_override: DNI aus API-Daten [W/m²] (optional, Fallback: DISC).
        dhi_override: DHI aus API-Daten [W/m²] (optional, Fallback: DISC).

    Returns:
        POA-Einstrahlung in W/m^2.
    """
    n = len(ghi)
    poa = np.zeros(n)

    tilt_rad = math.radians(panel_tilt_deg)
    panel_az_rad = math.radians(panel_azimuth_deg)

    # Bodenreflexion (konstant ueber alle Zeitschritte)
    ground_factor = albedo * (1.0 - math.cos(tilt_rad)) / 2.0

    for i in range(n):
        # Kein Ertrag bei Nacht oder sehr niedrigem Sonnenstand
        if ghi[i] <= 0 or solar_elevation_deg[i] < _MIN_ELEVATION_DEG:
            poa[i] = 0.0
            continue

        sun_elev_rad = math.radians(solar_elevation_deg[i])
        sun_az_rad = math.radians(solar_azimuth_deg[i])
        cos_zenith = math.sin(sun_elev_rad)  # cos(90-elev) = sin(elev)
        zenith_rad = math.pi / 2.0 - sun_elev_rad
        zenith_deg = math.degrees(zenith_rad)

        ghi_val = float(ghi[i])

        # DNI/DHI: API-Werte verwenden oder DISC-Fallback
        if (dni_override is not None and dhi_override is not None
                and (float(dni_override[i]) + float(dhi_override[i])) > 0):
            dni = float(dni_override[i])
            dhi = float(dhi_override[i])
        else:
            dni, dhi = _disc_decomposition(ghi_val, cos_zenith, doy)

        # Einfallswinkel (Angle of Incidence, AOI)
        cos_aoi = (
            math.sin(sun_elev_rad) * math.cos(tilt_rad)
            + math.cos(sun_elev_rad) * math.sin(tilt_rad)
            * math.cos(sun_az_rad - panel_az_rad)
        )
        cos_aoi = max(0.0, cos_aoi)

        # Luftmasse fuer Perez-Modell
        am = _kasten_airmass(zenith_deg)

        # Perez (1990) anisotropes Transpositionsmodell
        beam = dni * cos_aoi
        diffuse = _perez_diffuse(
            dhi, dni, cos_zenith, zenith_rad, cos_aoi, tilt_rad, am, doy,
        )
        ground_reflected = ghi_val * ground_factor

        poa[i] = beam + diffuse + ground_reflected

    return np.maximum(poa, 0.0)


def estimate_pv_power(
    poa_w_m2: np.ndarray,
    peak_power_kwp: float,
    module_efficiency: float = 0.20,
    temp_coefficient: float = -0.004,
    cell_temperature_c: np.ndarray | None = None,
    system_losses: float = 0.14,
) -> np.ndarray:
    """Schaetzt die PV-Leistung aus POA-Einstrahlung.

    P = P_peak * (POA / 1000) * temp_factor * (1 - losses)

    Args:
        poa_w_m2: POA-Einstrahlung in W/m^2.
        peak_power_kwp: Nennleistung der Anlage in kWp.
        module_efficiency: Modulwirkungsgrad bei STC (Standard 0.20 = 20%).
        temp_coefficient: Temperaturkoeffizient der Leistung (1/K, typisch -0.004).
        cell_temperature_c: Zelltemperatur in Grad C (optional).
        system_losses: Gesamte Systemverluste (Wechselrichter, Kabel, etc., Standard 14%).

    Returns:
        PV-Leistung in kW.
    """
    # Normierte Einstrahlung bezogen auf STC (1000 W/m^2)
    irradiance_ratio = poa_w_m2 / 1000.0

    # Temperaturkorrektur
    temp_factor = np.ones_like(poa_w_m2)
    if cell_temperature_c is not None:
        stc_temp = 25.0  # STC-Referenztemperatur
        temp_factor = 1.0 + temp_coefficient * (cell_temperature_c - stc_temp)
        temp_factor = np.clip(temp_factor, 0.5, 1.2)

    # PV-Leistung: kein Ertrag ueber Nennleistung moeglich
    power_kw = peak_power_kwp * irradiance_ratio * temp_factor * (1 - system_losses)
    power_kw = np.minimum(power_kw, peak_power_kwp)

    return np.maximum(power_kw, 0.0)


def estimate_cell_temperature(
    ambient_temp_c: np.ndarray,
    poa_w_m2: np.ndarray,
    wind_speed_m_s: np.ndarray | None = None,
    noct: float = 45.0,
) -> np.ndarray:
    """Schaetzt die PV-Zelltemperatur (NOCT-basiertes Modell).

    T_cell = T_amb + (NOCT - 20) / 800 * POA

    Mit optionaler Windkorrektur.

    Args:
        ambient_temp_c: Umgebungstemperatur in Grad C.
        poa_w_m2: POA-Einstrahlung in W/m^2.
        wind_speed_m_s: Windgeschwindigkeit in m/s (optional).
        noct: Nominal Operating Cell Temperature in Grad C (Standard 45).

    Returns:
        Zelltemperatur in Grad C.
    """
    # NOCT-basiertes Modell
    t_cell = ambient_temp_c + (noct - 20.0) / 800.0 * poa_w_m2

    # Windkorrektur (vereinfacht: staerkerer Wind kuehlt besser)
    if wind_speed_m_s is not None:
        wind_factor = np.clip(1.0 - 0.02 * wind_speed_m_s, 0.7, 1.0)
        t_cell = ambient_temp_c + (t_cell - ambient_temp_c) * wind_factor

    return t_cell


def detect_timezone_offset(date: datetime.date) -> float:
    """Erkennt den Zeitzonen-Offset fuer Deutschland (MEZ/MESZ).

    MESZ (Sommerzeit): Letzter Sonntag im Maerz 02:00 bis letzter Sonntag im Oktober 03:00.

    Args:
        date: Datum.

    Returns:
        Offset in Stunden (1 = MEZ, 2 = MESZ).
    """
    year = date.year

    # Letzter Sonntag im Maerz
    march_31 = datetime.date(year, 3, 31)
    days_since_sunday = (march_31.weekday() + 1) % 7
    mesz_start = march_31 - datetime.timedelta(days=days_since_sunday)

    # Letzter Sonntag im Oktober
    oct_31 = datetime.date(year, 10, 31)
    days_since_sunday = (oct_31.weekday() + 1) % 7
    mesz_end = oct_31 - datetime.timedelta(days=days_since_sunday)

    if mesz_start <= date < mesz_end:
        return 2.0  # MESZ
    return 1.0  # MEZ
