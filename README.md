# opportunity-txt

Deterministic public GitHub evidence evaluator. Analyzes contribution patterns, stewardship signals, builder signals, and adoption proxies to produce structured evaluation reports.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

### CLI

```bash
export GITHUB_TOKEN="ghp_..."

opportunity-txt <username>
opportunity-txt <username> --window 1y --max-repos 30 --refresh
opportunity-txt <username> --mode debug --json
```

### Programmatic API

```python
from opportunity_txt import evaluate_github_profile
from opportunity_txt.models import EvaluateGitHubProfileRequest

request = EvaluateGitHubProfileRequest(
    github_username="torvalds",
    run_mode="user",
)
result = evaluate_github_profile(request)

# result.report          — typed EvaluationReport
# result.summary         — CompactSummary
# result.markdown_report — rendered markdown string
```

## Output

The evaluator produces a structured `EvaluateGitHubProfileResult` containing:

- **report** — typed `EvaluationReport` with subject, scope, archetypes, maturity, dimensions, readiness, signal highlights, limitations, integrity, and methodology sections
- **summary** — compact `CompactSummary` for UI cards or CLI output
- **markdown_report** — pre-rendered human-readable evaluation report
- **evidence** — normalized evidence snapshot (debug mode only)
- **signals** — deterministic signal snapshot (debug mode only)
