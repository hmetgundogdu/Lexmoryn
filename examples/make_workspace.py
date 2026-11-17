"""Create an entirely synthetic, deterministic scale corpus; never read private workspaces."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--files", type=int, default=1000)
    args = parser.parse_args()
    source = Path(__file__).parent / "workspace"
    if args.destination.exists():
        parser.error("destination must not exist (generation never overwrites a workspace)")
    seeds = [p for p in source.rglob("*") if p.is_file() and ".lexmoryn" not in p.parts]
    visible = sum(not p.name.startswith(".") for p in seeds)
    if args.files < visible:
        parser.error(f"--files must be at least {visible}")
    shutil.copytree(source, args.destination, ignore=shutil.ignore_patterns(".lexmoryn"))
    topics = [
        ("gardening", "Orchids thrive in indirect sunlight. Keep potting soil lightly moist."),
        ("astronomy", "The telescope tracks distant stars. Observe nebulae under dark skies."),
        ("cooking", "Roast aubergines and combine them with yoghurt and fresh herbs."),
        ("cycling", "Inspect the bicycle brake pads and adjust tyre pressure before a ride."),
        ("music", "The chamber orchestra rehearses string quartets in the concert hall."),
        ("geology", "Basalt samples record volcanic activity and mineral crystallization."),
        ("birds", "An eagle nests near the mountain. This wildlife note concerns birds only."),
        ("shipping", "Warehouse parcels travel by rail. Freight labels record crate weight."),
    ]
    noise = args.destination / "archive"
    noise.mkdir()
    for i in range(args.files - visible):
        topic, description = topics[i % len(topics)]
        path = noise / f"{topic}_{i:05d}.txt"
        path.write_text(f"Synthetic archive note {i:05d}\n{description}\n", encoding="utf-8")
    print(f"Created {args.files} visible files; synthetic template distractors are not real data.")


if __name__ == "__main__":
    main()
