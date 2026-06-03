"""Command line wrapper for YAML based EMOS scenario tests."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from emos_light.testing.scenario_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
