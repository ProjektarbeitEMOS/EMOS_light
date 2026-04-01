"""Basisklasse fuer alle EMOS-Komponenten."""

from abc import ABC, abstractmethod
from typing import Any


class Component(ABC):
    """Abstrakte Basisklasse fuer alle Energiekomponenten."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.enabled = config.get("enabled", True)

    @abstractmethod
    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt PuLP-Optimierungsvariablen. Returns dict of variable lists."""

    @abstractmethod
    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Constraints zum PuLP-Modell hinzu."""

    def __repr__(self) -> str:
        status = "aktiv" if self.enabled else "deaktiviert"
        return f"{self.__class__.__name__}(name={self.name!r}, {status})"
