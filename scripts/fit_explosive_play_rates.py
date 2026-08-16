"""Rebuild the explosive-play calibration from slim CSV/CSV.GZ/PARQUET files.

The raw play-by-play files are inputs, never release artifacts. This command
writes a reviewable JSON artifact; use ``--check`` to compare a recomputation
with the tracked totals/rates without modifying the repository.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yahoo_fantasy_mcp.projections.explosive_play_model import fit_from_history  # noqa: E402
from yahoo_fantasy_mcp.projections.pbp_calibration import aggregate_rows  # noqa: E402

DEFAULT_OUTPUT = Path("src/yahoo_fantasy_mcp/projections/explosive_play_calibration.json")
BASIS = "provided_slim_pbp_2020_2025_regular_seasons_v1"


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    suffixes = path.suffixes
    if suffixes[-2:] == [".csv", ".gz"]:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    if path.suffix.lower() == ".parquet":
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("Parquet input requires pandas plus a parquet engine") from exc
        yield from pd.read_parquet(path).to_dict(orient="records")
        return
    raise ValueError(f"Unsupported input format: {path}")


def build(paths: list[Path]) -> dict[str, Any]:
    all_totals = {name: 0 for name in aggregate_rows([])}
    metadata: list[dict[str, Any]] = []
    for path in paths:
        rows = list(_rows(path))
        totals = aggregate_rows(rows)
        for name, value in totals.items():
            all_totals[name] += value
        seasons = {int(float(row["season"])) for row in rows if row.get("season") not in (None, "")}
        weeks = [int(float(row["week"])) for row in rows if row.get("week") not in (None, "")]
        game_ids = {str(row["game_id"]) for row in rows if row.get("game_id")}
        metadata.append({
            "season": next(iter(seasons)) if len(seasons) == 1 else sorted(seasons),
            "rows": len(rows),
            "regular_rows": sum(
                1 for row in rows
                if str(row.get("season_type", "REG")).upper() == "REG"
                and int(float(row.get("week") or 0)) <= (17 if int(float(row.get("season") or 0)) == 2020 else 18)
            ),
            "games": len(game_ids),
            "max_week": max(weeks, default=0),
            "sha256": _hash(path),
        })
    rates = fit_from_history([all_totals])
    return {
        "schema_version": 1,
        "basis": BASIS,
        "description": "Offline calibration from supplied slim play-by-play files.",
        "totals": all_totals,
        "rates": {
            "completion_40plus_rate": rates.completion_40plus_rate,
            "rush_40plus_rate": rates.rush_40plus_rate,
            "reception_40plus_rate": rates.reception_40plus_rate,
            "td_share_of_40plus": rates.td_share_of_40plus,
            "passing_td_share_of_40plus": rates.passing_td_share_of_40plus,
            "rushing_td_share_of_40plus": rates.rushing_td_share_of_40plus,
            "receiving_td_share_of_40plus": rates.receiving_td_share_of_40plus,
        },
        "files": metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build(args.inputs)
    if args.check:
        expected = json.loads(args.output.read_text(encoding="utf-8"))
        for key in ("basis", "totals", "rates", "files"):
            if payload[key] != expected[key]:
                print(f"calibration-check: mismatch in {key}", file=sys.stderr)
                return 1
        print("calibration-check: RESULT exact")
        return 0
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
