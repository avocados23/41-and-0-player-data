"""Compute versioned defensive characteristics from CBBD game-lineup data.

The command is a dry run unless --apply is supplied. Activating the inferred
scheme label requires a manually measured validation precision of at least 0.80;
otherwise use --disable-scheme-label to publish only measurable traits and
DROP_COMPATIBLE_BIG.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
from psycopg2.extras import Json, execute_values

from bracketballer_data.database import connection_dsn, load_env_file
from bracketballer_data.defensive_characteristics import (
    MODEL_CONFIGURATION,
    PlayerDefensiveEvidence,
    score_characteristics,
)
from bracketballer_data.import_audit import (
    begin_import_run,
    mark_failed,
    mark_validated,
    pipeline_commit,
)

from bracketballer_data.paths import REPO_ROOT


def nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def shooting(stats: dict[str, Any], shot_type: str) -> tuple[float, float]:
    return (
        number(nested(stats, shot_type, "made")),
        number(nested(stats, shot_type, "attempted")),
    )


def lineup_metrics(lineup: dict[str, Any]) -> dict[str, float]:
    aggregate = Aggregate()
    aggregate.add(
        game_id=lineup["game_id"],
        game_date=lineup["game_date"],
        stats=lineup["opponent_stats"],
        defense_rating=lineup["defense_rating"],
        opponent_offense_rating=lineup["opponent_offense_rating"],
    )
    return aggregate.metrics()


def teammate_adjusted_effects(
    lineups: list[dict[str, Any]],
    *,
    ridge_penalty: float = 25.0,
) -> dict[tuple[int, str], float]:
    """Regularized lineup regression that separates teammate combinations."""
    player_ids = sorted(
        {
            player["player_id"]
            for lineup in lineups
            for player in lineup["players"]
        }
    )
    if not player_ids or not lineups:
        return {}
    player_index = {
        player_id: index for index, player_id in enumerate(player_ids)
    }
    design = np.zeros((len(lineups), len(player_ids)), dtype=float)
    weights = np.ones(len(lineups), dtype=float)
    metric_rows: list[dict[str, float]] = []
    for row_index, lineup in enumerate(lineups):
        for player in lineup["players"]:
            design[row_index, player_index[player["player_id"]]] = 1.0
        weights[row_index] = max(
            1.0,
            number(lineup["opponent_stats"].get("possessions")),
        )
        metric_rows.append(lineup_metrics(lineup))

    weighted_design = design * np.sqrt(weights)[:, None]
    system = (
        weighted_design.T @ weighted_design
        + ridge_penalty * np.eye(len(player_ids))
    )
    effects: dict[tuple[int, str], float] = {}
    for metric in metric_rows[0]:
        outcomes = np.array([row[metric] for row in metric_rows], dtype=float)
        mean = float(np.average(outcomes, weights=weights))
        target = (outcomes - mean) * np.sqrt(weights)
        coefficients = np.linalg.solve(system, weighted_design.T @ target)
        coefficients -= coefficients.mean()
        for player_id, coefficient in zip(player_ids, coefficients):
            effects[(player_id, metric)] = float(coefficient)
    return effects


@dataclass
class Aggregate:
    possessions: float = 0
    field_goal_attempts: float = 0
    interior_attempts: float = 0
    interior_makes: float = 0
    jumper_attempts: float = 0
    offensive_rebound_weight: float = 0
    turnover_weight: float = 0
    free_throw_weight: float = 0
    adjusted_defense_weight: float = 0
    games: set[int] = field(default_factory=set)
    data_through: date | None = None

    def add(
        self,
        *,
        game_id: int,
        game_date: date,
        stats: dict[str, Any],
        defense_rating: float,
        opponent_offense_rating: float,
    ) -> None:
        possessions = number(stats.get("possessions"))
        field_goal_attempts = number(nested(stats, "fieldGoals", "attempted"))
        interior_makes = interior_attempts = 0.0
        two_pointers = stats.get("twoPointers") or {}
        for key in ("layups", "dunks", "tipIns"):
            made, attempted = shooting(two_pointers, key)
            interior_makes += made
            interior_attempts += attempted
        _, jumper_attempts = shooting(two_pointers, "jumpers")
        four = stats.get("fourFactors") or {}
        self.possessions += possessions
        self.field_goal_attempts += field_goal_attempts
        self.interior_makes += interior_makes
        self.interior_attempts += interior_attempts
        self.jumper_attempts += jumper_attempts
        self.offensive_rebound_weight += (
            possessions * number(four.get("offensiveReboundPct"))
        )
        self.turnover_weight += possessions * number(four.get("turnoverRatio"))
        self.free_throw_weight += possessions * number(four.get("freeThrowRate"))
        self.adjusted_defense_weight += possessions * (
            defense_rating - opponent_offense_rating
        )
        self.games.add(game_id)
        if self.data_through is None or game_date > self.data_through:
            self.data_through = game_date

    def metrics(self) -> dict[str, float]:
        possessions = max(1.0, self.possessions)
        attempts = max(1.0, self.field_goal_attempts)
        return {
            "interior_attempt_rate": self.interior_attempts / attempts,
            "interior_accuracy": (
                self.interior_makes / self.interior_attempts
                if self.interior_attempts > 0
                else 0.5
            ),
            "jumper_attempt_rate": self.jumper_attempts / attempts,
            "opponent_offensive_rebound_pct": (
                self.offensive_rebound_weight / possessions
            ),
            "opponent_turnover_rate": self.turnover_weight / possessions,
            "opponent_free_throw_rate": self.free_throw_weight / possessions,
            "adjusted_defense_rating": (
                self.adjusted_defense_weight / possessions
            ),
        }


def load_evidence(
    conn: Any,
    first_season: int,
    last_season: int,
) -> list[PlayerDefensiveEvidence]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                lineup.id, lineup.game_id, lineup.team_id, lineup.season,
                lineup.defense_rating, lineup.total_seconds,
                lineup.opponent_stats,
                game.start_date::date,
                CASE WHEN game.home_team_id = lineup.team_id
                     THEN game.away_team_id ELSE game.home_team_id END AS opponent_id,
                opponent.offense_rating AS opponent_offense_rating,
                lineup_player.player_id,
                membership.height,
                ARRAY(
                    SELECT position::text
                    FROM team_roster_position_maps position_map
                    WHERE position_map.roster_membership_id = membership.id
                    ORDER BY position
                ) AS positions,
                season.games AS season_games,
                season.minutes, season.fouls,
                defensive.blk_pct, defensive.stl_pct, defensive.dr_pct,
                defensive.dporpag, defensive.dbpm
            FROM team_game_lineups lineup
            JOIN college_games game ON game.id = lineup.game_id
            JOIN team_game_lineup_players lineup_player
              ON lineup_player.lineup_id = lineup.id
            LEFT JOIN team_roster_memberships membership
              ON membership.player_id = lineup_player.player_id
             AND membership.team_id = lineup.team_id
             AND membership.season = lineup.season
            LEFT JOIN player_seasons season
              ON season.player_id = lineup_player.player_id
             AND season.team_id = lineup.team_id
             AND season.season = lineup.season
            LEFT JOIN player_defensive_stats defensive
              ON defensive.torvik_id = season.torvik_id
             AND defensive.season = season.season
            LEFT JOIN opponent_team_season_contexts opponent
              ON opponent.team_id = CASE
                     WHEN game.home_team_id = lineup.team_id
                     THEN game.away_team_id ELSE game.home_team_id
                 END
             AND opponent.season = lineup.season
            JOIN team_season_eligibility eligibility
              ON eligibility.team_id = lineup.team_id
             AND eligibility.season = lineup.season
            WHERE lineup.season BETWEEN %s AND %s
            ORDER BY lineup.id, lineup_player.ordinal
            """,
            (first_season, last_season),
        )
        rows = cursor.fetchall()

    lineups: dict[int, dict[str, Any]] = {}
    player_metadata: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in rows:
        (
            lineup_id,
            game_id,
            team_id,
            season,
            defense_rating,
            total_seconds,
            opponent_stats,
            game_date,
            _opponent_id,
            opponent_offense_rating,
            player_id,
            height,
            positions,
            season_games,
            minutes,
            fouls,
            block_pct,
            steal_pct,
            dr_pct,
            dporpag,
            dbpm,
        ) = row
        lineup = lineups.setdefault(
            lineup_id,
            {
                "game_id": game_id,
                "team_id": team_id,
                "season": season,
                "defense_rating": number(defense_rating),
                "total_seconds": number(total_seconds),
                "opponent_stats": opponent_stats,
                "game_date": game_date,
                "opponent_offense_rating": number(
                    opponent_offense_rating,
                    number(defense_rating),
                ),
                "players": [],
            },
        )
        lineup["players"].append(
            {
                "player_id": player_id,
                "height": number(height) if height is not None else None,
                "positions": set(positions or []),
            }
        )
        player_metadata[(player_id, team_id, season)] = {
            "season_games": int(season_games or 0),
            "minutes": number(minutes),
            "fouls": number(fouls),
            "block_pct": number(block_pct) if block_pct is not None else None,
            "steal_pct": number(steal_pct) if steal_pct is not None else None,
            "dr_pct": number(dr_pct) if dr_pct is not None else None,
            "dporpag": number(dporpag) if dporpag is not None else None,
            "dbpm": number(dbpm) if dbpm is not None else None,
            "height": number(height) if height is not None else None,
        }

    player_on: dict[tuple[int, int, int], Aggregate] = defaultdict(Aggregate)
    player_center_possessions: dict[tuple[int, int, int], float] = defaultdict(float)
    grouped_lineups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    team_game_seconds: dict[tuple[int, int, int], float] = defaultdict(float)
    for lineup in lineups.values():
        stats = lineup["opponent_stats"]
        possessions = number(stats.get("possessions"))
        maximum_height = max(
            (
                player["height"]
                for player in lineup["players"]
                if player["height"] is not None
            ),
            default=None,
        )
        add_options = {
            "game_id": lineup["game_id"],
            "game_date": lineup["game_date"],
            "stats": stats,
            "defense_rating": lineup["defense_rating"],
            "opponent_offense_rating": lineup["opponent_offense_rating"],
        }
        grouped_lineups[(lineup["team_id"], lineup["season"])].append(lineup)
        team_game_seconds[
            (lineup["team_id"], lineup["season"], lineup["game_id"])
        ] += lineup["total_seconds"]
        for player in lineup["players"]:
            key = (
                player["player_id"],
                lineup["team_id"],
                lineup["season"],
            )
            player_on[key].add(**add_options)
            position_fit = bool(player["positions"] & {"PF", "C"})
            height_fit = (
                maximum_height is not None
                and player["height"] is not None
                and player["height"] >= maximum_height - 2
            )
            if position_fit or height_fit:
                player_center_possessions[key] += possessions

    adjusted_effects: dict[tuple[int, int, int, str], float] = {}
    for (team_id, season), rows_for_team in grouped_lineups.items():
        for (player_id, metric), effect in teammate_adjusted_effects(
            rows_for_team
        ).items():
            adjusted_effects[(player_id, team_id, season, metric)] = effect

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT eligibility.team_id, eligibility.season, count(*)::int
            FROM team_season_eligibility eligibility
            JOIN college_games game
              ON game.season = eligibility.season
             AND (
                 game.home_team_id = eligibility.team_id
                 OR game.away_team_id = eligibility.team_id
             )
            WHERE eligibility.season BETWEEN %s AND %s
              AND lower(game.status) = 'final'
            GROUP BY eligibility.team_id, eligibility.season
            """,
            (first_season, last_season),
        )
        finalized_game_counts = {
            (team_id, season): count
            for team_id, season, count in cursor.fetchall()
        }

    evidence: list[PlayerDefensiveEvidence] = []
    for key, aggregate in player_on.items():
        player_id, team_id, season = key
        metadata = player_metadata[key]
        on = aggregate.metrics()
        effect = {
            metric: adjusted_effects.get(
                (player_id, team_id, season, metric),
                0.0,
            )
            for metric in on
        }
        season_games = metadata["season_games"]
        games = len(aggregate.games)
        minutes = metadata["minutes"]
        finalized_games = finalized_game_counts.get((team_id, season), 0)
        ingested_games = {
            game_id
            for candidate_team, candidate_season, game_id in team_game_seconds
            if candidate_team == team_id and candidate_season == season
        }
        finalized_game_coverage = (
            min(1.0, len(ingested_games) / finalized_games)
            if finalized_games > 0
            else 0.0
        )
        lineup_coverage = (
            sum(
                min(
                    1.0,
                    team_game_seconds[(team_id, season, game_id)] / 2400.0,
                )
                for game_id in ingested_games
            )
            / finalized_games
            if finalized_games > 0
            else 0.0
        )
        evidence.append(
            PlayerDefensiveEvidence(
                player_id=player_id,
                team_id=team_id,
                season=season,
                games=games,
                season_games=season_games,
                possessions=aggregate.possessions,
                center_role_share=(
                    player_center_possessions[key] / aggregate.possessions
                    if aggregate.possessions
                    else 0
                ),
                height=metadata["height"],
                block_pct=metadata["block_pct"],
                steal_pct=metadata["steal_pct"],
                defensive_rebound_pct=metadata["dr_pct"],
                dporpag=metadata["dporpag"],
                dbpm=metadata["dbpm"],
                fouls_per40=(
                    40 * metadata["fouls"] / minutes if minutes > 0 else None
                ),
                interior_attempt_rate_delta=(
                    effect["interior_attempt_rate"]
                ),
                interior_accuracy_delta=(
                    effect["interior_accuracy"]
                ),
                jumper_attempt_rate_delta=(
                    effect["jumper_attempt_rate"]
                ),
                opponent_offensive_rebound_pct_delta=(
                    effect["opponent_offensive_rebound_pct"]
                ),
                opponent_turnover_rate_delta=(
                    effect["opponent_turnover_rate"]
                ),
                opponent_free_throw_rate_delta=(
                    effect["opponent_free_throw_rate"]
                ),
                adjusted_defense_rating_delta=effect[
                    "adjusted_defense_rating"
                ],
                finalized_game_coverage=finalized_game_coverage,
                lineup_coverage=lineup_coverage,
                data_through_date=(
                    aggregate.data_through.isoformat()
                    if aggregate.data_through
                    else None
                ),
            )
        )
    return evidence


def checksum_scores(scores: list[Any]) -> str:
    digest = hashlib.sha256()
    for score in sorted(
        scores,
        key=lambda row: (row.season, row.team_id, row.player_id, row.key),
    ):
        digest.update(
            json.dumps(
                {
                    "player_id": score.player_id,
                    "team_id": score.team_id,
                    "season": score.season,
                    "key": score.key,
                    "score": score.score,
                    "confidence": score.confidence,
                    "qualified": score.qualified,
                    "evidence": score.evidence,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def publish_scores(
    conn: Any,
    *,
    version: str,
    scores: list[Any],
    configuration: dict[str, Any],
    activate: bool,
    run_id: int,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT is_active
            FROM defensive_model_versions
            WHERE version = %s
            FOR UPDATE
            """,
            (version,),
        )
        existing = cursor.fetchone()
        if existing is not None and existing[0]:
            raise ValueError(
                f"Active defensive model {version} is immutable; "
                "publish a new version"
            )
        cursor.execute(
            """
            INSERT INTO defensive_model_versions (version, configuration)
            VALUES (%s, %s)
            ON CONFLICT (version) DO UPDATE
            SET configuration = EXCLUDED.configuration
            """,
            (version, Json(configuration)),
        )
        cursor.execute(
            "DELETE FROM player_characteristic_scores WHERE model_version = %s",
            (version,),
        )
        execute_values(
            cursor,
            """
            INSERT INTO player_characteristic_scores (
                player_id, team_id, season, model_version,
                characteristic_key, score, confidence, qualified,
                games, possessions, data_through_date, evidence, limitations
            ) VALUES %s
            """,
            [
                (
                    row.player_id,
                    row.team_id,
                    row.season,
                    version,
                    row.key,
                    row.score,
                    row.confidence,
                    row.qualified,
                    row.games,
                    row.possessions,
                    row.data_through_date,
                    Json(row.evidence),
                    list(row.limitations),
                )
                for row in scores
            ],
            page_size=500,
        )
        if activate:
            cursor.execute(
                """
                UPDATE defensive_model_versions
                SET is_active = FALSE, activated_at = NULL
                WHERE is_active
                """
            )
            cursor.execute(
                """
                UPDATE defensive_model_versions
                SET is_active = TRUE, activated_at = now()
                WHERE version = %s
                """,
                (version,),
            )
        cursor.execute(
            """
            UPDATE data_import_runs
            SET status = 'published',
                published_row_counts = jsonb_build_object(
                    'player_characteristic_scores', %s::int
                ),
                published_at = now(),
                finished_at = now()
            WHERE id = %s AND status = 'validated'
            """,
            (len(scores), run_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Import run {run_id} is not validated")
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=2024)
    parser.add_argument("--last", type=int, required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--scheme-validation-precision", type=float)
    parser.add_argument("--disable-scheme-label", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.first < 2024 or args.first > args.last:
        parser.error("season range must begin in 2024 or later")
    precision = args.scheme_validation_precision
    scheme_validated = precision is not None and precision >= 0.80
    if args.activate and not args.disable_scheme_label and not scheme_validated:
        parser.error(
            "activation with LIKELY_DROP_ANCHOR requires "
            "--scheme-validation-precision >= 0.80"
        )

    load_env_file()
    conn = psycopg2.connect(connection_dsn())
    conn.autocommit = False
    run_id: int | None = None
    try:
        evidence = load_evidence(conn, args.first, args.last)
        scores = score_characteristics(
            evidence,
            scheme_validated=scheme_validated,
        )
        if args.disable_scheme_label:
            scores = [row for row in scores if row.key != "LIKELY_DROP_ANCHOR"]
        if not scores:
            raise ValueError("Candidate model produced no characteristic scores")
        configuration = {
            **MODEL_CONFIGURATION,
            "scheme_validation_precision": precision,
            "scheme_label_enabled": not args.disable_scheme_label,
        }
        summary = {
            "players": len({row.player_id for row in scores}),
            "scores": len(scores),
            "qualified": sum(row.qualified for row in scores),
            "checksum": checksum_scores(scores),
        }
        print(json.dumps(summary, indent=2))
        if not args.apply:
            conn.rollback()
            print("DRY RUN: no model rows changed")
            return

        commit = pipeline_commit(REPO_ROOT)
        run_id = begin_import_run(
            conn,
            dataset="defensive_characteristics",
            import_version=args.release_version,
            commit=commit,
            source_uri="postgres://team_game_lineups",
            first_season=args.first,
            last_season=args.last,
            model_version=args.model_version,
            metadata=configuration,
        )
        mark_validated(
            conn,
            run_id,
            source_sha256=summary["checksum"],
            staged_row_counts={"player_characteristic_scores": len(scores)},
            validation_results=summary,
        )
        publish_scores(
            conn,
            version=args.model_version,
            scores=scores,
            configuration=configuration,
            activate=args.activate,
            run_id=run_id,
        )
    except Exception as error:
        if run_id is not None:
            mark_failed(conn, run_id, error)
        else:
            conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
