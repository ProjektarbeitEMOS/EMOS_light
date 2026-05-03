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
    """Komponente, die zur MILP-Optimierung Variablen und Constraints liefert."""

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


__all__ = ["Component", "MILPComponent"]
