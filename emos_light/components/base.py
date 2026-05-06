"""Basisklassen fuer EMOS-Komponenten.

Zwei Stufen:

* ``Component`` — minimale Basis. Nur Name, Config und enabled-Flag.
  Geeignet fuer reine Daten-Provider (PV, Building, ElectricVehicle,
  FreshWaterStation), die keine eigenen MILP-Variablen oder Constraints
  beisteuern.

* ``MILPComponent`` — erweitert ``Component`` um die Pflicht, Variablen
  und Constraints zum PuLP-Modell beizusteuern. Fuer Batterie, WP,
  Pufferspeicher, FBH, Wallbox.

Hinweis: Bisher hat ``Component`` *alle* Komponenten gezwungen, leere
``get_optimization_variables``/``add_constraints``-Stubs zu definieren.
Diese leeren Stubs bleiben aus Rueckwaertskompatibilitaet weiter erlaubt
(passive Komponenten erben einfach von ``Component`` und implementieren
sie nicht mehr).
"""

from abc import ABC, abstractmethod
from typing import Any


class Component(ABC):
    """Abstrakte Basisklasse fuer alle Energiekomponenten.

    Stellt die Grundattribute ``name``, ``config`` und ``enabled`` bereit.
    Eigene MILP-Variablen oder -Constraints werden hier *nicht* erwartet —
    Komponenten, die das brauchen, erben von :class:`MILPComponent`.
    """

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.enabled = config.get("enabled", True)

    def __repr__(self) -> str:
        status = "aktiv" if self.enabled else "deaktiviert"
        return f"{self.__class__.__name__}(name={self.name!r}, {status})"


class MILPComponent(Component):
    """Komponente, die zur MILP-Optimierung Variablen und Constraints liefert.

    Zusaetzlich zu den Variablen und Constraints kann eine Komponente ihren
    Beitrag zur **elektrischen Knotenbilanz** und zur **Waermebilanz** an
    eine bestimmte Senke selbst beisteuern. Dafuer existieren die drei
    Methoden :meth:`electrical_supply`, :meth:`electrical_demand` und
    :meth:`heat_supply`. Jede liefert pro Zeitschritt einen
    PuLP-kompatiblen Ausdruck (LpAffineExpression, LpVariable oder Zahl);
    Default ist 0, sodass nicht-elektrische bzw. waermefreie Komponenten
    nichts ueberschreiben muessen.

    Konventionen:
      - Vorzeichen positiv: ``electrical_supply`` ist Energie aus Sicht des
        AC-Knotens hinein (PV-Erzeugung, Batterie-Entladung).
      - ``electrical_demand`` ist Energie heraus (Last, HP, Wallbox,
        Batterie-Laden).
      - ``heat_supply(sink=...)`` liefert die thermische Leistung an eine
        konkret benannte Senke. Senken-Namen werden vom Optimizer
        gepflegt (aktuell ``"floor"`` fuer FBH-Estrich und ``"ww"`` fuer
        Warmwasserspeicher).
    """

    @abstractmethod
    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt PuLP-Optimierungsvariablen.

        Returns:
            Dict mit Variablenlisten. Keys werden vom Optimierer
            unter ``variables`` weitergereicht.
        """

    @abstractmethod
    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Constraints zum PuLP-Modell hinzu."""

    # ------------------------------------------------------------------
    # Bilanz-Beitraege (Default: 0). Komponenten ueberschreiben, was sie
    # tatsaechlich beisteuern.
    # ------------------------------------------------------------------

    def electrical_supply(self, variables: dict, t: int) -> Any:
        """Beitrag dieser Komponente zur elektrischen Supply-Seite (kW)."""
        return 0.0

    def electrical_demand(self, variables: dict, t: int) -> Any:
        """Beitrag dieser Komponente zur elektrischen Demand-Seite (kW)."""
        return 0.0

    def heat_supply(self, variables: dict, t: int, sink: str) -> Any:
        """Beitrag dieser Komponente zur Waermezufuhr an die Senke ``sink`` (kW).

        ``sink`` ist ein semantischer Bezeichner der Waermesenke
        (z.B. ``"floor"``, ``"ww"``). Komponenten, die mehrere Senken
        bedienen koennen (z.B. die Waermepumpe), entscheiden hier,
        welcher Ausdruck zurueckkommt.
        """
        return 0.0

    def heat_demand(self, variables: dict, t: int, sink: str) -> Any:
        """Beitrag dieser Komponente zur Waermebedarf-Seite der Senke (kW).

        Waermesenken (z.B. Estrich, Pufferspeicher) liefern hier den
        Ausdruck, der den ``Q_in``-Beitrag in die Senken-Bilanz
        einbringt. Komponenten, die selbst Senken sind, setzen
        :attr:`heat_sink_id`.
        """
        return 0.0

    # ------------------------------------------------------------------
    # Optionale Setup-Methoden — Default ist no-op
    # ------------------------------------------------------------------

    def prepare(self, inp: Any) -> None:
        """Optionaler Hook: erlaubt Vorberechnungen mit den Eingabedaten.

        Wird vom Optimizer einmalig vor :meth:`get_optimization_variables`
        aufgerufen. Default: nichts tun. Die Waermepumpe nutzt das z.B.
        zur Berechnung der COP-Zeitreihen.
        """

    def set_active_heat_sinks(self, sinks: set) -> None:
        """Optionaler Hook: teilt der Komponente die aktiven Waermesenken mit.

        Wird vom Optimizer nach Konstruktion der Komponentenliste
        aufgerufen, bevor Variablen erzeugt werden. Komponenten, die
        Waerme an mehrere Senken verteilen (Waermepumpe), brauchen
        diese Information, um interne Aufteilungs-Variablen zu erzeugen.
        """

    @property
    def heat_sink_id(self) -> str | None:
        """Bezeichner dieser Komponente als Waermesenke (z.B. ``"floor"``).

        Komponenten, die Waermesenken sind, ueberschreiben dies.
        Default ``None`` = keine Senke.
        """
        return None

    @property
    def is_heat_supplier(self) -> bool:
        """True, wenn die Komponente Waerme fuer mind. eine Senke liefert.

        Wird vom Optimizer benutzt, um zu entscheiden, ob Waermesenken
        ueberhaupt sinnvoll ins Modell eingebunden werden — eine UFH
        ohne Waermeerzeuger waere ein abgekoppelter Knoten und macht
        das Problem schnell infeasible. Default False, HP ueberschreibt.
        """
        return False

    @property
    def is_par14a_curtailable(self) -> bool:
        """True, wenn die Komponente unter §14a EnWG drosselbar ist.

        Aktuell trifft das auf WP und Wallboxen zu (steuerbare
        Verbrauchseinrichtungen i.S.d. §14a). Batterie und Haushaltslast
        sind ausgenommen. Default False, betroffene Komponenten
        ueberschreiben.
        """
        return False


__all__ = ["Component", "MILPComponent"]
