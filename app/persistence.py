from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StateStore:
    """Univerzální persistentní úložiště stavu pro AnyGate služby.

    Každá služba dostane vlastní JSON soubor v ``data_dir``.
    Zápis je atomický (tempfile + os.replace), takže data se nikdy
    nerozbijí ani při výpadku proudu uprostřed zápisu.
    """

    def __init__(self, service_name: str, data_dir: str = "data") -> None:
        self._path = Path(data_dir) / f"{service_name}_state.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, data: dict[str, Any]) -> None:
        """Atomicky uloží stav na disk."""
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=f".{self._path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self) -> dict[str, Any] | None:
        """Načte poslední snapshot, nebo None pokud neexistuje."""
        if not self._path.exists():
            return None
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Nelze načíst persistentní stav z %s: %s", self._path, exc)
            return None

    def clear(self) -> None:
        """Smaže persistentní stav."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass
