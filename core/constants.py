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

# --- CSV upload hardening (Phase 9) -----------------------------------------

# Hard ceiling on staged CSV uploads, in bytes. Oversized uploads are
# rejected before any parsing work happens. Demo-safe default: 20 MiB.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Advisory-only row threshold. Datasets above this size still load and
# analyze normally; the UI simply warns that processing may take longer.
UPLOAD_ROW_ADVISORY = 500_000

# Duplicate-basename policy for uploads: an identical basename replaces
# the previously staged file deterministically (uploads are transient
# staging copies and are never part of the audit store).
UPLOAD_DUPLICATE_POLICY = "replace"

# --- Restart recovery (Phase 10B) --------------------------------------------

# Detection sensitivities accepted by the analysis pipeline.
VALID_SENSITIVITIES: tuple[str, ...] = ("low", "medium", "high")

# Schema version of the restart-recovery metadata sidecar. Contexts with
# a different version are rejected (fail-safe) rather than interpreted.
RECOVERY_CONTEXT_VERSION = 1

# Filename of the recovery metadata sidecar, stored inside the
# gitignored ``data/uploads/`` runtime directory.
RECOVERY_CONTEXT_FILENAME = "recovery_context.json"
