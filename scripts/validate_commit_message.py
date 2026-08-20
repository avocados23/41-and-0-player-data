#!/usr/bin/env python3
"""Validate issue-linked commit subjects for local hooks and CI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


SUBJECT_PATTERN = re.compile(r"^#[1-9]\d* \S(?:.*\S)?$")


def valid_subject(subject: str) -> bool:
    return subject.startswith("Merge ") or bool(SUBJECT_PATTERN.fullmatch(subject))


def validate(subjects: list[tuple[str, str]]) -> int:
    invalid = [(label, subject) for label, subject in subjects if not valid_subject(subject)]
    if not invalid:
        return 0
    print('commit-message: ordinary commits must use "#<issue-id> <issue title>".', file=sys.stderr)
    for label, subject in invalid:
        print(f"  {label}: {subject!r}", file=sys.stderr)
    return 1


def subjects_from_message(path: Path) -> list[tuple[str, str]]:
    first_line = path.read_text(encoding="utf-8").splitlines()[:1]
    return [("received", first_line[0] if first_line else "")]


def subjects_from_range(value: str) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x09%s", value],
        check=True,
        capture_output=True,
        text=True,
    )
    subjects = []
    for line in result.stdout.splitlines():
        commit, _, subject = line.partition("\t")
        subjects.append((commit[:12], subject))
    return subjects


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path)
    group.add_argument("--range")
    args = parser.parse_args()
    try:
        subjects = (
            subjects_from_message(args.file)
            if args.file is not None
            else subjects_from_range(args.range)
        )
        return validate(subjects)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"commit-message: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
