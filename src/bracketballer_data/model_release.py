"""Dependency-free validation for atomic shooting-model publication."""

from __future__ import annotations


def validate_release_counts(counts: dict[str, int]) -> None:
    profiles = counts["ability_profiles"]
    if profiles == 0:
        raise ValueError("Candidate model has no ability profiles")
    if counts["zone_profiles"] != profiles * 4:
        raise ValueError(
            "Candidate model is incomplete: expected four zone profiles "
            f"per ability profile, got {counts['zone_profiles']} for {profiles}"
        )
    if counts["contextual_profiles"] != profiles:
        raise ValueError(
            "Candidate model is incomplete: contextual profile count does not "
            f"match ability profiles ({counts['contextual_profiles']} != {profiles})"
        )
    if counts["game_profiles"] < profiles:
        raise ValueError(
            "Candidate model is incomplete: at least one game profile is "
            f"required per ability profile ({counts['game_profiles']} < {profiles})"
        )
