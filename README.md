# opportunity-txt

A deterministic evaluation engine that analyzes public GitHub evidence — contribution patterns, stewardship signals, builder sophistication, and ecosystem adoption — and produces structured, versioned evaluation reports.

The package is designed to be embedded into larger products (portals, services, pipelines) without coupling to any specific UI, database, or workflow. It owns evidence collection, signal computation, scoring, and report generation. It does not own users, consent, billing, or product workflows.

## What it measures

- **7 dimensions:** Contribution Quality, Collaboration Quality, Maintainer/Community Trust, Ecosystem Impact, Specialization Strength, Consistency Over Time, Builder Sophistication
- **8 archetypes:** External Contributor, Independent Builder, Owned Project Maintainer, Maintainer/Steward, Burst Execution, Sustained Contributor, Complex Product Builder, Foundational Infrastructure Builder
- **3 builder routes:** Route A (PR delivery), Route B (repo substance), Route C (foundational infrastructure)
- **Evidence regime classification:** sparse / limited / normal / rich
- **Observability-first safety:** dimensions that can't be fairly judged from available evidence are marked "Not Reliably Observable" rather than scored low

## What it does not measure

Total professional ability, private work, organizational leadership, hiring skill, strategic judgment, or business success.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Python 3.11+ and a GitHub personal access token.

## CLI usage

```bash
# Set your GitHub token
export GITHUB_TOKEN="ghp_..."

# Basic evaluation
opportunity-txt torvalds

# Customize window and repo cap
opportunity-txt torvalds --window 1y --max-repos 30

# Bypass cache
opportunity-txt torvalds --refresh

# Debug mode with full JSON output
opportunity-txt torvalds --mode debug --json
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--window` | `3y` | Observation window: `1y`, `2y`, `3y`, `5y`, `all` |
| `--max-repos` | `50` | Maximum repositories to evaluate |
| `--output-dir` | `output` | Directory for output artifacts |
| `--cache-dir` | `.cache` | Directory for API response cache |
| `--refresh` | off | Bypass cache and re-fetch all data |
| `--mode` | `user` | Run mode: `user` (display-safe) or `debug` (full internals) |
| `--json` | off | Write structured JSON result to output dir |

## Package usage

```python
from opportunity_txt import evaluate_github_profile
from opportunity_txt.models import EvaluateGitHubProfileRequest

request = EvaluateGitHubProfileRequest(
    github_username="torvalds",
    github_token="ghp_...",       # or omit to use GITHUB_TOKEN env var
    observation_window="3y",
    run_mode="user",
)

result = evaluate_github_profile(request)
```

### What you get back

`result` is an `EvaluateGitHubProfileResult` with these fields:

| Field | Type | Description |
|---|---|---|
| `methodology_version` | `str` | Scoring logic version (`"1.0.0"`) |
| `schema_version` | `str` | Result contract version (`"1.0.0"`) |
| `generated_at` | `str` | ISO-8601 timestamp |
| `report` | `EvaluationReport` | Typed structured report (always present) |
| `markdown_report` | `str \| None` | Pre-rendered markdown report |
| `summary` | `CompactSummary \| None` | Compact output for cards/previews |
| `evidence` | `dict \| None` | Normalized evidence (debug mode only) |
| `signals` | `dict \| None` | Raw signal snapshot (debug mode only) |

### Reading the report

```python
# Typed structured sections
report = result.report

report.subject.username          # "torvalds"
report.maturity.band             # "Public Maintainer / Steward"
report.maturity.evidence_regime  # "limited"

# Canonical dimension results — the only source renderers should use
for dim in report.dimensions:
    if dim.status == "not_reliably_observable":
        print(f"{dim.name}: N/R Observable")
    else:
        print(f"{dim.name}: {dim.score_label} ({dim.confidence_label})")

# Readiness
report.readiness.readiness_summary

# Integrity
report.integrity.passed
report.integrity.issue_summary

# Builder route highlights
for route in report.signal_highlights.builder_routes:
    print(f"{route.route_label}: active={route.active}")
```

### Reading the summary

```python
summary = result.summary

summary.maturity_band       # "Public Maintainer / Steward"
summary.primary_domain      # "operating-systems"
summary.readiness_summary   # "Evidence supports infrastructure ownership roles..."

for d in summary.dimensions:
    print(f"{d.name}: {d.score_label}")
```

### Caching

The package does not hardcode caching. Pass an optional `FileCache` for CLI-style file caching, or implement `CacheProtocol` for custom backends:

```python
from opportunity_txt.cache import FileCache

result = evaluate_github_profile(request, cache=FileCache())
```

### Error handling

All package errors inherit from `OpportunityTxtError`:

```python
from opportunity_txt.errors import (
    OpportunityTxtError,
    AuthenticationError,    # missing or invalid GitHub token
    CollectionError,        # GitHub API failure
    RateLimitError,         # rate limit exhausted
    ValidationError,        # invalid request parameters
    IntegrityError,         # report integrity check failure
)

try:
    result = evaluate_github_profile(request)
except AuthenticationError:
    print("Set GITHUB_TOKEN or pass github_token in the request")
except ValidationError as e:
    print(f"Bad request: {e.details}")
except OpportunityTxtError as e:
    print(f"Evaluation failed: {e}")
```

## Run modes

- **`user`** — Returns display-safe artifacts: report, summary, markdown. Evidence and signals are excluded. This is what a portal should consume.
- **`debug`** — Additionally exposes full evidence snapshot, signal snapshot, detailed integrity issues, and route-level diagnostics.
