"""Atomic persistence for matching engine state snapshots."""

from __future__ import annotations

import os
from pathlib import Path

from engine.snapshot import EngineSnapshot


def save_snapshot(snapshot: EngineSnapshot, path: str | Path) -> Path:
    """Save an EngineSnapshot to disk atomically.

    Writes to a temporary file first and atomically renames it to the target
    destination, avoiding partially written or corrupted snapshots on failure.
    """
    if not isinstance(snapshot, EngineSnapshot):
        raise TypeError("snapshot must be an EngineSnapshot instance")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")

    payload = snapshot.to_json()
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise

    return target


def load_snapshot(path: str | Path) -> EngineSnapshot:
    """Load and parse an EngineSnapshot from disk."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"snapshot file not found: {target}")
    content = target.read_text(encoding="utf-8")
    return EngineSnapshot.from_json(content)


class SnapshotManager:
    """Manage saving, loading, and discovering snapshots in a directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        snapshot: EngineSnapshot,
        filename: str | None = None,
    ) -> Path:
        """Save a snapshot into the managed directory."""
        if filename is None:
            filename = f"snapshot_{snapshot.last_sequence:08d}.json"
        path = self.directory / filename
        return save_snapshot(snapshot, path)

    def load(self, filename: str | Path) -> EngineSnapshot:
        """Load a snapshot from the managed directory or given path."""
        path = (
            Path(filename)
            if isinstance(filename, Path) and filename.is_absolute()
            else self.directory / filename
        )
        return load_snapshot(path)

    def list_snapshots(self) -> list[Path]:
        """Return sorted snapshot paths in the managed directory."""
        return sorted(self.directory.glob("*.json"))

    def latest(self) -> EngineSnapshot | None:
        """Load the most recent snapshot in the directory, or None if empty."""
        snapshots = self.list_snapshots()
        if not snapshots:
            return None
        return load_snapshot(snapshots[-1])
