"""Deterministic synthetic operational dataset generator for OpsPilot AI.

Phase 1 demo data: daily operational records across multiple regions and
products with trends, seasonality and occasional spikes/dips so later phases
(KPIs, anomaly detection) have realistic signal to analyse.

Run directly:

    python scripts/generate_demo_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from core.config import DATA_DIR

SEED = 42
START_DATE = "2024-01-01"
NUM_DAYS = 730
DEMO_FILENAME = "demo_operational_data.csv"

REQUIRED_COLUMNS = [
    "date",
    "region",
    "product",
    "units_sold",
    "revenue",
    "cost",
    "lead_time_days",
]

REGIONS = ["North", "South", "East", "West"]

PRODUCTS = ["Widget Pro", "Gadget Plus", "Sensor Lite"]

REGION_PROFILES = {
    "North": {"demand": 120.0, "lead_time": 7.0},
    "South": {"demand": 90.0, "lead_time": 12.0},
    "East": {"demand": 150.0, "lead_time": 5.0},
    "West": {"demand": 70.0, "lead_time": 18.0},
}

PRODUCT_CATALOG = {
    "Widget Pro": {"price": 24.50, "cost": 14.00, "popularity": 1.15},
    "Gadget Plus": {"price": 59.90, "cost": 33.50, "popularity": 0.85},
    "Sensor Lite": {"price": 12.75, "cost": 7.40, "popularity": 1.00},
}

LEAD_TIME_MIN = 1
LEAD_TIME_MAX = 45


def _day_shape_factors(day_index: np.ndarray, day_of_week: np.ndarray) -> dict[str, np.ndarray]:
    """Shared temporal components applied to every region/product series."""
    trend = 1.0 + 0.25 * day_index / NUM_DAYS
    yearly_seasonality = 1.0 + 0.15 * np.sin(2.0 * np.pi * day_index / 365.25)
    weekend_factor = np.where(day_of_week >= 5, 0.80, 1.0)
    return {
        "trend": trend,
        "yearly_seasonality": yearly_seasonality,
        "weekend_factor": weekend_factor,
    }


def generate_demo_data(seed: int = SEED) -> pd.DataFrame:
    """Generate the deterministic demo dataset and return it as a DataFrame."""
    rng = np.random.default_rng(seed)

    dates = pd.date_range(START_DATE, periods=NUM_DAYS, freq="D")
    date_strings = dates.strftime("%Y-%m-%d")
    day_index = np.arange(NUM_DAYS, dtype=float)
    day_of_week = dates.dayofweek.to_numpy()

    shape = _day_shape_factors(day_index, day_of_week)

    frames: list[pd.DataFrame] = []
    for region in REGIONS:
        region_profile = REGION_PROFILES[region]
        for product in PRODUCTS:
            catalog_entry = PRODUCT_CATALOG[product]
            base_demand = region_profile["demand"] * catalog_entry["popularity"]

            demand_noise = rng.lognormal(mean=0.0, sigma=0.18, size=NUM_DAYS)
            spike_mask = rng.random(NUM_DAYS) < 0.02
            dip_mask = (~spike_mask) & (rng.random(NUM_DAYS) < 0.015)
            spike_multiplier = np.where(
                spike_mask, rng.uniform(1.6, 2.6, size=NUM_DAYS), 1.0
            )
            dip_multiplier = np.where(dip_mask, rng.uniform(0.10, 0.45, size=NUM_DAYS), 1.0)

            units = (
                base_demand
                * shape["trend"]
                * shape["yearly_seasonality"]
                * shape["weekend_factor"]
                * demand_noise
                * spike_multiplier
                * dip_multiplier
            )
            units_sold = np.maximum(np.round(units).astype(np.int64), 1)

            price_noise = rng.normal(loc=1.0, scale=0.03, size=NUM_DAYS)
            revenue = np.round(units_sold * catalog_entry["price"] * price_noise, 2)
            revenue = np.maximum(revenue, 0.01)

            cost_noise = rng.normal(loc=1.0, scale=0.05, size=NUM_DAYS)
            cost = np.round(units_sold * catalog_entry["cost"] * cost_noise, 2)
            cost = np.maximum(cost, 0.01)

            lead_noise = rng.normal(loc=0.0, scale=2.0, size=NUM_DAYS)
            supply_seasonality = 2.0 * np.sin(2.0 * np.pi * day_index / 180.0)
            lead_time = np.round(region_profile["lead_time"] + supply_seasonality + lead_noise)
            lead_time_days = np.clip(lead_time, LEAD_TIME_MIN, LEAD_TIME_MAX).astype(np.int64)

            frames.append(
                pd.DataFrame(
                    {
                        "date": date_strings,
                        "region": region,
                        "product": product,
                        "units_sold": units_sold,
                        "revenue": revenue,
                        "cost": cost,
                        "lead_time_days": lead_time_days,
                    }
                )
            )

    df = pd.concat(frames, ignore_index=True)
    return df[REQUIRED_COLUMNS]


def save_demo_data(df: pd.DataFrame, output_path: str | Path | None = None) -> Path:
    """Save the demo dataset as CSV and return the resolved output path."""
    if output_path is None:
        path = DATA_DIR / "demo" / DEMO_FILENAME
    else:
        path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def main() -> None:
    """Generate the demo dataset and write it under data/demo/."""
    df = generate_demo_data()
    path = save_demo_data(df)
    print(f"Generated {len(df)} rows across {len(REGIONS)} regions "
          f"and {len(PRODUCTS)} products -> {path}")


if __name__ == "__main__":
    main()
