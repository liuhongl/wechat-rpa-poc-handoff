from __future__ import annotations

import argparse
import json
from pathlib import Path


def _snapshot_paths(snapshot_dir: Path, *, pattern: str) -> list[Path]:
    if not snapshot_dir.exists():
        return []
    return sorted(
        [path for path in snapshot_dir.glob(pattern) if path.is_file()],
        key=lambda path: path.name,
    )


def build_cleanup_summary(
    *,
    snapshot_dir: Path,
    pattern: str,
    max_count: int,
    delete: bool,
) -> dict[str, object]:
    snapshots = _snapshot_paths(snapshot_dir, pattern=pattern)
    candidate_paths = snapshots[:-max_count] if len(snapshots) > max_count else []
    deleted_paths: list[Path] = []
    if delete:
        for path in candidate_paths:
            path.unlink(missing_ok=True)
            deleted_paths.append(path)

    retained_paths = snapshots[-max_count:] if max_count else []
    return {
        "deleted": delete,
        "snapshot_dir": str(snapshot_dir),
        "pattern": pattern,
        "max_count": max_count,
        "snapshot_count": len(snapshots),
        "retained_count": len(retained_paths),
        "candidate_count": len(candidate_paths),
        "deleted_count": len(deleted_paths),
        "retained_paths": [str(path) for path in retained_paths],
        "candidate_paths": [str(path) for path in candidate_paths],
        "deleted_paths": [str(path) for path in deleted_paths],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="POC: keep only the newest no-message-audit accessibility snapshot files."
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=Path("data/no_msgaudit_desktop_agent/accessibility_snapshots"),
    )
    parser.add_argument("--pattern", default="*.txt")
    parser.add_argument("--max-count", type=int, default=2000)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    if args.max_count < 1:
        raise SystemExit("--max-count must be >= 1")

    summary = build_cleanup_summary(
        snapshot_dir=args.snapshot_dir,
        pattern=args.pattern,
        max_count=args.max_count,
        delete=args.delete,
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
