# EMOS Light — Energiemanagement fuer Neubau

Vereinfachtes Energiemanagement- und Optimierungssystem (EMOS) fuer einen typischen Neubau mit Waermepumpe, Fussbodenheizung und Frischwassersystem. 

---

## Schnellstart

### 1. Voraussetzungen

- **Python 3.10 oder neuer** ([python.org](https://www.python.org/downloads/) — bei Installation unter Windows „Add Python to PATH" anhaken)
- **Git** ([git-scm.com](https://git-scm.com/downloads))

Pruefen, ob alles da ist:
```bash
python --version
git --version
```

### 2. Repository klonen

```bash
git clone https://github.com/JakobKapsner/EMOS_light.git
cd EMOS_light
```

### 3. Virtuelle Umgebung anlegen (empfohlen)

So bleiben die Pakete vom System-Python getrennt.

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (cmd):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

> Falls PowerShell die Aktivierung blockiert: einmalig
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` ausfuehren.

### 4. Abhaengigkeiten installieren

```bash
pip install -r requirements.txt
```

### 5. Dashboard starten

```bash
streamlit run app.py
```

Browser oeffnet sich automatisch unter `http://localhost:8501`. Falls der Port belegt ist:
```bash
streamlit run app.py --server.port 8502
```

**Windows-Komfort:** Datei `start_emos_light.bat` mit folgendem Inhalt anlegen, dann reicht ein Doppelklick:
```bat
@echo off
cd /d "%~dp0"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502
```

---

## Was kann man im Dashboard?

- Komponenten an-/abschalten und konfigurieren (PV, Speicher, Waermepumpe, Wallbox, E-Auto, Heizung, …)
- Standort, Strompreis-Tarif, Wetter- und Lastprofil einstellen
- Optimierungsergebnisse als Zeitreihen und Kostentabelle ansehen
- Vergleich gegen ungeregelten Baseline-Betrieb

---

## Komponenten

- **PV-Anlage** — Standortbasierte Ertragsprognose (Perez-Transposition)
- **Batteriespeicher** — MILP-optimierte Lade-/Entladesteuerung inkl. Alterungskosten
- **Waermepumpe (SG-Ready)** — 4-Zustandsmodell als Optimierungsvariable, aroTHERM plus COP
- **Fussbodenheizung** — Estrich als thermischer Speicher (~32 kWh nutzbar)
- **Gebaeudespeicher** — Wand- und Luftspeicher mit Komforttemperatur-Grenzen
- **Frischwassersystem** — Warmwasser on-demand via Waermetauscher
- **Wallbox + E-Auto** — Ladezeitoptimierung mit Abfahrtsziel (Verbrauch in kWh/100km konfigurierbar)

## Thermische Topologie

```
                  +---> Fussbodenheizung ---> Estrich (therm. Speicher) ---> Raum
Waermepumpe ------+
                  +---> Warmwasserspeicher ---> Frischwasserstation ---> Brauchwasser
```

## Optimierung

- **MILP** (Mixed-Integer Linear Programming) mit PuLP / HiGHS
- **MPC** (Model Predictive Control) mit rollierendem Horizont
- **Dynamischer Strompreis** (Day-Ahead Boersenpreis + Tarifkomponenten)

---

## Kommandozeile (alternativ zum Dashboard)

```bash
python main.py                    # Morgen, synthetische Daten
python main.py --date 2026-04-15  # Bestimmtes Datum
python main.py --api              # Echte API-Daten
python main.py --mpc              # MPC-Modus
python main.py --config meine.yaml
python main.py --dashboard        # startet Streamlit
```

---

## Projektstruktur

```
EMOS_light/
├── app.py                  # Streamlit-Dashboard
├── main.py                 # CLI-Einstiegspunkt
├── requirements.txt
├── config/                 # YAML-Konfigurationen
└── emos_light/
    ├── components/         # PV, Batterie, WP, Wallbox, EV, …
    ├── optimization/       # MILP-Solver, MPC, Baseline
    └── core/               # Config-Loader, Szenario-Builder
```

---

## Mitarbeiten

1. Repo klonen, Branch anlegen: `git checkout -b feature/meine-aenderung`
2. Aenderung machen, lokal testen (`streamlit run app.py`)
3. Committen: `git commit -am "feat: kurze Beschreibung"`
4. Pushen: `git push -u origin feature/meine-aenderung`
5. Auf GitHub einen Pull Request gegen `main` aufmachen.

Neue Komponenten als eigenes Modul unter `emos_light/components/` anlegen und im Dashboard (`app.py`) konfigurierbar machen.

---

## Troubleshooting

| Problem | Loesung |
|---|---|
| `python` wird nicht gefunden (Windows) | Python neu installieren mit „Add to PATH" |
| `ModuleNotFoundError: streamlit` | venv aktiviert? `pip install -r requirements.txt` erneut |
| `Port 8501 is not available` | Anderen Port: `streamlit run app.py --server.port 8502` |
| PowerShell blockt venv-Aktivierung | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| HiGHS/PuLP-Fehler beim Solven | `pip install --upgrade highspy pulp` |
