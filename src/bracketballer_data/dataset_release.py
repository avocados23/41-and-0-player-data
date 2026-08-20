"""Dependency-free helpers shared by safe dataset publication commands."""

from __future__ import annotations

import hashlib
from pathlib import Path


def checksum_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(b"\0")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\n")
    return digest.hexdigest()


def validate_row_bounds(dataset: str, staged: int, active: int) -> dict[str, int | None]:
    lower = int(active * 0.5) if active else 1
    upper = int(active * 1.5) if active else None
    result = {
        "staged": staged,
        "previous_active": active,
        "minimum_expected": lower,
        "maximum_expected": upper,
    }
    if staged == 0:
        raise ValueError(f"{dataset} staged no rows")
    if active and not lower <= staged <= upper:
        raise ValueError(f"{dataset} failed row-count bounds: {result}")
    return result
