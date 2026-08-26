import csv
import random
from datetime import date, timedelta

random.seed(42)

OUTPUT_PATH = r"C:\Users\Tanishka\opspilot-ai\data\demo\demo_sales_ops.csv"
TARGET_ROWS = 5000

CATEGORIES = ["Electronics", "Furniture", "Office Supplies", "Software"]
CITIES = ["New York", "San Francisco", "Chicago", "Austin", "Seattle", "Boston", "Denver", "Portland"]
CHANNELS = ["Online", "Retail", "Wholesale", "Direct"]

# Profit margin ranges by category (min_margin, max_margin)
CAT_MARGIN = {
    "Electronics": (0.18, 0.40),
    "Furniture": (0.08, 0.22),
    "Office Supplies": (0.10, 0.25),
    "Software": (0.15, 0.35),
}

# City base sales multiplier (Seattle is higher)
CITY_MULT = {
    "New York": 1.0,
    "San Francisco": 1.1,
    "Chicago": 0.95,
    "Austin": 0.9,
    "Seattle": 1.45,
    "Boston": 1.05,
    "Denver": 0.85,
    "Portland": 0.9,
}

# Channel characteristics: (qty_mult, margin_mult)
CHANNEL_CHARS = {
    "Online": (0.8, 1.0),
    "Retail": (1.0, 1.0),
    "Wholesale": (2.2, 0.55),
    "Direct": (0.6, 1.15),
}

start_date = date(2025, 1, 1)
end_date = date(2025, 12, 31)
num_days = (end_date - start_date).days + 1  # 365

# Determine which days appear (~82% of days to create gaps → ~300 dates, yielding ~5000 rows)
days_to_skip = set()
while len(days_to_skip) < 65:
    days_to_skip.add(random.randint(0, num_days - 1))

# July boost factor (months 7)
# October profit drop (months 10)

def gen_date(day_offset):
    return start_date + timedelta(days=day_offset)

def gen_row(day_offset):
    d = gen_date(day_offset)
    month = d.month

    category = random.choice(CATEGORIES)
    city = random.choice(CITIES)
    channel = random.choice(CHANNELS)

    # Base quantity
    base_qty = random.randint(1, 20)
    qty_mult = CHANNEL_CHARS[channel][0]
    qty = max(1, min(50, int(base_qty * qty_mult + random.gauss(0, 1))))

    # Base sales
    base_sales = random.uniform(100, 2200)

    # July spike: multiply by 1.6-2.2
    if month == 7:
        base_sales *= random.uniform(1.6, 2.2)

    # City multiplier
    base_sales *= CITY_MULT[city]

    # Some high-value outliers
    if random.random() < 0.03:
        base_sales *= random.uniform(2.0, 3.0)

    # Category adjustment
    if category == "Electronics":
        base_sales *= random.uniform(1.1, 1.4)
    elif category == "Furniture":
        base_sales *= random.uniform(0.9, 1.1)

    sales_amount = round(max(15.0, min(4500.0, base_sales)), 2)

    # Profit calculation
    base_margin = random.uniform(*CAT_MARGIN[category])
    channel_margin = CHANNEL_CHARS[channel][1]
    margin = base_margin * channel_margin

    # October profit drop (high costs)
    if month == 10:
        margin *= random.uniform(-0.15, 0.3)

    profit = round(sales_amount * margin + random.gauss(0, 30), 2)
    # Clamp profit to reasonable range
    profit = round(max(-500.0, min(2500.0, profit)), 2)

    return {
        "order_date": d.isoformat(),
        "sales_amount": sales_amount,
        "profit": profit,
        "quantity": qty,
        "product_category": category,
        "city": city,
        "channel": channel,
    }


rows = []
for offset in range(num_days):
    if offset in days_to_skip:
        continue
    # Some days get 1 row, some get 2, a few get 3
    n = random.choices([1, 2, 3], weights=[0.55, 0.35, 0.10])[0]
    for _ in range(n):
        rows.append(gen_row(offset))

# Pad or trim to ~5000
if len(rows) > TARGET_ROWS + 100:
    rows = rows[:TARGET_ROWS]
elif len(rows) < TARGET_ROWS - 100:
    extra_needed = TARGET_ROWS - len(rows)
    for i in range(extra_needed):
        offset = random.randint(0, num_days - 1)
        rows.append(gen_row(offset))

random.shuffle(rows)
rows = rows[:TARGET_ROWS]

# Write CSV
fieldnames = [
    "order_date", "sales_amount", "profit", "quantity",
    "product_category", "city", "channel",
]

with open(OUTPUT_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"File: {OUTPUT_PATH}")
print(f"Row count (data rows, excluding header): {len(rows)}")
