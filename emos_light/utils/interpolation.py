"""Bilineare 2D-Interpolation auf einem Tabellengitter.

Wird z.B. fuer das COP-Kennfeld der Waermepumpe verwendet
(Aussentemperatur x Vorlauftemperatur -> COP).
"""

import numpy as np


def interp_2d(
    x: np.ndarray,
    y: float,
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    z_grid: np.ndarray,
) -> np.ndarray:
    """Bilineare 2D-Interpolation auf einem regulaeren Gitter, mit Clamp am Rand.

    Args:
        x:      Array von x-Werten (Auswertungspunkte).
        y:      Skalarer y-Wert (Auswertungspunkt).
        x_grid: Stuetzstellen der x-Achse (sortiert, aufsteigend).
        y_grid: Stuetzstellen der y-Achse (sortiert, aufsteigend).
        z_grid: 2D-Matrix der Tabellenwerte (Form ``len(x_grid) x len(y_grid)``).

    Returns:
        Interpolierte Werte als 1D-numpy-Array (gleiche Laenge wie ``x``).

    Behavior:
        - Werte ausserhalb des Gitters werden auf den Rand geclamped
          (kein Extrapolieren).
        - Bei degenerierten Achsen (zwei identische Stuetzstellen)
          wird der jeweilige Gewicht 0 gesetzt.
    """
    x = np.atleast_1d(np.asarray(x, dtype=float))
    x_c = np.clip(x, x_grid[0], x_grid[-1])
    y_c = np.clip(y, y_grid[0], y_grid[-1])

    # x-Indizes (Vektor)
    ix = np.searchsorted(x_grid, x_c) - 1
    ix = np.clip(ix, 0, len(x_grid) - 2)

    # y-Index (skalar)
    iy = int(np.clip(np.searchsorted(y_grid, y_c) - 1, 0, len(y_grid) - 2))

    dx = x_grid[ix + 1] - x_grid[ix]
    dy = y_grid[iy + 1] - y_grid[iy]
    wx = np.where(dx > 0, (x_c - x_grid[ix]) / dx, 0.0)
    wy = (y_c - y_grid[iy]) / dy if dy > 0 else 0.0

    return (
        z_grid[ix, iy] * (1 - wx) * (1 - wy)
        + z_grid[ix + 1, iy] * wx * (1 - wy)
        + z_grid[ix, iy + 1] * (1 - wx) * wy
        + z_grid[ix + 1, iy + 1] * wx * wy
    )
