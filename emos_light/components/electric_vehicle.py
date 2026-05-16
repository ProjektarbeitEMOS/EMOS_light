"""E-Auto Komponentenmodell fuer EMOS.

Beschreibt das Elektrofahrzeug, das ueber eine Wallbox geladen wird.
Das EV hat eigene Eigenschaften (Akkukapazitaet, aktueller SOC, Fahrprofil),
die von der Wallbox genutzt werden, um den Ladebedarf zu berechnen.
Reine Daten-/Konfigurations-Komponente — daher Component, nicht MILPComponent.
"""

from emos_light.components.base import Component


class ElectricVehicle(Component):
    """Elektrofahrzeug mit Akkuparametern und Fahrprofil.

    Wird mit einer Wallbox verknuepft. Das EV liefert die Informationen
    ueber Ladebedarf, Verfuegbarkeit und Akkuparameter.

    Config-Parameter:
        battery_capacity_kwh (float): Akkukapazitaet in kWh.
        current_soc (float): Aktueller Ladestand (0-1).
        target_soc (float): Gewuenschter Ladestand bei Abfahrt (0-1).
        min_soc (float): Minimaler erlaubter SOC (0-1).
        max_soc (float): Maximaler SOC (0-1), z.B. 0.8 fuer Akkuschonung.
        arrival_hour (int): Ankunftszeit (0-23).
        departure_hour (int): Abfahrtszeit (0-23).
        daily_distance_km (float): Taegliche Fahrstrecke in km.
        consumption_kwh_per_100km (float): Verbrauch in kWh/100km.
        onboard_charger_kw (float): Max. Ladeleistung des Onboard-Chargers (AC).
        dc_charging_capable (bool): DC-Schnellladen moeglich.
        v2h_capable (bool): Vehicle-to-Home faehig.
        v2h_min_soc (float): Minimaler SOC fuer V2H-Entladung.
        name_display (str): Anzeigename des Fahrzeugs.
    """

    # Typische Verbrauchswerte nach Fahrzeugklasse (kWh/100km)
    VEHICLE_CLASSES = {
        "kleinwagen": {"consumption": 14.0, "capacity": 40.0, "charger": 7.4},
        "kompakt": {"consumption": 16.0, "capacity": 58.0, "charger": 11.0},
        "mittelklasse": {"consumption": 18.0, "capacity": 75.0, "charger": 11.0},
        "suv": {"consumption": 21.0, "capacity": 85.0, "charger": 11.0},
        "transporter": {"consumption": 25.0, "capacity": 70.0, "charger": 11.0},
    }

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        vehicle_class = config.get("vehicle_class", "kompakt")
        defaults = self.VEHICLE_CLASSES.get(vehicle_class, self.VEHICLE_CLASSES["kompakt"])

        self.battery_capacity_kwh = config.get("battery_capacity_kwh", defaults["capacity"])
        self.current_soc = config.get("current_soc", 0.30)
        self.target_soc = config.get("target_soc", 0.80)
        self.min_soc = config.get("min_soc", 0.10)
        self.max_soc = config.get("max_soc", 1.0)
        self.arrival_hour = config.get("arrival_hour", 17)
        self.departure_hour = config.get("departure_hour", 7)
        self.daily_distance_km = config.get("daily_distance_km", 40.0)
        self.consumption_kwh_100km = config.get(
            "consumption_kwh_per_100km", defaults["consumption"]
        )
        self.onboard_charger_kw = config.get("onboard_charger_kw", defaults["charger"])
        self.dc_charging_capable = config.get("dc_charging_capable", False)
        self.v2h_capable = config.get("v2h_capable", False)
        self.v2h_min_soc = config.get("v2h_min_soc", 0.30)
        self.name_display = config.get("name_display", name)

    @property
    def energy_needed_kwh(self) -> float:
        """Benoetigte Ladeenergie in kWh (netto, am Akku)."""
        delta_soc = max(0.0, self.target_soc - self.current_soc)
        return delta_soc * self.battery_capacity_kwh

    @property
    def daily_consumption_kwh(self) -> float:
        """Taeglicher Energieverbrauch durch Fahren in kWh."""
        return self.daily_distance_km * self.consumption_kwh_100km / 100.0

    @property
    def v2h_available_kwh(self) -> float:
        """Fuer V2H verfuegbare Energie in kWh."""
        if not self.v2h_capable:
            return 0.0
        available_soc = max(0.0, self.current_soc - self.v2h_min_soc)
        return available_soc * self.battery_capacity_kwh

    def get_wallbox_config(self) -> dict:
        """Erzeugt ein Wallbox-kompatibles Config-Dict aus EV-Parametern.

        Wird verwendet, um eine Wallbox mit den EV-Daten zu konfigurieren.
        """
        return {
            "ev_battery_capacity_kwh": self.battery_capacity_kwh,
            "current_soc": self.current_soc,
            "target_soc": self.target_soc,
            "departure_hour": self.departure_hour,
            "arrival_hour": self.arrival_hour,
            "max_power_kw": self.onboard_charger_kw,
        }

