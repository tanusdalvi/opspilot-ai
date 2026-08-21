"""Data service: discovery and loading of CSV datasets.

Provides small helpers to list available demo datasets, safely load them
by filename, load arbitrary local CSV files, and inspect DataFrames.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config import DATA_DIR
from core.exceptions import DataValidationError

# Directory that holds the bundled demo datasets.
DEMO_DATA_DIR: Path = DATA_DIR / "demo"

# Hidden placeholder files that must never be treated as datasets.
IGNORED_FILES: frozenset[str] = frozenset({".gitkeep"})


def _is_csv_file(path: Path) -> bool:
    """Return ``True`` when ``path`` is an existing regular ``*.csv`` file."""
    return path.is_file() and path.suffix.lower() == ".csv"


def list_datasets() -> list[dict[str, object]]:
    """Return metadata dictionaries for every CSV file in the demo directory.

    Placeholder files such as ``.gitkeep`` are ignored. Each dictionary
    contains ``name``, ``path``, ``size_bytes``, and ``modified_at`` keys.
    """
    datasets: list[dict[str, object]] = []
    if not DEMO_DATA_DIR.is_dir():
        return datasets
    for path in sorted(DEMO_DATA_DIR.iterdir()):
        if path.name in IGNORED_FILES or not _is_csv_file(path):
            continue
        stat = path.stat()
        datasets.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )
    return datasets


def load_csv(path: Path | str) -> pd.DataFrame:
    """Load a CSV file into a DataFrame.

    Args:
        path: Path to an existing ``*.csv`` file.

    Returns:
        The parsed DataFrame.

    Raises:
        DataValidationError: If the path does not exist or is not a CSV file.
    """
    csv_path = Path(path)
    if not _is_csv_file(csv_path):
        raise DataValidationError(f"Not a readable CSV file: {csv_path}")
    return pd.read_csv(csv_path)


def load_dataset(filename: str) -> pd.DataFrame:
    """Load a demo dataset by filename from the demo data directory.

    Only plain CSV filenames located inside the demo directory are allowed.
    Nonexistent files, non-CSV names, and path traversal attempts are rejected.

    Args:
        filename: CSV filename (e.g. ``demo_operational_data.csv``).

    Returns:
        The parsed DataFrame.

    Raises:
        DataValidationError: If the filename is invalid, escapes the demo
            directory, or does not exist.
    """
    if not filename:
        raise DataValidationError("Dataset filename must not be empty")
    if Path(filename).suffix.lower() != ".csv":
        raise DataValidationError(f"Dataset must be a CSV file: {filename!r}")

    demo_root = DEMO_DATA_DIR.resolve()
    candidate = (demo_root / filename).resolve()
    try:
        candidate.relative_to(demo_root)
    except ValueError as exc:
        raise DataValidationError(
            f"Path traversal is not allowed: {filename!r}"
        ) from exc

    if not _is_csv_file(candidate):
        raise DataValidationError(f"Dataset not found: {filename!r}")
    return load_csv(candidate)


def get_dataset_info(df: pd.DataFrame) -> dict[str, object]:
    """Return basic structural information about a DataFrame.

    Args:
        df: The DataFrame to inspect.

    Returns:
        Dictionary with ``row_count``, ``column_count``, ``columns``,
        and ``memory_usage_bytes``.
    """
    return {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "columns": [str(column) for column in df.columns],
        "memory_usage_bytes": int(df.memory_usage(deep=True).sum()),
    }
