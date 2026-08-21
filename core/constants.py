"""Project-wide constants for OpsPilot AI.

Keep values here stable and simple; later phases import them instead of
redefining their own copies of the same strings.
"""

# --- General ---------------------------------------------------------------

APPLICATION_NAME = "OpsPilot AI"

# --- Alert severity levels (used by the future alert engine) ---------------

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

# --- Operational health labels (used on dashboards/reports) ----------------

HEALTHY = "Healthy"
NEEDS_ATTENTION = "Needs Attention"
AT_RISK = "At Risk"
CRITICAL = "Critical"

# --- Recommendation statuses (human review workflow) -----------------------

RECOMMENDATION_PENDING = "PENDING"
RECOMMENDATION_APPROVED = "APPROVED"
RECOMMENDATION_REJECTED = "REJECTED"
RECOMMENDATION_REVIEW = "REVIEW"
