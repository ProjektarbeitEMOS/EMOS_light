# EMOS Light — Energiemanagement fuer Neubau

Vereinfachtes Energiemanagement- und Optimierungssystem (EMOS) fuer einen typischen Neubau mit Waermepumpe, Fussbodenheizung und Frischwassersystem.

## Komponenten

- **PV-Anlage** — Standortbasierte Ertragsprognose
- **Batteriespeicher** — MILP-optimierte Lade-/Entladesteuerung
- **Waermepumpe (SG-Ready)** — 4-Zustandsmodell als Optimierungsvariable
- **Fussbodenheizung** — Estrich als thermischer Speicher (~32 kWh nutzbar)
- **Frischwassersystem** — Warmwasser on-demand via Waermetauscher
- **Wallbox + E-Auto** — Ladezeitoptimierung mit Abfahrtsziel

## Thermische Topologie

```
                  +---> Fussbodenheizung ---> Estrich (therm. Speicher) ---> Raum
Waermepumpe ------+
                  +---> Warmwasserspeicher ---> Frischwasserstation ---> Brauchwasser
```

## Optimierung

- **MILP** (Mixed-Integer Linear Programming) mit PuLP/HiGHS
- **MPC** (Model Predictive Control) mit rollierendem Horizont
- **Dynamischer Strompreis** (Day-Ahead Boersenpreis + Tarifkomponenten)

## Installation

```bash
pip install -r requirements.txt
```

## Nutzung

### Streamlit Dashboard
```bash
streamlit run app.py
```

### Kommandozeile
```bash
python main.py                    # Morgen, synthetische Daten
python main.py --date 2026-04-15  # Bestimmtes Datum
python main.py --api              # Echte API-Daten
python main.py --mpc              # MPC-Modus
```
