"""Where things live on disk."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def inputs_dir(tile: str) -> Path:
    return ROOT / "data" / "interim" / tile


def run_dir(tile: str, device: str, date: str) -> Path:
    """One SOLWEIG run: a tile, a device and a day."""
    return ROOT / "data" / "processed" / tile / device / date


def output_dir(tile: str, device: str, date: str) -> Path:
    return run_dir(tile, device, date) / "output_folder" / "0_0"
