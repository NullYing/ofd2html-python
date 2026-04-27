"""Virtual OFD container: in-memory view of an OFD ZIP archive.

Load the ZIP once, expose entries by virtual path (POSIX-style, optionally
leading ``/``).
"""

from __future__ import annotations

import io
import zipfile
from typing import Iterable


class OFDContainer:
    """In-memory view of an OFD ZIP archive."""

    def __init__(self, ofd_bytes: bytes) -> None:
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(ofd_bytes), "r")
        except zipfile.BadZipFile as exc:  # pragma: no cover - explicit boundary
            raise ValueError(f"not a valid OFD/ZIP file: {exc}") from exc
        # Normalise paths: drop leading slash, collapse backslashes.
        self._entries: dict[str, zipfile.ZipInfo] = {
            self._norm(info.filename): info
            for info in self._zip.infolist()
            if not info.is_dir()
        }

    @staticmethod
    def _norm(path: str) -> str:
        return path.replace("\\", "/").lstrip("/")

    def has(self, path: str) -> bool:
        return self._norm(path) in self._entries

    def read(self, path: str) -> bytes:
        key = self._norm(path)
        info = self._entries.get(key)
        if info is None:
            raise FileNotFoundError(f"OFD entry not found: {path}")
        return self._zip.read(info)

    def names(self) -> Iterable[str]:
        return self._entries.keys()

    def close(self) -> None:
        self._zip.close()

    # Context manager sugar.
    def __enter__(self) -> "OFDContainer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
