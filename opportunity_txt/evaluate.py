"""Public entry point for the opportunity_txt evaluation engine.

Usage:

    from opportunity_txt import evaluate_github_profile
    from opportunity_txt.models import EvaluateGitHubProfileRequest

    request = EvaluateGitHubProfileRequest(github_username="torvalds")
    result = evaluate_github_profile(request)
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from .cache import Cache, FileCache
from .dimensions import evaluate as _evaluate_dimensions
from .errors import IntegrityError, UnsupportedRequestError, ValidationError
from .models import (
    ArchetypeResult,
    BuilderRouteHighlight,
    CompactSummary,
    DimensionSummaryEntry,
    EvaluateGitHubProfileRequest,
    EvaluateGitHubProfileResult,
    EvaluationReport,
    EvaluationScope,
    IntegritySection,
    MaturitySection,
    MethodologySection,
    ReadinessSection,
    RepositoryEntry,
    SignalHighlights,
    SubjectSummary,
)
from .normalizer import collect_and_normalize
from .report import _render_report
from .signals import compute_signals

_SUPPORTED_METHODOLOGY = "1.0.0"
_SCHEMA_VERSION = "1.0.0"
_VALID_WINDOWS = {"1y", "2y", "3y", "5y", "all"}
_VALID_MODES = {"user", "debug"}


def evaluate_github_profile(
    request: EvaluateGitHubProfileRequest,
    *,
    cache: Cache | None = None,
) -> EvaluateGitHubProfileResult:
    """Run the full evaluation pipeline and return a structured result.

    Parameters
    ----------
    request:
        Structured evaluation request.
    cache:
        Optional cache for GitHub API responses.  Defaults to no caching.
    """
    # -- Validate request --
    _validate_request(request)

    # -- Pipeline: collect → normalize → signals → dimensions --
    evidence = collect_and_normalize(
        request.github_username,
        window=request.observation_window,
        max_repos=request.max_repositories,
        cache=cache,
        token=request.github_token,
    )

    signals = compute_signals(evidence)
    eval_result = _evaluate_dimensions(evidence, signals)

    # -- Build structured report --
    report = _build_report(evidence, signals, eval_result)

    # -- Build compact summary --
    summary: CompactSummary | None = None
    if request.include_summary:
        summary = _build_summary(eval_result, signals)

    # -- Render markdown --
    markdown: str | None = None
    if request.include_markdown_report:
        markdown = _render_report(evidence, signals, eval_result)

    # -- Integrity enforcement (strict in user mode) --
    ri = signals.report_integrity
    if request.run_mode == "user" and not ri.report_integrity_passed:
        report.integrity = IntegritySection(
            passed=False,
            degraded=True,
            mode="user",
            issue_summary=list(ri.integrity_issues),
            auto_corrections=list(ri.auto_corrections_applied),
        )

    # -- Assemble result --
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = EvaluateGitHubProfileResult(
        methodology_version=_SUPPORTED_METHODOLOGY,
        schema_version=_SCHEMA_VERSION,
        generated_at=generated_at,
        report=report,
        markdown_report=markdown,
        summary=summary,
        evidence=evidence.to_dict() if request.include_raw_evidence else None,
        signals=signals.to_dict() if request.include_signals else None,
    )

    # -- run_mode gating --
    if request.run_mode == "user":
        result = _gate_user_mode(result)

    return result


# -------------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------------

def _validate_request(req: EvaluateGitHubProfileRequest) -> None:
    errors: list[str] = []
    if not req.github_username or not req.github_username.strip():
        errors.append("github_username is required")
    if req.observation_window not in _VALID_WINDOWS:
        errors.append(f"observation_window must be one of {_VALID_WINDOWS}")
    if req.max_repositories < 1:
        errors.append("max_repositories must be >= 1")
    if req.run_mode not in _VALID_MODES:
        errors.append(f"run_mode must be one of {_VALID_MODES}")
    if errors:
        raise ValidationError(message="Invalid request", details=errors)


def _build_report(evidence, signals, eval_result) -> EvaluationReport:
    """Build the structured EvaluationReport from pipeline outputs."""
    p = evidence.profile
    meta = evidence.collection_metadata

    subject = SubjectSummary(
        username=p.username,
        name=p.name,
        account_created=p.created_at[:10] if p.created_at else None,
        public_repos=p.public_repo_count,
        followers=p.followers,
        bio=p.bio if hasattr(p, "bio") else None,
    )

    scope = EvaluationScope(
        window_start=eval_result.observation_window_start,
        window_end=eval_result.observation_window_end,
        repos_evaluated=eval_result.repos_evaluated,
        pull_requests_collected=meta.get("prs_collected", 0),
        reviews_collected=meta.get("reviews_collected", 0),
        issues_collected=meta.get("issues_collected", 0),
        releases_collected=meta.get("releases_collected", 0),
        counterparties_tracked=meta.get("counterparties_tracked", 0),
    )

    # Maturity
    mat = signals.maturity
    er = signals.evidence_regime
    maturity = MaturitySection(
        band=mat.maturity_band,
        basis=mat.maturity_basis,
        evidence_regime=er.evidence_regime,
        source_tier=er.specialization_source_tier,
    )

    # Readiness
    readiness = None
    if eval_result.stage_interpretation:
        si = eval_result.stage_interpretation
        readiness = ReadinessSection(
            contributor_type=si.contributor_type,
            readiness_summary=si.readiness_summary,
            promise_summary=si.promise_summary,
        )

    # Repository set
    repo_entries = []
    for r in evidence.repositories:
        repo_entries.append(RepositoryEntry(
            name=r.name,
            owner=r.owner,
            stars=r.stars,
            language=r.primary_language,
            role="owner" if r.owner.lower() == p.username.lower() else "contributor",
        ))

    # Signal highlights — builder routes
    builder_routes = []
    bs = signals.builder_sophistication
    builder_routes.append(BuilderRouteHighlight(
        route_label="Route A (PR delivery)",
        active=bs.builder_signal_path in ("pr_delivery", "mixed"),
        key_signals={
            "builder_sophistication_signal": bs.builder_sophistication_signal,
            "delivery_depth_signal": bs.delivery_depth_signal,
        },
    ))
    builder_routes.append(BuilderRouteHighlight(
        route_label="Route B (repo substance)",
        active=bs.repo_substance_score > 0,
        key_signals={
            "repo_substance_score": bs.repo_substance_score,
            "owned_repo_complexity_score": bs.owned_repo_complexity_score,
        },
    ))
    fb = signals.foundational_builder
    builder_routes.append(BuilderRouteHighlight(
        route_label="Route C (foundational infrastructure)",
        active=fb.foundational_infrastructure_builder_signal > 0.3,
        key_signals={
            "foundational_signal": fb.foundational_infrastructure_builder_signal,
            "central_repo_substance": fb.central_repo_substance_score,
        },
    ))

    signal_highlights = SignalHighlights(
        builder_routes=builder_routes,
        contribution_highlights={
            "merged_pr_count": signals.contribution.merged_pr_count,
            "independent_acceptance_count": signals.contribution.independent_acceptance_count,
            "merge_ratio": signals.contribution.merge_ratio,
        },
        evidence_regime_detail={
            "regime": er.evidence_regime,
            "sparse_flag": er.sparse_evidence_flag,
            "total_artifacts": er.total_collected_artifacts,
            "source_tier": er.specialization_source_tier,
        },
        specialization_summary={
            "primary_domain": eval_result.domain_inference.primary_domain,
            "secondary_domains": eval_result.domain_inference.secondary_domains,
            "confidence": eval_result.domain_inference.confidence,
        },
    )

    # Integrity
    ri = signals.report_integrity
    integrity = IntegritySection(
        passed=ri.report_integrity_passed,
        degraded=ri.report_degraded_flag,
        mode=ri.integrity_mode,
        issue_summary=list(ri.integrity_issues),
        auto_corrections=list(ri.auto_corrections_applied),
    )

    # Limitations
    limitations = _compute_limitations(eval_result, signals)

    return EvaluationReport(
        subject=subject,
        scope=scope,
        archetypes=list(eval_result.archetypes),
        maturity=maturity,
        dimensions=list(eval_result.final_dimensions),
        readiness=readiness,
        signal_highlights=signal_highlights,
        repository_set=repo_entries,
        limitations=limitations,
        integrity=integrity,
        methodology=MethodologySection(
            methodology_version=eval_result.methodology_version,
            schema_version=_SCHEMA_VERSION,
        ),
        domain_inference=eval_result.domain_inference,
    )


def _compute_limitations(eval_result, signals) -> list[str]:
    """Compute report limitations from evaluation state."""
    lims: list[str] = []

    er = signals.evidence_regime
    if er.sparse_evidence_flag:
        lims.append(
            "Evidence regime is sparse. Scores and interpretations are based on "
            "limited public data and may not reflect actual ability."
        )
    elif er.evidence_regime == "limited":
        lims.append(
            "Evidence regime is limited. Some dimensions may have reduced "
            "confidence due to incomplete public activity records."
        )

    for fd in eval_result.final_dimensions:
        if fd.status == "not_reliably_observable":
            lims.append(
                f"{fd.name} is not reliably observable from available evidence."
            )
        if fd.score_cap_applied and fd.cap_reason:
            lims.append(f"{fd.name}: {fd.cap_reason}")
        if fd.limitation:
            lims.append(fd.limitation)

    return lims


def _build_summary(eval_result, signals) -> CompactSummary:
    """Build a compact summary from evaluation results."""
    dim_entries = []
    for fd in eval_result.final_dimensions:
        dim_entries.append(DimensionSummaryEntry(
            name=fd.name,
            status=fd.status,
            score_label=fd.score_label,
            confidence_label=fd.confidence_label,
        ))

    mat = signals.maturity
    er = signals.evidence_regime
    di = eval_result.domain_inference

    return CompactSummary(
        username=eval_result.subject,
        maturity_band=mat.maturity_band,
        evidence_regime=er.evidence_regime,
        primary_domain=di.primary_domain,
        secondary_domains=list(di.secondary_domains),
        dimensions=dim_entries,
        readiness_summary=(
            eval_result.stage_interpretation.readiness_summary
            if eval_result.stage_interpretation else ""
        ),
        methodology_version=eval_result.methodology_version,
    )


def _gate_user_mode(result: EvaluateGitHubProfileResult) -> EvaluateGitHubProfileResult:
    """Strip debug-only fields from user-mode result.

    In user mode:
    - evidence is excluded (set to None)
    - signals are excluded (set to None)
    - report and summary remain full
    """
    result.evidence = None
    result.signals = None
    return result
