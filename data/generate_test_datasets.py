"""Generate test datasets for multi-dataset testing.

Creates three CSV files under data/demo/ covering different schema types:
- demo_manufacturing.csv  (Type B: numeric + categorical, no date)
- demo_marketing.csv      (Type A: date + numeric + categorical)
- demo_scores.csv         (Type C: numeric + categorical)

Run directly:

    python data/generate_test_datasets.py
"""

from __future__ import annotations

import csv
import math
import os
import random
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "demo"


def _seed_rng(seed: int = 42) -> random.Random:
    rng = random.Random(seed)
    return rng


# ---------------------------------------------------------------------------
# Dataset 1: Manufacturing (50 rows, no date)
# ---------------------------------------------------------------------------
MACHINES = [
    "CNC-01", "CNC-02", "CNC-03", "CNC-04", "CNC-05",
    "PRESS-01", "PRESS-02", "PRESS-03",
    "LATHE-01", "LATHE-02",
]
SHIFTS = ["Morning", "Afternoon", "Night"]


def generate_manufacturing(path: Path, rng: random.Random) -> None:
    rows: list[dict[str, object]] = []
    for i in range(50):
        machine = rng.choice(MACHINES)
        shift = rng.choice(SHIFTS)

        # Machines have different baseline characteristics
        machine_idx = MACHINES.index(machine)
        base_volume = 200 + machine_idx * 15
        production_volume = int(rng.gauss(base_volume, base_volume * 0.15))

        # Defect rate: some machines are worse; night shift slightly worse
        base_defect = 1.5 + machine_idx * 0.3
        if shift == "Night":
            base_defect += 0.8
        elif shift == "Afternoon":
            base_defect += 0.3
        defect_rate = round(rng.gauss(base_defect, 0.6), 2)
        defect_rate = max(0.1, min(defect_rate, 8.0))

        # Downtime: correlated with defect rate, some random
        downtime = round(max(0, rng.gauss(30 + defect_rate * 10, 15)), 1)

        rows.append(
            {
                "machine_id": machine,
                "defect_rate": defect_rate,
                "production_volume": max(50, production_volume),
                "downtime_minutes": downtime,
                "shift": shift,
            }
        )

    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["machine_id", "defect_rate", "production_volume", "downtime_minutes", "shift"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# Dataset 2: Marketing (60 rows, with date)
# ---------------------------------------------------------------------------
CAMPAIGNS = ["Spring Sale", "Brand Awareness", "Retarget Q2", "New Product Launch", "Holiday Promo"]


def generate_marketing(path: Path, rng: random.Random) -> None:
    rows: list[dict[str, object]] = []
    base_date = rng.randint(1, 28)
    # 60 days: two months starting June 2024
    for day in range(60):
        month = 6 + day // 30
        day_of_month = (base_date + day) % 28 + 1
        date_str = f"2024-{month:02d}-{day_of_month:02d}"

        campaign = rng.choice(CAMPAIGNS)
        is_weekend = (rng.randint(0, 6)) >= 5

        # Base impressions per campaign
        campaign_profiles = {
            "Spring Sale": 8500,
            "Brand Awareness": 15000,
            "Retarget Q2": 5000,
            "New Product Launch": 20000,
            "Holiday Promo": 12000,
        }
        base_imp = campaign_profiles[campaign]
        if is_weekend:
            base_imp = int(base_imp * 0.75)
        impressions = int(rng.gauss(base_imp, base_imp * 0.2))

        # CTR varies by campaign
        ctr_map = {
            "Spring Sale": 0.035,
            "Brand Awareness": 0.015,
            "Retarget Q2": 0.055,
            "New Product Launch": 0.028,
            "Holiday Promo": 0.042,
        }
        ctr = rng.gauss(ctr_map[campaign], 0.008)
        clicks = max(1, int(impressions * max(0.005, ctr)))

        # Conversion rate varies
        conv_rate_map = {
            "Spring Sale": 0.12,
            "Brand Awareness": 0.03,
            "Retarget Q2": 0.18,
            "New Product Launch": 0.08,
            "Holiday Promo": 0.10,
        }
        conv_rate = rng.gauss(conv_rate_map[campaign], 0.025)
        conversions = max(0, int(clicks * max(0.01, conv_rate)))

        # Spend: CPM-based with noise
        cpm_map = {
            "Spring Sale": 6.5,
            "Brand Awareness": 3.2,
            "Retarget Q2": 8.0,
            "New Product Launch": 5.0,
            "Holiday Promo": 7.0,
        }
        spend = round(impressions / 1000.0 * rng.gauss(cpm_map[campaign], 1.0), 2)
        spend = max(10.0, spend)

        rows.append(
            {
                "date": date_str,
                "campaign": campaign,
                "impressions": max(100, impressions),
                "clicks": clicks,
                "conversions": conversions,
                "spend": spend,
            }
        )

    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["date", "campaign", "impressions", "clicks", "conversions", "spend"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# Dataset 3: Scores (30 rows, numeric + one categorical, no date)
# ---------------------------------------------------------------------------
CATEGORIES = ["Beginner", "Intermediate", "Advanced", "Expert"]


def generate_scores(path: Path, rng: random.Random) -> None:
    rows: list[dict[str, object]] = []
    for i in range(30):
        category = rng.choice(CATEGORIES)
        # Higher category -> higher scores with overlap
        cat_offset = CATEGORIES.index(category) * 15

        score_a = round(rng.gauss(40 + cat_offset, 12), 1)
        score_b = round(rng.gauss(35 + cat_offset, 15), 1)
        # score_c has a different distribution shape
        score_c = round(max(0, min(100, 50 + cat_offset + rng.gauss(0, 10))), 1)
        score_a = round(max(0, min(100, score_a)), 1)
        score_b = round(max(0, min(100, score_b)), 1)

        rows.append(
            {
                "score_a": score_a,
                "score_b": score_b,
                "score_c": score_c,
                "category": category,
            }
        )

    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["score_a", "score_b", "score_c", "category"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = _seed_rng()
    print(f"Generating test datasets in {OUTPUT_DIR}/")
    generate_manufacturing(OUTPUT_DIR / "demo_manufacturing.csv", rng)
    generate_marketing(OUTPUT_DIR / "demo_marketing.csv", rng)
    generate_scores(OUTPUT_DIR / "demo_scores.csv", rng)
    print("Done.")


if __name__ == "__main__":
    main()
