"""opportunity_txt — Public GitHub evidence evaluator."""

from .evaluate import evaluate_github_profile
from .version import __version__

__all__ = ["evaluate_github_profile", "__version__"]
