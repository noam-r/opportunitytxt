"""Structured error hierarchy for opportunity_txt.

All package errors inherit from OpportunityTxtError so callers can catch
at a single level.  Service wrappers translate these into HTTP semantics;
CLI translates them into sys.exit() — the package itself never calls
sys.exit().
"""

from __future__ import annotations

from dataclasses import dataclass, field


class OpportunityTxtError(Exception):
    """Base exception for all opportunity_txt errors."""


class AuthenticationError(OpportunityTxtError):
    """GitHub token missing or invalid."""


@dataclass
class RateLimitError(OpportunityTxtError):
    """GitHub API rate limit exhausted."""
    message: str = "GitHub API rate limit exceeded"
    retry_after_seconds: int | None = None
    requests_remaining: int = 0

    def __str__(self) -> str:
        s = self.message
        if self.retry_after_seconds is not None:
            s += f" (retry after {self.retry_after_seconds}s)"
        return s


class CollectionError(OpportunityTxtError):
    """Error during GitHub data collection."""


class NormalizationError(OpportunityTxtError):
    """Error during evidence normalization."""


@dataclass
class ValidationError(OpportunityTxtError):
    """Invalid request parameters or schema validation failure."""
    message: str = "Validation error"
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {'; '.join(self.details)}"
        return self.message


@dataclass
class IntegrityError(OpportunityTxtError):
    """Report integrity check failure (strict mode)."""
    message: str = "Report integrity check failed"
    issues: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.issues:
            return f"{self.message}: {'; '.join(self.issues)}"
        return self.message


class RendererError(OpportunityTxtError):
    """Error during report rendering."""


class UnsupportedRequestError(OpportunityTxtError):
    """Requested methodology version, mode, or feature is not supported."""
