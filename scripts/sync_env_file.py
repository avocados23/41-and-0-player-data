#!/usr/bin/env python3
"""Create or safely update the local environment file used by the pipeline."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path


# Keep this list deliberately narrow.  In particular, do not merge every key
# from .env.example: DATABASE_URL takes precedence over the individual PSQL_*
# settings and could silently change an existing developer's database target.
SPACES_KEYS: tuple[str, ...] = (
    "DO_SPACES_REGION",
    "DO_SPACES_BUCKET",
    "DO_SPACES_ACCESS_KEY_ID",
    "DO_SPACES_SECRET_ACCESS_KEY",
)
SECRET_KEYS = {"DO_SPACES_ACCESS_KEY_ID", "DO_SPACES_SECRET_ACCESS_KEY"}
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _assigned_keys(contents: str) -> set[str]:
    keys: set[str] = set()
    for line in contents.splitlines():
        match = _KEY_RE.match(line.strip())
        if match:
            keys.add(match.group(1))
    return keys


def _example_values(contents: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in contents.splitlines():
        match = _KEY_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1)
        if key in SPACES_KEYS:
            values[key] = line.split("=", 1)[1].strip()
    missing = [key for key in SPACES_KEYS if key not in values]
    if missing:
        raise ValueError(f".env.example is missing required Spaces keys: {', '.join(missing)}")
    return values


def _current_values(contents: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in contents.splitlines():
        match = _KEY_RE.match(line.strip())
        if match:
            values[match.group(1)] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return values


def _write_private(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(contents)
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)
    path.chmod(0o600)


def sync_env_file(env_path: Path, example_path: Path) -> tuple[bool, list[str], list[str]]:
    """Create or update ``env_path`` and return changed, added, blank secrets."""

    if env_path.is_symlink():
        raise RuntimeError(f"refusing to modify symlinked environment file: {env_path}")
    if env_path.exists() and not env_path.is_file():
        raise RuntimeError(f"refusing to modify non-regular environment file: {env_path}")
    if not example_path.is_file():
        raise RuntimeError(f"missing environment template: {example_path}")

    example_contents = example_path.read_text(encoding="utf-8")
    example_values = _example_values(example_contents)
    if not env_path.exists():
        _write_private(env_path, example_contents)
        values = _current_values(example_contents)
        return True, list(SPACES_KEYS), [
            key for key in sorted(SECRET_KEYS) if not values.get(key)
        ]

    existing_contents = env_path.read_text(encoding="utf-8")
    existing_keys = _assigned_keys(existing_contents)
    added = [key for key in SPACES_KEYS if key not in existing_keys]
    updated_contents = existing_contents
    if added:
        suffix = "" if updated_contents.endswith("\n") else "\n"
        updated_contents += suffix + "\n# Optional private DigitalOcean Spaces publishing.\n"
        updated_contents += "\n".join(f"{key}={example_values[key]}" for key in added) + "\n"
        _write_private(env_path, updated_contents)
    else:
        # Existing files may have been created with a permissive umask.  Fix
        # the mode even when no content changes are needed.
        env_path.chmod(0o600)

    values = _current_values(updated_contents)
    blank_secrets = [
        key for key in sorted(SECRET_KEYS) if not values.get(key, "").strip()
    ]
    return bool(added), added, blank_secrets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--example-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        changed, added, blank_secrets = sync_env_file(args.env_file, args.example_file)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"sync-env: {error}", file=sys.stderr)
        return 1

    if changed:
        print(f"Updated {args.env_file} with missing Spaces settings: {', '.join(added)}")
    else:
        print(f"Kept existing values in {args.env_file}; enforced mode 600.")
    if blank_secrets:
        print(
            "sync-env: Spaces publishing remains disabled until these secrets are set: "
            + ", ".join(sorted(blank_secrets)),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
