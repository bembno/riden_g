"""Local storage for regularly captured JK BMS readings.

JSON Lines (one JSON object per line) is the primary format:

- append-only, safe against partial writes (a torn line is skippable)
- readable line-by-line with any tool (``jq``, ``grep``, pandas, ...)
- easy to rotate (rename the file; a new one starts automatically)

Example::

    from jkbms import JkBmsClient
    from jkbms.storage import JsonlStore

    store = JsonlStore("/home/pi/bms_data/readings.jsonl")
    for readings in JkBmsClient().poll_sync(interval=30):
        store.append(readings)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

from .models import JkReadings

PathLike = Union[str, os.PathLike]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JsonlStore:
    """Append-only JSONL store for :class:`JkReadings`.

    Each record is the flattened readings dict plus a ``"timestamp"`` key
    set at write time, so the file is self-describing and ordered even if
    the BMS clock or reader restarts.

    ``sections`` selects which parts are stored (default: all received);
    e.g. ``sections=("cell",)`` keeps files small for high-frequency logging.
    """

    def __init__(self, path: PathLike, *, sections: Optional[Iterable[str]] = None,
                 ensure_ascii: bool = False) -> None:
        self.path = Path(path)
        self.sections = tuple(sections) if sections is not None else None
        self.ensure_ascii = ensure_ascii

    def _record(self, readings: JkReadings) -> Dict[str, Any]:
        data = readings.to_dict()
        if self.sections is not None:
            data = {k: v for k, v in data.items() if k in self.sections}
        data["timestamp"] = readings.timestamp or _now()
        return data

    def append(self, readings: JkReadings) -> Path:
        """Append one readings record; returns the store path."""
        line = json.dumps(self._record(readings), ensure_ascii=self.ensure_ascii)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return self.path

    def extend(self, readings_iter: Iterable[JkReadings]) -> int:
        """Append many records in one file open; returns the count written."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with self.path.open("a", encoding="utf-8") as f:
            for readings in readings_iter:
                f.write(json.dumps(self._record(readings),
                                   ensure_ascii=self.ensure_ascii) + "\n")
                n += 1
        return n

    def read(self) -> List[Dict[str, Any]]:
        """Load all valid records (skipping torn/partial lines)."""
        out = []
        for rec in self.iter():
            out.append(rec)
        return out

    def iter(self) -> Iterator[Dict[str, Any]]:
        """Iterate records from disk, skipping unparsable lines."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield out

    def count(self) -> int:
        """Number of parsable records in the file."""
        n = 0
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    json.loads(line)
                    n += 1
                except json.JSONDecodeError:
                    continue
        return n

    def rotate(self) -> Optional[Path]:
        """Rename the file to ``<name>-<timestamp>.jsonl`` and start fresh.

        Returns the rotated path, or None when there was nothing to rotate.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.path.with_name(f"{self.path.stem}-{stamp}.jsonl")
        os.replace(self.path, target)
        return target
