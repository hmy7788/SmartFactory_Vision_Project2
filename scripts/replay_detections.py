"""Run from the repository root: python -m scripts.replay_detections --demo."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame
from src.process.recipe import load_recipe
from scripts.demo_data import demo_frames

ROOT = Path(__file__).resolve().parents[1]


def replay(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield DetectionFrame.from_dict(json.loads(line))
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(f"Invalid frame at line {line_number}: {error}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true")
    source.add_argument("--input", type=Path, help="Normalized DetectionFrame JSONL")
    parser.add_argument("--recipe", default="recipe_1", choices=["recipe_1", "recipe_2", "recipe_3"])
    parser.add_argument("--config", type=Path, default=ROOT/"config/mvp.json")
    parser.add_argument("--output", type=Path, help="Write all snapshots to a new JSONL file")
    args = parser.parse_args()
    config = load_config(args.config)
    recipe = load_recipe(ROOT/f"config/recipes/{args.recipe}.json")
    service = InspectionService(config, recipe)
    frames = demo_frames(recipe, config) if args.demo else replay(args.input)
    output = args.output.open("x", encoding="utf-8") if args.output else None
    print(f"Recipe: {recipe.recipe_id}; calibration: {config['calibration_status']}")
    try:
        previous = None
        for frame in frames:
            snapshot = service.update(frame)
            if output:
                output.write(json.dumps(asdict(snapshot), ensure_ascii=False)+"\n")
            key = (snapshot.phase, snapshot.status, snapshot.candidate, snapshot.stable)
            if key != previous:
                print(f"{frame.timestamp_ms:6.0f} ms | {snapshot.phase.value:15} | {snapshot.status.value:11} "
                      f"| candidate={snapshot.candidate.status.value:11} | stable={snapshot.stable} "
                      f"| {[i.code + ':H' + str(i.hole_id) for i in snapshot.candidate.issues]}")
                previous = key
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    main()
