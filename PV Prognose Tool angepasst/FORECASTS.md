# PV-Prognose-Kontext: EMOS, EMOS_light, HTW PVprog und pvprog-best

Dieses Dokument beschreibt die vier im Projekt untersuchten PV-Prognoseverfahren,
ihre Gemeinsamkeiten und Unterschiede sowie einen Hybrid-Ansatz, der die
jeweiligen Staerken kombiniert.

Anlage: beliebig viele Dachflaechen aus `data/surfaces.json`,
`PV_SURFACES_FILE` oder `PV_SURFACES_JSON`. Die bisherige Ost/West-Anlage
ist nur der mitgelieferte Beispiel-Default.
Standort: per Konfiguration (`PV_LATITUDE`, `PV_LONGITUDE`), Default
48.52 N / 13.30 E. Wetterdaten: Open-Meteo (Archive ERA5 / Forecast API).

---

## 1. Die vier Algorithmen im Ueberblick

### A) EMOS (klassisch)
- **Transposition:** Liu & Jordan (1963), **isotroper** Himmel
- **Dekomposition:** DISC (Maxwell 1987) schaetzt DNI und DHI aus GHI
- **Art der Prognose:** wetterbasiert (Day-Ahead bis mehrere Tage)
- **Quelle:** bestehender Produktiv-Code (EMOS)
- **Modul:** `algorithms/emos_solar_isotropic.py`

### B) EMOS_light (Perez)
- **Transposition:** Perez (1990), **anisotrop** (Zirkumsolar + Horizont-Aufhellung, 8 Epsilon-Bins)
- **Dekomposition:** entfaellt – nutzt API-DNI/DHI direkt (Open-Meteo liefert bereits DNI, DHI)
- **Art der Prognose:** wetterbasiert (Day-Ahead bis mehrere Tage)
- **Quelle:** neues EMOS-light Projekt (15-Personen-Team)
- **Modul:** `algorithms/emos_light_solar_perez.py`

### C) HTW PVprog
- **Prinzip:** Persistenz / messwertbasiert
  1. Rollierend wird ein **Klar-Himmel-Hue** `p_pvmax(t)` aus den letzten 10 Tagen aufgebaut (max-Envelope)
  2. Wetterlagenindex `k_TF = E_real / E_max` ueber die letzten 30 min
  3. Prognose: `p_pvf(t+h) = k_TF(t) * p_pvmax(t+h)` fuer h = 1..tf_prog_h
- **Autoren:** Bergner, Weniger, Tjaden (HTW Berlin, 2016)
- **Art der Prognose:** Kurzfrist / Nowcast (Stunden, nicht Tage)
- **Quelle:** MATLAB-Original, nach Python portiert
- **Modul:** `algorithms/htw_prog4pv.py`

### D) pvprog-best
- **Transposition:** Perez (wie EMOS_light)
- **Korrektur:** globaler Kalibrierfaktor **k = 0.84** (Energy-Ratio-Methode auf 20 Trainingstagen)
- **Art der Prognose:** wetterbasiert, empirisch getuned
- **Modul:** `pv_forecast.py` (`pv_forecast`, `calibrate_from_history`)
- `k` beruecksichtigt reale Verluste: Soiling, Spektral, Verschattung, Inverter-Clipping, MPPT-Verluste, Alterung ueber die nominalen 85 % hinaus.

---

## 2. Gemeinsamkeiten

| Block | Umsetzung |
|---|---|
| Sonnenstand | Spencer (1971) Declination + Equation of Time, identisch in A / B / D |
| Airmass | Kasten (1966) |
| Zelltemperatur | NOCT-Modell (45 C) mit Windkorrektur |
| Anlagenmodell | Multi-Flaechen-Summe aus Konfiguration/Schnittstelle, linearer Temperaturkoeffizient -0.4 %/K |
| System-Wirkungsgrad | 85 % (MPPT + Inverter + Leitung) |
| Zeitraster | 15-min fuer HTW, stuendlich fuer EMOS-Varianten (interpolierbar) |
| Input PV-real | InfluxDB `Gesamterzeugung` (15-min aggregiert) |

---

## 3. Unterschiede

| Eigenschaft | EMOS | EMOS_light | HTW PVprog | pvprog-best |
|---|---|---|---|---|
| Transposition | **iso** | Perez | n/a | Perez |
| DNI/DHI | DISC aus GHI | API | n/a | API |
| Wetterabh. | ja | ja | **nein (Messwerte)** | ja |
| Kalibrierung | keine | keine | keine | **k = 0.84** |
| Horizont | Day-Ahead | Day-Ahead | Nowcast–4 h | Day-Ahead |
| Staerke | einfach | physikalisch besser | praezise kurzfristig | bester Mittelwert |
| Schwaeche | iso-Naeherung | keine Kalibrierung | braucht Live-Daten | schlecht bei Wolkeneffekten |

---

## 4. Metriken (Test-Set: letztes Drittel von 30 Tagen)

Nennleistung 18 500 W.

### Wetterbasierte Day-Ahead-Prognose
| Algorithmus | MAE [W] | RMSE [W] | nRMSE [%] | Bias [W] | R² |
|---|---:|---:|---:|---:|---:|
| EMOS (iso) | 1 090 | 2 080 | 11.24 | +510 | +0.55 |
| EMOS_light (Perez) | 1 080 | 2 050 | 11.08 | +465 | +0.56 |
| **pvprog-best (k=0.84)** | **870** | **1 620** | **8.77** | **+60** | **+0.63** |

### HTW PVprog (messwertbasiert, verschiedene Horizonte)
| Horizont | MAE [W] | nRMSE [%] | R² |
|---|---:|---:|---:|
| 15 min | 810 | 7.13 | +0.69 |
| 1 h | 1 050 | 8.80 | +0.55 |
| 4 h | 1 520 | 11.90 | +0.30 |
| 24 h | 1 980 | 14.40 | +0.03 |

**Fazit:** HTW ist bei h < 2 h das beste Verfahren, fuer laenger gilt pvprog-best.

---

## 5. Beispiel-Tage

### Sonniger Tag mit Cloud-Enhancement (2026-04-20, 83 kWh bis Abend)
Ueberirradianz durch Reflexion an Cumulus-Wolkenkanten – Open-Meteo unterschaetzt:
| Algorithmus | Tagesenergie | Abweichung |
|---|---:|---:|
| EMOS (iso) | 77.4 | -7 % |
| EMOS_light (Perez) | 74.2 | -11 % |
| pvprog-best | 65.0 | -22 % |
| HTW Intraday | 83.1 | +0 % |

### Stark bewoelkter Tag (2026-04-14, 12.5 kWh)
Dichte Bedeckung – Open-Meteo liefert zu optimistisches GHI:
| Algorithmus | Tagesenergie | Abweichung |
|---|---:|---:|
| EMOS (iso) | 35.7 | +185 % |
| EMOS_light (Perez) | 36.3 | +190 % |
| pvprog-best | 30.5 | +143 % |
| HTW Intraday | 12.5 | +0 % |

**Kernbeobachtung:** Die Fehler der wetterbasierten Verfahren stammen
ueberwiegend aus dem **GHI-Input** (Open-Meteo/ERA5), nicht aus der
Transposition. Eine Korrektur am Transpositionsmodell loest das nicht –
aber eine Live-Korrektur mit Messwerten (HTW) tut es.

---

## 6. Hybrid-Loesung

### Motivation
- pvprog-best ist unschlagbar fuer **Day-Ahead-Planung** (Speicherfuehrung, Energiemarkt-Gebote, Last-Shifting).
- HTW ist unschlagbar fuer **kurzfristige Reaktion** (Eigenverbrauch, Batterie-SoC, Regelstrategie) und korrigiert Wetterfehler.

### Horizontabhaengiger Mischer
```
p_final(t+h) = w(h) * p_HTW(t+h) + (1 - w(h)) * p_pvprog-best(t+h)
```

mit einer glatten Gewichtung, z. B.:
```
w(h) = exp(-h / h0),   h0 ~ 2 h
```

| Horizont h | w(h) HTW | (1-w) pvprog-best |
|---|---:|---:|
| 15 min | 0.94 | 0.06 |
| 1 h | 0.61 | 0.39 |
| 2 h | 0.37 | 0.63 |
| 4 h | 0.14 | 0.86 |
| 24 h | 0.00 | 1.00 |

### Praktische Umsetzung
1. **Offline/einmalig:** `calibrate_from_history` liefert `k` fuer pvprog-best.
2. **Alle 15 min (Live):**
   a) Neue Messwerte aus InfluxDB holen.
   b) HTW-Lauf mit `tf_prog_h = 6` h auf aktualisiertem Puffer.
   c) pvprog-best-Lauf ueber Rest-Tag + Folgetag.
   d) Beide in 15-min-Raster mischen per `w(h)`.
3. **Fallback:** Fehlen Live-Daten laenger als 30 min, degeneriert das Ergebnis automatisch zu reiner pvprog-best-Prognose (w -> 0 wird erzwungen).

### Erweiterungsideen
- **Clearness-abhaengige Kalibrierung** fuer pvprog-best: eigenes `k` fuer hohe vs. niedrige Clearness-Indices. Das wuerde die Cloud-Enhancement-Unterschaetzung und die Overcast-Ueberschaetzung simultan daempfen.
- **Bias-Tracker:** rollierendes `bias_w` der letzten 2 h zwischen pvprog-best und Messung als additiver Offset fuer die naechsten Stunden.
- **Ensemble-Varianz** als Unsicherheitsmass: wenn `p_HTW` und `p_pvprog-best` stark divergieren, ist die Prognose unsicher – nuetzlich fuer Speicher-Risikoregeln.

---

## 7. Dateien im Projekt

| Datei | Zweck |
|---|---|
| `pv_forecast.py` | Perez + Kalibrierung (API der finalen Prognose) |
| `algorithms/emos_solar_isotropic.py` | EMOS Liu&Jordan |
| `algorithms/emos_light_solar_perez.py` | EMOS_light Perez |
| `algorithms/htw_prog4pv.py` | HTW PVprog (Python-Port) |
| `fetch_data.py` | stuendl. Influx + Open-Meteo Archive |
| `fetch_data_15min.py` | 15-min Datenbasis fuer HTW |
| `compare.py` | 1:1 EMOS vs. EMOS_light |
| `evaluate_best.py` | Kalibrierung + Test pvprog-best |
| `evaluate_all.py` | 4er-Vergleich inkl. HTW |
| `forecast_today.py` | Tagesprognose (CLI: Datum als Argument) |
| `data/calibration.json` | persistente Kalibrierparameter |
| `data/eval_all_*.csv` | vollstaendiges Benchmark-Ergebnis |

---

## 8. Quellen

- Liu B. Y. H., Jordan R. C. (1963): *The long-term average performance of flat-plate solar energy collectors*
- Perez R. et al. (1990): *Modeling daylight availability and irradiance components from direct and global irradiance*
- Maxwell E. L. (1987): *A quasi-physical model for converting hourly global horizontal to direct normal insolation*, DISC-Modell, SERI/TR-215-3087
- Kasten F. (1966): *A new table and approximation formula for the relative optical air mass*
- Spencer J. W. (1971): *Fourier series representation of the position of the sun*
- Bergner J., Weniger J., Tjaden T. (2016): *PVprog-Algorithmus zur Prognose der PV-Leistung fuer netzdienliche Batteriesysteme*, HTW Berlin
