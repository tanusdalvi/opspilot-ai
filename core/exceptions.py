"""Application-specific exception hierarchy for OpsPilot AI.

All custom exceptions derive from OpsPilotError so callers can catch
any application error with a single ``except`` clause when needed.
"""


class OpsPilotError(Exception):
    """Base class for all OpsPilot AI application errors."""


class DataValidationError(OpsPilotError):
    """Raised when ingested business data fails validation."""


class ConfigurationError(OpsPilotError):
    """Raised when required configuration or environment setup is missing/invalid."""


class AnalyticsError(OpsPilotError):
    """Raised when analytics or KPI calculations fail."""


class AgentError(OpsPilotError):
    """Raised when the AI investigation agent fails (e.g. Gemini errors, tool failures)."""


class DatabaseError(OpsPilotError):
    """Raised when database persistence or queries fail."""
