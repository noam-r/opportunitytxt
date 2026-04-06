"""Dimension evaluation, confidence estimation, and archetype detection (v0.9).

Maps computed signals into seven scored dimensions, each with a score band,
a confidence band, and an observability status, plus explainability fields.

v0.9 changes:
- Sparse-evidence specialization cap (§4.2): evidence_regime == sparse → cap Moderate
- Foundational Infrastructure Builder archetype detection
- Builder Route C: foundational builder scoring for steward profiles
- Temporal edge-case safety: invalid denominators → NRO consistency
- Sparse-profile specialization wording (directionality, not concentration)
- Foundational builder wording in builder sophistication interpretation
- Secondary-domain cleanup for central low-level profiles
"""

from __future__ import annotations

from .models import (
    Archetype,
    ArchetypeResult,
    ConfidenceBand,
    DimensionResult,
    DomainInference,
    EvaluationResult,
    Evidence,
    FinalDimensionResult,
    MaturityBand,
    ObservabilityStatus,
    ScoreBand,
    SignalSet,
    StageInterpretation,
)


# =====================================================================
# Helper: threshold -> band mapping
# =====================================================================

def _band(value: float, thresholds: list[tuple[float, ScoreBand]]) -> ScoreBand:
    """Return the highest band whose threshold is met.

    *thresholds* must be sorted ascending by threshold value.
    """
    result = ScoreBand.LOW
    for threshold, band in thresholds:
        if value >= threshold:
            result = band
    return result


def _conf(value: float) -> ConfidenceBand:
    if value >= 0.65:
        return ConfidenceBand.HIGH
    if value >= 0.35:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


_SCORE_ORDER = [ScoreBand.LOW, ScoreBand.EMERGING, ScoreBand.MODERATE,
                ScoreBand.STRONG, ScoreBand.VERY_STRONG]


def _cap_score(score: ScoreBand, max_band: ScoreBand) -> ScoreBand:
    """Cap *score* to at most *max_band*."""
    if _SCORE_ORDER.index(score) > _SCORE_ORDER.index(max_band):
        return max_band
    return score


# =====================================================================
# Archetype detection (v0.3)
# =====================================================================

def _detect_archetypes(sig: SignalSet) -> list[ArchetypeResult]:
    results: list[ArchetypeResult] = []
    c = sig.contribution
    op = sig.owned_projects
    st = sig.stewardship
    ei = sig.execution_intensity
    cs = sig.consistency

    # 1. External Contributor
    has_independent = c.independent_acceptance_count >= 3
    has_ext_repos = c.repos_with_merged_contributions_external >= 2
    ext_conf = (
        min(c.independent_acceptance_count / 10, 1.0) * 0.5
        + min(c.repos_with_merged_contributions_external / 5, 1.0) * 0.5
    )
    results.append(ArchetypeResult(
        archetype=Archetype.EXTERNAL_CONTRIBUTOR,
        detected=has_independent and has_ext_repos,
        confidence=ext_conf,
        basis=(
            f"{c.independent_acceptance_count} independently accepted PRs "
            f"across {c.repos_with_merged_contributions_external} external repos."
        ),
    ))

    # 2. Independent Builder
    has_owned = op.owned_public_project_count >= 1
    has_activity = c.authored_repo_activity_signal > 0.3
    builder_conf = (
        min(op.owned_public_project_count / 5, 1.0) * 0.5
        + c.authored_repo_activity_signal * 0.5
    )
    results.append(ArchetypeResult(
        archetype=Archetype.INDEPENDENT_BUILDER,
        detected=has_owned and has_activity,
        confidence=builder_conf,
        basis=(
            f"{op.owned_public_project_count} owned public projects, "
            f"authored activity signal: {c.authored_repo_activity_signal:.2f}."
        ),
    ))

    # 3. Owned Public Project Maintainer
    has_adopted = op.owned_public_project_visibility_score >= 3.0
    has_releases = op.owned_public_project_release_count >= 1
    has_maintenance = op.owned_public_project_maintenance_score >= 0.3
    maintainer_detected = has_adopted and (has_releases or has_maintenance)
    maintainer_conf = (
        min(op.owned_public_project_visibility_score / 10, 1.0) * 0.4
        + (0.3 if has_releases else 0.0)
        + min(op.owned_public_project_maintenance_score, 1.0) * 0.3
    )
    results.append(ArchetypeResult(
        archetype=Archetype.OWNED_PROJECT_MAINTAINER,
        detected=maintainer_detected,
        confidence=maintainer_conf,
        basis=(
            f"Owned project visibility: {op.owned_public_project_visibility_score:.1f}, "
            f"releases: {op.owned_public_project_release_count}, "
            f"maintenance: {op.owned_public_project_maintenance_score:.2f}."
        ),
    ))

    # 4. Maintainer / Steward / Governor
    has_stewardship = st.stewardship_signal >= 0.25
    has_governance = st.repo_governance_activity_score >= 0.2
    has_centrality = st.owned_repo_centrality_score >= 2.0
    steward_detected = has_stewardship and (has_governance or has_centrality)
    steward_conf = (
        min(st.stewardship_signal, 1.0) * 0.5
        + min(st.owned_repo_centrality_score / 10, 1.0) * 0.3
        + min(st.issue_participation_count / 20, 1.0) * 0.2
    )
    results.append(ArchetypeResult(
        archetype=Archetype.MAINTAINER_STEWARD,
        detected=steward_detected,
        confidence=steward_conf,
        basis=(
            f"Stewardship signal: {st.stewardship_signal:.2f}, "
            f"governance: {st.repo_governance_activity_score:.2f}, "
            f"centrality: {st.owned_repo_centrality_score:.1f}, "
            f"issue participation: {st.issue_participation_count}."
        ),
    ))

    # 5. Burst Execution Profile
    has_high_intensity = ei.burst_execution_score >= 0.4
    low_consistency = cs.active_month_ratio < 0.3 or cs.active_quarter_count <= 4
    burst_detected = has_high_intensity and low_consistency
    burst_conf = (
        min(ei.burst_execution_score, 1.0) * 0.6
        + (0.4 if low_consistency else 0.0)
    )
    results.append(ArchetypeResult(
        archetype=Archetype.BURST_EXECUTION,
        detected=burst_detected,
        confidence=burst_conf,
        basis=(
            f"Execution score: {ei.burst_execution_score:.2f}, "
            f"active month ratio: {cs.active_month_ratio:.0%}, "
            f"active quarters: {cs.active_quarter_count}."
        ),
    ))

    # 6. Sustained Public Contributor
    has_spread = cs.active_month_ratio >= 0.25
    has_return = cs.repeat_return_repos >= 2
    has_quarters = cs.active_quarter_count >= 6
    sustained_detected = has_spread and has_return and has_quarters
    sustained_conf = (
        min(cs.active_month_ratio / 0.5, 1.0) * 0.4
        + min(cs.repeat_return_repos / 5, 1.0) * 0.3
        + min(cs.active_quarter_count / 10, 1.0) * 0.3
    )
    results.append(ArchetypeResult(
        archetype=Archetype.SUSTAINED_CONTRIBUTOR,
        detected=sustained_detected,
        confidence=sustained_conf,
        basis=(
            f"Active month ratio: {cs.active_month_ratio:.0%}, "
            f"repeat-return repos: {cs.repeat_return_repos}, "
            f"active quarters: {cs.active_quarter_count}."
        ),
    ))

    # 7. Complex Product Builder (v0.6)
    bs = sig.builder_sophistication
    has_sophistication = bs.builder_sophistication_signal >= 0.25
    has_delivery = bs.repeated_feature_delivery_count >= 1 or bs.repeated_major_delivery_count >= 1
    has_complexity = bs.large_pr_count >= 3 and bs.large_pr_repo_count >= 1
    cpb_detected = has_sophistication and (has_delivery or has_complexity)
    cpb_conf = bs.complex_product_builder_strength
    results.append(ArchetypeResult(
        archetype=Archetype.COMPLEX_PRODUCT_BUILDER,
        detected=cpb_detected,
        confidence=cpb_conf,
        basis=(
            f"Builder sophistication: {bs.builder_sophistication_signal:.2f}, "
            f"large PRs: {bs.large_pr_count}, "
            f"large PR repos: {bs.large_pr_repo_count}, "
            f"repeated feature delivery: {bs.repeated_feature_delivery_count}, "
            f"owned repo complexity: {bs.owned_repo_complexity_score:.2f}."
        ),
    ))

    # 8. Foundational Infrastructure Builder (v0.9)
    fb = sig.foundational_builder
    fib_detected = (
        fb.foundational_infrastructure_builder_signal >= 0.4
        and st.owned_repo_centrality_score >= 5.0
        and st.owned_repo_public_reliance_score >= 0.3
    )
    fib_conf = min(fb.foundational_infrastructure_builder_signal, 1.0)
    results.append(ArchetypeResult(
        archetype=Archetype.FOUNDATIONAL_INFRASTRUCTURE_BUILDER,
        detected=fib_detected,
        confidence=fib_conf,
        basis=(
            f"Foundational builder signal: {fb.foundational_infrastructure_builder_signal:.2f}, "
            f"centrality: {st.owned_repo_centrality_score:.1f}, "
            f"public reliance: {st.owned_repo_public_reliance_score:.2f}, "
            f"technical foundation: {fb.technical_foundation_signal:.2f}, "
            f"systems scope: {fb.systems_scope_signal:.2f}."
        ),
    ))

    return results


# =====================================================================
# Per-dimension evaluators
# =====================================================================

def _eval_contribution(sig: SignalSet) -> DimensionResult:
    c = sig.contribution
    op = sig.owned_projects
    ei = sig.execution_intensity
    sc = sig.steward_contribution

    # v0.4: multi-path contribution -- three valid evidence routes
    # Route A: Independent accepted contribution (best for external contributors)
    independent_score = min(c.independent_acceptance_count / 10, 1.0)
    independent_breadth = min(c.independent_acceptance_repo_count / 5, 1.0)
    repeat_external = min(c.repeat_external_accepted_contribution_count / 4, 1.0)
    throughput_score = min(c.merged_contributions_per_active_month / 4, 1.0)

    route_a = (
        independent_score * 0.35
        + independent_breadth * 0.20
        + repeat_external * 0.20
        + throughput_score * 0.15
        + ei.burst_execution_score * 0.10
    )

    # Route B: Owned public project output (best for builders)
    route_b = sc.owned_public_build_signal

    # Route C: Steward / governance contribution (best for maintainers/stewards)
    route_c = sc.steward_contribution_signal

    # v0.6 Route D: Complex self-directed building
    # Allows builder sophistication to partially raise contribution,
    # but NOT as much as trust/adoption (capped contribution from this route)
    bs = sig.builder_sophistication
    route_d = bs.builder_sophistication_signal * 0.75  # intentionally dampened

    # Max-of-paths: use the strongest route, with small cross-path bonus
    routes = sorted([route_a, route_b, route_c, route_d], reverse=True)
    composite = routes[0] * 0.65 + routes[1] * 0.20 + routes[2] * 0.10 + routes[3] * 0.05

    score = _band(composite, [
        (0.10, ScoreBand.EMERGING),
        (0.25, ScoreBand.MODERATE),
        (0.50, ScoreBand.STRONG),
        (0.75, ScoreBand.VERY_STRONG),
    ])

    # Gate: self-merged-only work caps at Moderate
    # Exception: strong stewardship or owned project evidence bypasses the cap
    if c.merged_pr_count_external == 0 and c.externally_merged_pr_count == 0:
        has_strong_stewardship = sc.steward_contribution_signal >= 0.3
        has_strong_owned = op.owned_public_project_visibility_score >= 5.0
        if not has_strong_stewardship and not has_strong_owned:
            score = _cap_score(score, ScoreBand.MODERATE)

    # v0.5: stronger cap for self-governed-only burst profiles
    # If ALL strong-trust routes are absent, cap contribution more aggressively
    # v0.6: builder sophistication can partially lift the cap from Emerging to Moderate
    cc = sig.contribution_calibration
    if cc.independent_validation_absence and cc.self_governed_execution_ratio >= 0.8:
        # Strong builder sophistication can lift to Moderate (but not higher)
        if bs.builder_sophistication_signal >= 0.35:
            score = _cap_score(score, ScoreBand.MODERATE)
        else:
            score = _cap_score(score, ScoreBand.EMERGING)
    elif cc.self_governed_execution_ratio >= 0.9 and c.independent_acceptance_count == 0:
        if not (op.owned_public_project_visibility_score >= 3.0 or sc.steward_contribution_signal >= 0.2):
            score = _cap_score(score, ScoreBand.MODERATE)

    # Confidence: v0.4 includes steward/owned evidence paths
    has_independent = c.independent_acceptance_count > 0
    has_owned_evidence = op.owned_public_project_visibility_score >= 3.0
    has_steward_evidence = sc.steward_contribution_signal >= 0.2
    evidence_points = (
        min(c.total_prs_opened / 15, 1.0) * 0.15
        + min(c.repos_with_merged_contributions / 5, 1.0) * 0.15
        + min(c.independent_acceptance_count / 5, 1.0) * 0.20
        + min(c.repeat_merged_contribution_count / 3, 1.0) * 0.10
        + min(op.owned_public_project_visibility_score / 5, 1.0) * 0.20
        + min(sc.steward_contribution_signal / 0.5, 1.0) * 0.20
    )
    confidence = _conf(evidence_points)
    if not has_independent and not has_owned_evidence and not has_steward_evidence:
        if confidence == ConfidenceBand.HIGH:
            confidence = ConfidenceBand.MEDIUM

    merged = c.merged_pr_count
    total = c.total_prs_opened
    repos = c.repos_with_merged_contributions

    limitation_parts = [
        "Contribution quality is inferred from acceptance patterns, "
        "project ownership, and execution intensity.",
        "Private work and non-PR workflows are not visible.",
    ]
    if c.independent_acceptance_count == 0 and c.merged_pr_count > 0:
        limitation_parts.append(
            "No independently accepted PRs detected -- all external merges "
            "may be self-governed."
        )
    if c.merged_pr_count_external == 0 and c.merged_pr_count > 0:
        limitation_parts.append(
            "All merged PRs are in self-owned repositories -- "
            "no external acceptance evidence is available."
        )

    return DimensionResult(
        name="Contribution Quality",
        score=score,
        confidence=confidence,
        claim=(
            f"Merged {merged} of {total} PRs across {repos} repositories "
            f"({c.independent_acceptance_count} independently accepted, "
            f"{c.merged_pr_count_self_owned} self-owned). "
            f"Owned {op.owned_public_project_count} public projects."
        ),
        evidence_summary=(
            f"Independent acceptance: {c.independent_acceptance_count} "
            f"across {c.independent_acceptance_repo_count} repos "
            f"(ratio: {c.independent_acceptance_ratio:.0%}). "
            f"Owned project visibility: {op.owned_public_project_visibility_score:.1f}. "
            f"Execution intensity: {ei.burst_execution_score:.2f}."
        ),
        interpretation=_contribution_interpretation(score, c, op, sig.steward_contribution, bs),
        limitation=" ".join(limitation_parts),
    )


def _contribution_interpretation(score: ScoreBand, c, op, sc, bs=None) -> str:
    has_independent = c.independent_acceptance_count > 0
    has_owned = op.owned_public_project_visibility_score >= 3.0
    has_stewardship = sc.steward_contribution_signal >= 0.2
    has_builder = bs is not None and bs.builder_sophistication_signal >= 0.25

    if score == ScoreBand.VERY_STRONG:
        if has_stewardship:
            return (
                "Public evidence shows exceptional contribution through stewardship "
                "of central public infrastructure, project ownership, and/or "
                "independently accepted contributions."
            )
        return (
            "Public evidence shows consistently accepted contributions "
            "with strong independent external acceptance and/or significant "
            "owned project footprint."
        )
    if score == ScoreBand.STRONG:
        if has_stewardship and has_owned:
            return (
                "Public evidence shows strong contribution through stewardship "
                "of adopted public projects and visible maintenance activity."
            )
        if has_independent and has_owned:
            return (
                "Public evidence shows solid contribution through both "
                "external acceptance and meaningful owned project building."
            )
        if has_stewardship:
            return (
                "Public evidence shows meaningful contribution through "
                "stewardship, governance, and project maintenance activity."
            )
        if has_independent:
            return (
                "Public evidence shows solid contribution patterns with "
                "independently accepted external work."
            )
        if has_owned:
            return (
                "Public evidence shows meaningful contribution through "
                "owned public projects with visible adoption."
            )
        return (
            "Public evidence shows solid contribution patterns, though "
            "independent acceptance evidence is limited."
        )
    if score == ScoreBand.MODERATE:
        if has_builder and not has_independent and not has_owned:
            return (
                "Visible non-trivial self-directed product/system building "
                "with limited independent external validation so far. "
                "Builder sophistication is recognized separately."
            )
        if has_stewardship:
            return (
                "Moderate contribution visible through stewardship and "
                "maintenance, though independent acceptance scope is limited."
            )
        if not has_independent and not has_owned:
            return (
                "Public evidence shows activity primarily in self-governed "
                "contexts. Neither independent external acceptance nor "
                "adopted owned projects are visible."
            )
        return (
            "Public evidence shows meaningful contributions, though breadth "
            "or independent acceptance is moderate."
        )
    if score == ScoreBand.EMERGING:
        if has_builder:
            return (
                "Early-stage contribution activity with some visible "
                "self-directed building. Volume, external acceptance, or "
                "project adoption is limited, but builder sophistication "
                "is noted separately."
            )
        return (
            "Early-stage contribution activity. "
            "Volume, external acceptance, or project adoption is limited."
        )
    return (
        "Insufficient public contribution evidence to assess contribution quality. "
        "This does not reflect the contributor's actual ability."
    )


# ------------------------------------------------------------------

def _eval_collaboration(sig: SignalSet, archetypes: list[ArchetypeResult]) -> DimensionResult:
    co = sig.collaboration
    st = sig.stewardship

    # Detect if steward archetype is present
    is_steward = any(
        a.detected and a.archetype == Archetype.MAINTAINER_STEWARD
        for a in archetypes
    )

    # v0.5: archetype-sensitive collaboration weights
    if is_steward:
        # For stewards, weight issue-based collaboration more heavily
        review_score = min(co.review_activity_count / 20, 1.0)
        substantive_score = min(co.substantive_review_count / 10, 1.0)
        diversity_score = min(co.counterparty_count / 8, 1.0)
        multi_type_score = min(co.repos_with_repeated_collaboration / 5, 1.0)
        feedback_score = min(co.accepted_after_feedback_count / 10, 1.0)
        iteration_score = min(co.review_iteration_count / 5, 1.0)
        issue_score = min(st.issue_participation_count / 15, 1.0)
        governance_score = min(st.repo_governance_activity_score / 0.5, 1.0)

        composite = (
            review_score * 0.08
            + substantive_score * 0.12
            + diversity_score * 0.12
            + multi_type_score * 0.08
            + feedback_score * 0.08
            + iteration_score * 0.08
            + issue_score * 0.24
            + governance_score * 0.20
        )
    else:
        review_score = min(co.review_activity_count / 20, 1.0)
        substantive_score = min(co.substantive_review_count / 10, 1.0)
        diversity_score = min(co.counterparty_count / 8, 1.0)
        multi_type_score = min(co.repos_with_repeated_collaboration / 5, 1.0)
        feedback_score = min(co.accepted_after_feedback_count / 10, 1.0)
        iteration_score = min(co.review_iteration_count / 5, 1.0)
        issue_score = min(st.issue_participation_count / 15, 1.0)

        composite = (
            review_score * 0.12
            + substantive_score * 0.18
            + diversity_score * 0.18
            + multi_type_score * 0.12
            + feedback_score * 0.12
            + iteration_score * 0.13
            + issue_score * 0.15
        )

    score = _band(composite, [
        (0.10, ScoreBand.EMERGING),
        (0.25, ScoreBand.MODERATE),
        (0.50, ScoreBand.STRONG),
        (0.75, ScoreBand.VERY_STRONG),
    ])

    # Gate: cannot exceed Moderate without multi-repo or repeated interaction
    has_multi_repo = co.repos_with_repeated_collaboration >= 2
    has_repeated = co.repeated_counterparty_count >= 2
    has_issue_depth = st.issue_participation_count >= 5
    if not has_multi_repo and not has_repeated and not has_issue_depth:
        score = _cap_score(score, ScoreBand.MODERATE)

    evidence_points = (
        min(co.review_activity_count / 10, 1.0) * 0.20
        + min(co.counterparty_count / 5, 1.0) * 0.20
        + min(co.repos_with_repeated_collaboration / 3, 1.0) * 0.20
        + min(co.issue_discussion_count / 10, 1.0) * 0.20
        + min(st.issue_participation_count / 10, 1.0) * 0.20
    )
    confidence = _conf(evidence_points)
    # v0.3: sparse evidence reduces confidence, not score
    if evidence_points < 0.15:
        confidence = ConfidenceBand.LOW

    collab_obs = sig.dimension_coverage.collaboration_observability_status

    return DimensionResult(
        name="Collaboration Quality",
        score=score,
        confidence=confidence,
        observability_status=collab_obs,
        claim=(
            f"Reviewed {co.review_activity_count} PRs, interacted with "
            f"{co.counterparty_count} distinct collaborators, participated in "
            f"{st.issue_participation_count} issues across "
            f"{co.repos_with_repeated_collaboration} repos with multi-type collaboration."
        ),
        evidence_summary=(
            f"Substantive reviews: {co.substantive_review_count}. "
            f"Issue discussions: {co.issue_discussion_count}. "
            f"Issue participation: {st.issue_participation_count}. "
            f"PRs merged after review feedback: {co.accepted_after_feedback_count}. "
            f"Review iterations: {co.review_iteration_count}. "
            f"Repeated counterparties: {co.repeated_counterparty_count}. "
            f"Multi-repo counterparties: {co.multi_repo_counterparty_count}."
        ),
        interpretation=_collaboration_interpretation(score, is_steward, st),
        limitation=(
            "Collaboration quality is inferred from public review, issue, and PR "
            "interactions. Private channels, pair programming, and verbal "
            "collaboration are not visible. "
            + ("For steward profiles, issue and governance interaction is "
               "weighted more heavily, but PR-centric collaboration data "
               "may still underrepresent real collaborative activity. "
               if is_steward else "")
            + "Sparse public interaction evidence lowers confidence, not the "
            "person's actual collaboration ability."
        ),
    )


def _collaboration_interpretation(score: ScoreBand, is_steward: bool, st) -> str:
    if score in (ScoreBand.VERY_STRONG, ScoreBand.STRONG):
        if is_steward:
            return (
                "Public evidence shows active collaboration through issue governance, "
                "stewardship interactions, and community engagement."
            )
        return (
            "Public evidence shows active collaboration across reviews, issues, "
            "and PR discussions with diverse collaborators."
        )
    if score == ScoreBand.MODERATE:
        if is_steward:
            return (
                "Moderate collaboration visibility. Steward-relevant interactions "
                "(issues, governance) are present but PR-centric collaboration "
                "data may undercount real activity."
            )
        return (
            "Public evidence shows some collaborative activity, though review "
            "depth or diversity is moderate."
        )
    if score == ScoreBand.EMERGING:
        if is_steward:
            return (
                "Limited visible collaboration in the collected data. "
                "Steward profiles often have collaboration patterns not fully "
                "captured by PR-centric collection."
            )
        return "Limited but observable public collaboration signals."
    if is_steward:
        return (
            "Insufficient public collaboration evidence. "
            "Steward-relevant interactions may not be fully visible."
        )
    return "Insufficient public collaboration evidence."


# ------------------------------------------------------------------

def _eval_trust(sig: SignalSet) -> DimensionResult:
    t = sig.trust
    c = sig.contribution
    op = sig.owned_projects
    st = sig.stewardship

    # v0.3: multi-path trust -- independent acceptance OR stewardship OR owned adoption
    # Path 1: Independent external acceptance
    independent_score = min(c.independent_acceptance_count / 8, 1.0)
    independent_breadth = min(c.independent_acceptance_repo_count / 3, 1.0)
    ext_sustained = min(t.sustained_external_repos / 3, 1.0)

    # Path 2: Stewardship of adopted repos
    stewardship_score = st.stewardship_signal
    owned_adoption = min(op.owned_public_project_visibility_score / 10, 1.0)

    # Path 3: Classic repeat-merge signals
    ext_repeat = min(t.repeat_merges_external_repo / 3, 1.0)
    release_score = min(t.repos_with_release_involvement / 3, 1.0)

    # Best-of multi-path: whichever path yields more evidence
    auth_trust = (
        independent_score * 0.40
        + independent_breadth * 0.25
        + ext_sustained * 0.20
        + ext_repeat * 0.15
    )

    steward_trust = (
        stewardship_score * 0.35
        + owned_adoption * 0.30
        + release_score * 0.20
        + min(t.owned_repos_with_external_stars / 4, 1.0) * 0.15
    )

    # v0.5: external-repo self-merged discount
    # External repos where contributor self-merges are NOT independent validation
    ext_self_merged_penalty = 0.0
    if c.external_repo_self_merged_pr_count > 0 and c.independent_acceptance_count == 0:
        # Heavy discount: external self-merged without any independent acceptance
        ext_self_merged_penalty = min(c.external_repo_self_merged_pr_count / 10, 0.15)
        auth_trust = max(auth_trust - ext_self_merged_penalty, 0.0)

    # Use the stronger of the two paths, with a small bonus for both
    if auth_trust > steward_trust:
        composite = auth_trust * 0.80 + steward_trust * 0.20
    else:
        composite = steward_trust * 0.80 + auth_trust * 0.20

    score = _band(composite, [
        (0.10, ScoreBand.EMERGING),
        (0.25, ScoreBand.MODERATE),
        (0.50, ScoreBand.STRONG),
        (0.75, ScoreBand.VERY_STRONG),
    ])

    # Gate: no external acceptance AND no stewardship -> Emerging max
    has_ext_acceptance = t.external_acceptance_visible or c.independent_acceptance_count > 0
    has_stewardship = stewardship_score >= 0.2 or op.owned_public_project_visibility_score >= 3.0
    if not has_ext_acceptance and not has_stewardship:
        score = _cap_score(score, ScoreBand.EMERGING)

    # v0.5: external-repo self-merged without independent acceptance caps trust
    if c.external_repo_self_merged_pr_count > 0 and c.independent_acceptance_count == 0:
        if not has_stewardship:
            score = _cap_score(score, ScoreBand.MODERATE)

    evidence_points = (
        min(c.independent_acceptance_count / 5, 1.0) * 0.25
        + min(t.sustained_repos / 3, 1.0) * 0.20
        + (1.0 if t.repos_with_release_involvement > 0 else 0.0) * 0.15
        + min(t.owned_repos_with_external_stars / 2, 1.0) * 0.20
        + min(st.stewardship_signal / 0.5, 1.0) * 0.20
    )
    confidence = _conf(evidence_points)

    limitation_parts = [
        "Trust signals are based on independent acceptance patterns, "
        "sustained engagement, stewardship activity, and release history.",
        "Organizational trust, private access roles, and internal "
        "maintainership are not visible.",
    ]
    if not has_ext_acceptance:
        limitation_parts.append(
            "No independently accepted PRs in external repos were detected."
        )
    if not has_stewardship:
        limitation_parts.append(
            "No significant stewardship or project ownership evidence detected."
        )

    return DimensionResult(
        name="Maintainer / Community Trust",
        score=score,
        confidence=confidence,
        claim=(
            f"Independently accepted PRs: {c.independent_acceptance_count} "
            f"across {c.independent_acceptance_repo_count} repos. "
            f"Stewardship signal: {st.stewardship_signal:.2f}. "
            f"Sustained repos (>6mo): {t.sustained_repos} "
            f"({t.sustained_external_repos} external). "
            f"Release repos: {t.repos_with_release_involvement}."
        ),
        evidence_summary=(
            f"Author trust path: {auth_trust:.2f}. "
            f"Steward trust path: {steward_trust:.2f}. "
            f"Owned project visibility: {op.owned_public_project_visibility_score:.1f}. "
            f"Issue response activity: {st.issue_response_activity_count}. "
            f"Maintainer visibility: {st.maintainer_visibility_score:.2f}."
        ),
        interpretation=_trust_interpretation(score, t, c, st),
        limitation=" ".join(limitation_parts),
    )


def _trust_interpretation(score: ScoreBand, t, c, st) -> str:
    has_independent = c.independent_acceptance_count > 0
    has_stewardship = st.stewardship_signal >= 0.2
    has_limited_stewardship = st.stewardship_signal > 0.05

    if score in (ScoreBand.VERY_STRONG, ScoreBand.STRONG):
        if has_independent and has_stewardship:
            return (
                "Strong trust evidence through both independent external acceptance "
                "and visible stewardship of public projects."
            )
        if has_stewardship:
            return (
                "Strong trust evidence through stewardship of adopted public "
                "repositories, governance activity, and maintenance responsibility."
            )
        return (
            "Public evidence shows recurring trust from external maintainers, "
            "sustained engagement in external projects, and visible responsibility."
        )
    if score == ScoreBand.MODERATE:
        if has_stewardship:
            return (
                "Moderate trust evidence from project stewardship and ownership, "
                "though external validation scope is limited."
            )
        if has_independent:
            return (
                "Some independent external acceptance exists, supporting "
                "moderate trust, but scope or depth is limited."
            )
        if t.external_acceptance_visible:
            return (
                "Some evidence of external maintainer trust through repeat "
                "merges or sustained engagement, but scope is moderate."
            )
        return (
            "Some evidence of project ownership or community presence, but "
            "independent external acceptance evidence is limited."
        )
    if score == ScoreBand.EMERGING:
        if has_independent and has_limited_stewardship:
            return (
                "Limited trust evidence. Some independent external acceptance "
                "and limited stewardship activity are present, but scope is narrow."
            )
        if has_independent:
            return (
                "Limited trust evidence. Some independent external acceptance "
                "exists, but scope and depth are limited."
            )
        if has_limited_stewardship:
            return (
                "Limited trust evidence. Some stewardship activity is present, "
                "but independent external acceptance is not detected."
            )
        return (
            "Limited trust evidence. Neither independent external acceptance "
            "nor significant stewardship activity was detected."
        )
    return (
        "Insufficient evidence to infer maintainer or community trust. "
        "This reflects evidence limitations, not a judgment on the contributor."
    )


# ------------------------------------------------------------------

def _eval_ecosystem(sig: SignalSet) -> DimensionResult:
    e = sig.ecosystem
    op = sig.owned_projects
    st = sig.stewardship
    ic = sig.impact_calibration

    # v0.4: multi-path -- PR participation + owned repo impact + stewardship + calibration
    importance_score = min(e.weighted_repo_importance / 10, 1.0)
    adoption_score = min(e.contributions_to_high_adoption_repos / 3, 1.0)
    owned_visibility = min(op.owned_public_project_visibility_score / 10, 1.0)
    owned_interest = min(op.owned_public_project_external_interest_score / 2, 1.0)
    release_score = min(e.release_involvement_count / 10, 1.0)
    centrality_score = min(st.owned_repo_centrality_score / 10, 1.0)

    composite = (
        importance_score * 0.20
        + adoption_score * 0.20
        + owned_visibility * 0.20
        + owned_interest * 0.15
        + release_score * 0.10
        + centrality_score * 0.15
    )

    # v0.4: impact calibration boost for extreme centrality/reliance
    if ic.central_repo_impact_override:
        # Boost composite based on tier -- ensures top-tier ecosystems reach top scores
        tier_boost = {
            "extreme": 0.35,
            "high": 0.20,
            "moderate": 0.10,
        }
        centrality_boost = tier_boost.get(ic.ecosystem_centrality_tier, 0.0)
        reliance_boost = tier_boost.get(ic.public_reliance_tier, 0.0)
        override_boost = max(centrality_boost, reliance_boost)
        composite = min(composite + override_boost, 1.0)

    score = _band(composite, [
        (0.10, ScoreBand.EMERGING),
        (0.25, ScoreBand.MODERATE),
        (0.50, ScoreBand.STRONG),
        (0.75, ScoreBand.VERY_STRONG),
    ])

    # v0.4: central repo impact override bypasses adoption cap
    if ic.central_repo_impact_override:
        pass  # No cap applied -- override guarantees recognition
    else:
        has_adoption = (
            e.contributions_to_high_adoption_repos > 0
            or op.owned_public_project_visibility_score >= 5.0
            or st.owned_repo_centrality_score >= 3.0
        )
        if not has_adoption:
            score = _cap_score(score, ScoreBand.MODERATE)

    evidence_points = (
        min(e.weighted_repo_importance / 5, 1.0) * 0.20
        + (1.0 if e.contributions_to_high_adoption_repos > 0 else 0.0) * 0.15
        + min(op.owned_public_project_visibility_score / 5, 1.0) * 0.25
        + min(st.owned_repo_centrality_score / 5, 1.0) * 0.20
        + (0.8 if ic.central_repo_impact_override else 0.0) * 0.20
    )
    confidence = _conf(evidence_points)

    return DimensionResult(
        name="Ecosystem Impact",
        score=score,
        confidence=confidence,
        claim=(
            f"Weighted repo importance: {e.weighted_repo_importance:.1f}. "
            f"High-adoption contributions: {e.contributions_to_high_adoption_repos}. "
            f"Owned project visibility: {op.owned_public_project_visibility_score:.1f}. "
            f"Repo centrality: {st.owned_repo_centrality_score:.1f}."
        ),
        evidence_summary=(
            f"Owned repo external interest: {op.owned_public_project_external_interest_score:.2f}. "
            f"Release involvements: {e.release_involvement_count}. "
            f"Public reliance: {st.owned_repo_public_reliance_score:.2f}."
        ),
        interpretation=_ecosystem_interpretation(score, op, st, ic),
        limitation=(
            "Ecosystem impact is estimated from public adoption proxies (stars, forks), "
            "release activity, and project centrality. Internal tool impact, private "
            "infrastructure contributions, and downstream usage are not measurable."
        ),
    )


def _ecosystem_interpretation(score: ScoreBand, op, st, ic) -> str:
    has_owned = op.owned_public_project_visibility_score >= 3.0
    has_centrality = st.owned_repo_centrality_score >= 2.0
    has_override = ic.central_repo_impact_override

    if score in (ScoreBand.VERY_STRONG, ScoreBand.STRONG):
        if has_override and has_owned:
            return (
                "Central public infrastructure with high ecosystem impact. "
                "Owned repositories show significant adoption, reliance, and centrality."
            )
        if has_owned and has_centrality:
            return (
                "Significant ecosystem presence through central owned repositories "
                "and contributions to well-adopted public projects."
            )
        if has_owned:
            return (
                "Meaningful ecosystem footprint through publicly adopted owned "
                "projects with visible community interest."
            )
        return (
            "Visible work touches well-adopted public repositories and/or "
            "includes owned projects with meaningful public traction."
        )
    if score == ScoreBand.MODERATE:
        return "Some ecosystem presence through contributions to moderately adopted repos."
    if score == ScoreBand.EMERGING:
        return "Limited but observable ecosystem footprint."
    return "Insufficient evidence of ecosystem-level impact."


# ------------------------------------------------------------------

def _eval_specialization(sig: SignalSet) -> DimensionResult:
    s = sig.specialization
    sc = sig.specialization_coherence

    concentration_score = min(s.domain_concentration_score / 0.5, 1.0)

    primary_share = 0.0
    if s.primary_domain and s.domain_distribution:
        primary_share = s.domain_distribution.get(s.primary_domain, 0.0)
    primary_score = min(primary_share / 0.5, 1.0)

    primary_repos = s.repos_per_domain.get(s.primary_domain or "", 0)
    primary_ext_repos = s.external_repos_per_domain.get(s.primary_domain or "", 0)
    primary_months = s.active_months_per_domain.get(s.primary_domain or "", 0)

    depth_score = (
        min(primary_repos / 5, 1.0) * 0.35
        + min(primary_ext_repos / 3, 1.0) * 0.30
        + min(primary_months / 12, 1.0) * 0.35
    )

    # v0.7: domain centrality boost for profiles with strong central-repo ownership
    centrality_boost = max(sc.domain_centrality_signal - 0.5, 0.0) * 0.15

    composite = (
        concentration_score * 0.25
        + primary_score * 0.25
        + depth_score * 0.50
        + centrality_boost
    )

    score = _band(composite, [
        (0.10, ScoreBand.EMERGING),
        (0.30, ScoreBand.MODERATE),
        (0.55, ScoreBand.STRONG),
        (0.80, ScoreBand.VERY_STRONG),
    ])

    # v0.9: sparse-evidence specialization cap (§4.2)
    er = sig.evidence_regime
    sr = sig.specialization_reliability
    if er.sparse_evidence_flag:
        # Exception path: allow stronger if strong multi-signal evidence
        has_exception = (
            primary_repos >= 3
            and primary_ext_repos >= 1
            and primary_months >= 6
            and s.domain_inference_confidence >= 0.5
        )
        if not has_exception:
            # Very sparse: breadth<=1, duration==0, conf<0.4, self-only → Emerging
            very_sparse = (
                s.domain_support_breadth <= 1
                and s.domain_support_duration == 0
                and s.domain_inference_confidence < 0.4
                and sr.domain_evidence_source_mix == "self-only"
            )
            if very_sparse:
                score = _cap_score(score, ScoreBand.EMERGING)
            else:
                score = _cap_score(score, ScoreBand.MODERATE)
            er.specialization_sparse_cap_applied = True
    elif er.evidence_regime == "limited":
        # Limited evidence: cannot exceed Strong
        score = _cap_score(score, ScoreBand.STRONG)

    # v1.0: source-tier specialization cap (Priority C §5.4)
    # metadata_only → cap at Moderate; metadata_plus_activity → cap at Strong
    if er.specialization_source_tier == "metadata_only" and not er.sparse_evidence_flag:
        capped = _cap_score(score, ScoreBand.MODERATE)
        if capped != score:
            score = capped
            er.specialization_sparse_cap_applied = True
    elif er.specialization_source_tier == "metadata_plus_activity":
        capped = _cap_score(score, ScoreBand.STRONG)
        if capped != score:
            score = capped

    # v1.0: minimum evidence thresholds for Strong+ (Priority C §5.2)
    if score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG):
        min_evidence = (
            s.domain_support_breadth >= 2
            and s.domain_support_duration >= 3
            and s.domain_inference_confidence >= 0.3
        )
        if not min_evidence and not s.domain_override_applied:
            score = _cap_score(score, ScoreBand.MODERATE)
            er.specialization_sparse_cap_applied = True

    # Confidence: v0.3 uses domain_inference_confidence from signals
    has_multi_repo = primary_repos >= 3
    has_repeated_activity = primary_months >= 6
    has_external = primary_ext_repos >= 1
    has_override = s.domain_override_applied

    if has_override:
        conf_score = max(s.domain_inference_confidence, 0.7)
    elif has_multi_repo and has_repeated_activity:
        conf_score = 0.8 if has_external else 0.5
    elif has_multi_repo or has_repeated_activity:
        conf_score = 0.4
    elif s.primary_domain:
        conf_score = 0.2
    else:
        conf_score = 0.1

    # v0.5: tighter specialization confidence coherence
    # Bounded by domain confidence, support breadth, duration, and external presence
    domain_conf_cap = _conf(s.domain_inference_confidence)
    raw_conf = _conf(conf_score)

    # High spec confidence requires at least medium domain confidence
    if raw_conf == ConfidenceBand.HIGH and domain_conf_cap == ConfidenceBand.LOW:
        conf_score = min(conf_score, 0.30)
    elif raw_conf == ConfidenceBand.HIGH and domain_conf_cap == ConfidenceBand.MEDIUM:
        conf_score = min(conf_score, 0.55)

    # Short support duration caps confidence
    if primary_months < 3 and conf_score > 0.34:
        conf_score = min(conf_score, 0.30)
    elif primary_months < 6 and conf_score > 0.64:
        conf_score = min(conf_score, 0.50)

    # Self-only evidence without external repos caps at Medium
    sr = sig.specialization_reliability
    if sr.domain_evidence_source_mix == "self-only" and conf_score > 0.55:
        conf_score = min(conf_score, 0.50)

    # Override-dependent classification should flag reduced confidence
    if sr.override_dependency_flag and conf_score > 0.64:
        conf_score = min(conf_score, 0.55)

    # v0.7: apply specialization coherence override penalty
    if sc.specialization_override_penalty > 0:
        conf_score = max(conf_score - sc.specialization_override_penalty, 0.1)

    # Low domain signal quality overall
    if sr.domain_signal_quality_score < 0.25 and conf_score > 0.34:
        conf_score = min(conf_score, 0.30)

    confidence = _conf(conf_score)

    domain_str = s.primary_domain or "undetected"
    secondary_str = ", ".join(s.secondary_domains[:3]) if s.secondary_domains else "none"

    limitation_parts = [
        "Domain inference uses repository metadata (topics, descriptions, "
        "names, languages) with a keyword-based classifier.",
    ]
    if s.domain_override_applied:
        limitation_parts.append(
            "A curated domain override was applied for a known central repository."
        )
    if primary_ext_repos == 0 and primary_repos > 0:
        limitation_parts.append(
            "Domain evidence comes only from self-owned repos -- "
            "external validation of specialization is absent."
        )
    if primary_months < 6:
        limitation_parts.append(
            f"Activity in the primary domain spans only {primary_months} months."
        )
    limitation_parts.append(
        "Nuanced expertise within a domain cannot be reliably assessed "
        "from metadata alone."
    )
    if sc.specialization_confidence_ceiling_reason:
        limitation_parts.append(
            f"Confidence ceiling factors: {sc.specialization_confidence_ceiling_reason}."
        )
    if er.specialization_sparse_cap_applied:
        limitation_parts.append(
            "Specialization score was capped due to sparse evidence. "
            "Additional public activity would strengthen domain assessment."
        )

    return DimensionResult(
        name="Specialization Strength",
        score=score,
        confidence=confidence,
        claim=f"Primary domain: {domain_str}. Secondary: {secondary_str}.",
        evidence_summary=(
            f"Domain concentration (HHI): {s.domain_concentration_score:.3f}. "
            f"Primary domain repos: {primary_repos} ({primary_ext_repos} external). "
            f"Active months in primary domain: {primary_months}. "
            f"Domain confidence: {s.domain_inference_confidence:.2f}. "
            f"Override applied: {'yes' if s.domain_override_applied else 'no'}. "
            f"Top languages: {', '.join(list(s.language_distribution.keys())[:3])}."
        ),
        interpretation=_specialization_interpretation(score, s.primary_domain, primary_ext_repos, er.sparse_evidence_flag, er.specialization_sparse_cap_applied),
        limitation=" ".join(limitation_parts),
    )


def _specialization_interpretation(
    score: ScoreBand,
    domain: str | None,
    ext_repos: int = 0,
    sparse: bool = False,
    sparse_cap_applied: bool = False,
) -> str:
    # v0.9: sparse-evidence directionality wording (§4.3, §11.1)
    if sparse or sparse_cap_applied:
        if domain:
            if score in (ScoreBand.MODERATE, ScoreBand.EMERGING):
                return (
                    f"Some visible directionality toward {domain}, but evidence "
                    f"is currently sparse. This reflects limited domain signal, "
                    f"not strong specialization."
                )
            return (
                f"Limited but visible directionality toward {domain}. "
                f"Evidence is too sparse for a confident specialization assessment."
            )
        return "Evidence is too sparse to assess domain specialization."

    if domain and score in (ScoreBand.VERY_STRONG, ScoreBand.STRONG):
        if ext_repos > 0:
            return (
                f"Public history shows strong concentration in {domain} "
                f"with consistent activity across related repositories, "
                f"including external project contributions."
            )
        return (
            f"Public history shows concentration in {domain}, "
            f"though evidence comes primarily from self-owned repositories."
        )
    if score == ScoreBand.MODERATE:
        return "Some domain focus is visible but activity spans multiple areas or evidence is limited."
    if score == ScoreBand.EMERGING:
        return "Early domain patterns are emerging but not yet concentrated."
    return "No clear domain specialization detected from public metadata."


# ------------------------------------------------------------------

def _eval_consistency(sig: SignalSet, archetypes: list[ArchetypeResult]) -> DimensionResult:
    cs = sig.consistency
    ei = sig.execution_intensity
    ci = sig.consistency_interpretation

    # v0.9: temporal safety — invalid denominators or no activity → NRO (§8.1)
    if not ci.temporal_denominator_valid or ci.temporal_evidence_completeness == "none":
        consist_obs = sig.dimension_coverage.consistency_observability_status
        fallback_reason = ci.consistency_fallback_reason or "insufficient temporal evidence"
        return DimensionResult(
            name="Consistency Over Time",
            score=ScoreBand.LOW,
            confidence=ConfidenceBand.LOW,
            observability_status=ObservabilityStatus.NOT_RELIABLY_OBSERVED.value,
            claim=(
                f"Temporal evidence: {cs.observed_months_active} active months "
                f"in {cs.total_months_in_window}-month window. "
                f"Reason: {fallback_reason}."
            ),
            evidence_summary=(
                f"Active quarters: {cs.active_quarter_count}. "
                f"Repeat-return repos: {cs.repeat_return_repos}."
            ),
            interpretation=(
                "Insufficient temporal evidence in the observation window to "
                "assess consistency. This does not imply inconsistency — "
                "the evidence base is too thin for a meaningful cadence judgment."
            ),
            limitation=(
                "Consistency cannot be assessed when the observation window "
                "contains zero or near-zero activity. This may reflect "
                "evidence-collection limits rather than true inactivity."
            ),
        )

    # Detect if steward archetype
    is_steward = any(
        a.detected and a.archetype == Archetype.MAINTAINER_STEWARD
        for a in archetypes
    )

    active_ratio_score = min(cs.active_month_ratio / 0.5, 1.0)
    burstiness_penalty = 1.0 - cs.burstiness
    recency_score = cs.recency_score
    return_score = min(cs.repeat_return_repos / 5, 1.0)
    quarter_score = min(cs.active_quarter_count / 8, 1.0)
    gap_penalty = max(1.0 - cs.longest_inactive_gap_months / 12, 0.0)

    composite = (
        active_ratio_score * 0.20
        + burstiness_penalty * 0.15
        + recency_score * 0.15
        + return_score * 0.20
        + quarter_score * 0.15
        + gap_penalty * 0.15
    )

    score = _band(composite, [
        (0.15, ScoreBand.EMERGING),
        (0.30, ScoreBand.MODERATE),
        (0.55, ScoreBand.STRONG),
        (0.75, ScoreBand.VERY_STRONG),
    ])

    # v0.3: burst consistency cap
    is_bursty = cs.active_month_ratio < 0.2 and cs.active_quarter_count <= 4
    has_repeat_return = cs.multi_quarter_repo_count >= 2
    if is_bursty and not has_repeat_return:
        score = _cap_score(score, ScoreBand.EMERGING)
    elif is_bursty and cs.active_quarter_count <= 3:
        score = _cap_score(score, ScoreBand.MODERATE)

    evidence_points = (
        min(cs.observed_months_active / 12, 1.0) * 0.4
        + min(cs.repeat_return_repos / 3, 1.0) * 0.3
        + (1.0 if cs.recency_score > 0.1 else 0.0) * 0.15
        + min(cs.active_quarter_count / 6, 1.0) * 0.15
    )

    # v0.5: use archetype-adjusted confidence for steward profiles
    if ci.window_visibility_limited:
        confidence = ConfidenceBand.LOW
    elif is_steward:
        confidence = _conf(ci.archetype_adjusted_consistency_confidence)
    else:
        confidence = _conf(evidence_points)

    # v1.0: partial temporal evidence caps confidence (Priority G)
    if ci.temporal_evidence_completeness == "partial":
        if confidence == ConfidenceBand.HIGH:
            confidence = ConfidenceBand.MEDIUM

    consist_obs = sig.dimension_coverage.consistency_observability_status

    return DimensionResult(
        name="Consistency Over Time",
        score=score,
        confidence=confidence,
        observability_status=consist_obs,
        claim=(
            f"Active in {cs.observed_months_active} of {cs.total_months_in_window} "
            f"months ({cs.active_month_ratio:.0%}). "
            f"Active quarters: {cs.active_quarter_count}. "
            f"Repos with multi-quarter activity: {cs.repeat_return_repos}. "
            f"Longest gap: {cs.longest_inactive_gap_months} months."
        ),
        evidence_summary=(
            f"Burstiness: {cs.burstiness:.2f} (lower is more even). "
            f"Recency score: {cs.recency_score:.2f}. "
            f"Execution intensity: {ei.burst_execution_score:.2f} "
            f"({ei.merged_work_per_active_month:.1f} merged/active month)."
        ),
        interpretation=_consistency_interpretation(score, cs, is_steward, ci),
        limitation=(
            "Consistency is measured from public activity timestamps "
            "within the observation window only. "
            "Periods of private work, sabbaticals, or organizational changes "
            "are invisible and may unfairly lower this score."
            + (" For steward profiles, the observation window may miss "
               "significant earlier public activity."
               if ci.window_visibility_limited else "")
        ),
    )


def _consistency_interpretation(score: ScoreBand, cs, is_steward: bool, ci) -> str:
    if score in (ScoreBand.VERY_STRONG, ScoreBand.STRONG):
        return (
            "Public activity is spread across many months with recent engagement "
            "and repeat returns to projects, suggesting sustained involvement."
        )
    if score == ScoreBand.MODERATE:
        if is_steward and ci.window_visibility_limited:
            return (
                "Limited recent steward-visible activity collected in this window. "
                "The broader profile suggests mature public stewardship beyond "
                "what is visible in the observation period."
            )
        if cs.longest_inactive_gap_months >= 6:
            return (
                "Moderate consistency with notable inactivity gaps. "
                "Some repeat-return behavior is present."
            )
        return "Moderate consistency with some gaps or concentration in activity periods."
    if score == ScoreBand.EMERGING:
        if is_steward and ci.window_visibility_limited:
            return (
                "Limited visible activity in the observation window for a steward "
                "profile. This likely reflects evidence-collection limits rather "
                "than true weak consistency."
            )
        return "Limited temporal spread of activity, possibly recent, intermittent, or bursty."
    if is_steward:
        return (
            "Activity is too sparse in the observation window to assess consistency. "
            "For steward profiles, this may reflect collection limits."
        )
    return "Activity is too sparse to assess consistency."


# ------------------------------------------------------------------

def _eval_builder_sophistication(sig: SignalSet, archetypes: list[ArchetypeResult]) -> DimensionResult:
    """v0.6/v0.7/v0.9: Builder Sophistication — archetype-safe, evidence-mode-aware, Route C."""
    bs = sig.builder_sophistication
    op = sig.owned_projects
    dc = sig.dimension_coverage
    fb = sig.foundational_builder

    # v0.7: Check if builder sophistication is reliably observable
    is_steward = any(
        a.detected and a.archetype == Archetype.MAINTAINER_STEWARD
        for a in archetypes
    )
    not_reliably_observable = (
        dc.builder_observability_status == "not_reliably_observed"
    )

    # v0.9: Route C — foundational builder can bypass NRO for steward profiles
    if not_reliably_observable and is_steward:
        if bs.foundational_builder_route_active and bs.foundational_builder_score >= 0.4:
            # Route C: score via foundational builder signal instead of NRO
            composite = bs.foundational_builder_score
            score = _band(composite, [
                (0.10, ScoreBand.EMERGING),
                (0.25, ScoreBand.MODERATE),
                (0.45, ScoreBand.STRONG),
                (0.65, ScoreBand.VERY_STRONG),
            ])
            # Confidence from foundational signals, not PR evidence
            fib_conf_score = (
                fb.foundational_system_ownership_signal * 0.35
                + fb.technical_foundation_signal * 0.25
                + fb.systems_scope_signal * 0.25
                + fb.central_repo_substance_score * 0.15
            )
            confidence = _conf(fib_conf_score)
            return DimensionResult(
                name="Builder Sophistication",
                score=score,
                confidence=confidence,
                claim=(
                    f"Foundational builder route (C) active. "
                    f"Foundational signal: {fb.foundational_infrastructure_builder_signal:.2f}. "
                    f"Central repo substance: {fb.central_repo_substance_score:.2f}. "
                    f"Systems scope: {fb.systems_scope_signal:.2f}."
                ),
                evidence_summary=(
                    f"Foundational system ownership: {fb.foundational_system_ownership_signal:.2f}. "
                    f"Technical foundation: {fb.technical_foundation_signal:.2f}. "
                    f"Long-lived repo substance: {fb.long_lived_repo_substance_score:.2f}. "
                    f"Builder signal path: {bs.builder_signal_path}."
                ),
                interpretation=_builder_sophistication_interpretation(score, bs, route_c=True),
                limitation=(
                    "Builder sophistication scored via foundational infrastructure route (Route C). "
                    "PR-delivery evidence is sparse, but ownership of central, technically "
                    "substantial public infrastructure is strong. Route C does not capture "
                    "implementation depth directly — it infers builder substance from "
                    "infrastructure ownership and public reliance."
                ),
                observability_status="partially_observed",
            )

        # v0.7 original: NRO return for steward profiles without Route C
        return DimensionResult(
            name="Builder Sophistication",
            score=ScoreBand.LOW,  # stored as LOW but display overridden
            confidence=ConfidenceBand.LOW,
            claim=(
                f"Large PRs (>=200 additions): {bs.large_pr_count}. "
                f"Very large PRs (>=500 additions): {bs.very_large_pr_count}. "
                f"Multi-subsystem PRs (>=5 files): {bs.multi_subsystem_pr_count}. "
                f"Observability mode: {bs.builder_observability_mode}."
            ),
            evidence_summary=(
                f"Builder evidence coverage: {bs.builder_evidence_coverage:.2f}. "
                f"Signal path: {bs.builder_signal_path}. "
                f"Repo substance: {bs.repo_substance_score:.2f}. "
                f"Owned repo complexity: {bs.owned_repo_complexity_score:.2f}."
            ),
            interpretation=(
                "Builder Sophistication is not reliably observable from current "
                "PR-based and repository-surface evidence. This profile's public "
                "value is expressed primarily through stewardship, governance, "
                "and ecosystem centrality. A low builder score here does not "
                "imply the contributor lacks builder depth."
            ),
            limitation=(
                "Current evidence collection does not expose enough builder-style "
                "implementation signals for this archetype. Stewardship-dominant "
                "profiles often contribute through non-PR workflows not captured "
                "in the current collector."
            ),
            observability_status=ObservabilityStatus.NOT_RELIABLY_OBSERVED.value,
        )

    # v0.7: For partially-observed profiles, use combined Route A + Route B
    if dc.builder_observability_status == "partially_observed":
        # Route B can contribute via repo substance
        route_b_boost = bs.repo_substance_score * 0.3 + bs.owned_repo_breadth_score * 0.2
        composite = bs.builder_sophistication_signal * 0.7 + route_b_boost * 0.3
    else:
        composite = bs.builder_sophistication_signal

    score = _band(composite, [
        (0.10, ScoreBand.EMERGING),
        (0.25, ScoreBand.MODERATE),
        (0.45, ScoreBand.STRONG),
        (0.65, ScoreBand.VERY_STRONG),
    ])

    # Confidence: depends on evidence strength, delivery, repos involved
    evidence_points = (
        min(bs.large_pr_count / 5, 1.0) * 0.20
        + min(bs.large_pr_repo_count / 3, 1.0) * 0.20
        + min(bs.repeated_feature_delivery_count / 2, 1.0) * 0.20
        + min(bs.multi_subsystem_pr_count / 5, 1.0) * 0.15
        + min(bs.cross_layer_change_count / 5, 1.0) * 0.10
        + bs.product_scope_signal * 0.15
    )
    confidence = _conf(evidence_points)

    # Gate: no large PRs at all -> cap at Emerging
    if bs.large_pr_count == 0:
        score = _cap_score(score, ScoreBand.EMERGING)

    # Gate: no repeated delivery across repos -> cap at Moderate
    if bs.repeated_feature_delivery_count == 0 and bs.repeated_major_delivery_count == 0:
        score = _cap_score(score, ScoreBand.MODERATE)

    # Determine observability status for well/partially observed
    obs_status = dc.builder_observability_status

    limitation_parts = [
        "Builder sophistication is inferred from PR size, file breadth, "
        "repeated delivery patterns, and repo complexity.",
        "Large PRs alone do not prove meaningful system building -- "
        "noisy or auto-generated changes may inflate this signal.",
        "Private codebases and non-PR workflows are not visible.",
    ]
    if bs.owned_repo_complexity_score < 0.1 and score in (ScoreBand.MODERATE, ScoreBand.STRONG, ScoreBand.VERY_STRONG):
        limitation_parts.append(
            "Builder sophistication evidence comes primarily from non-owned repos."
        )
    if obs_status == "partially_observed":
        limitation_parts.append(
            "Builder evidence is only partially observable in the current evidence mode."
        )

    return DimensionResult(
        name="Builder Sophistication",
        score=score,
        confidence=confidence,
        claim=(
            f"Large PRs (>=200 additions): {bs.large_pr_count}. "
            f"Very large PRs (>=500 additions): {bs.very_large_pr_count}. "
            f"Multi-subsystem PRs (>=5 files): {bs.multi_subsystem_pr_count}. "
            f"Repos with large PRs: {bs.large_pr_repo_count}."
        ),
        evidence_summary=(
            f"Median additions/PR: {bs.median_additions_per_pr:.0f}. "
            f"Max additions: {bs.max_additions_per_pr}. "
            f"Median changed files/PR: {bs.median_changed_files_per_pr:.1f}. "
            f"Repeated feature delivery: {bs.repeated_feature_delivery_count} repos. "
            f"Repeated major delivery: {bs.repeated_major_delivery_count} repos. "
            f"Product scope signal: {bs.product_scope_signal:.2f}. "
            f"Owned repo complexity: {bs.owned_repo_complexity_score:.2f}. "
            f"Signal path: {bs.builder_signal_path}."
        ),
        interpretation=_builder_sophistication_interpretation(score, bs, route_c=False),
        limitation=" ".join(limitation_parts),
        observability_status=obs_status,
    )


def _builder_sophistication_interpretation(score: ScoreBand, bs, route_c: bool = False) -> str:
    # v0.9: foundational builder wording (§11.2)
    if route_c:
        if score in (ScoreBand.VERY_STRONG, ScoreBand.STRONG):
            return (
                "Strong evidence of foundational systems building through ownership "
                "and stewardship of technically substantial public infrastructure."
            )
        if score == ScoreBand.MODERATE:
            return (
                "Meaningful foundational builder signal through ownership of "
                "central public infrastructure, though PR-delivery evidence is limited."
            )
        return (
            "Some foundational infrastructure signals present, but overall builder "
            "substance is limited from available evidence."
        )

    if score == ScoreBand.VERY_STRONG:
        return (
            "Public evidence shows repeated sophisticated system/product building "
            "across meaningful scope with substantial implementation depth."
        )
    if score == ScoreBand.STRONG:
        return (
            "Public evidence shows clear substantial product/system construction "
            "with repeated feature delivery and multi-subsystem changes."
        )
    if score == ScoreBand.MODERATE:
        return (
            "Visible repeated self-directed building with some non-trivial "
            "implementation depth, though scope or delivery repetition is moderate."
        )
    if score == ScoreBand.EMERGING:
        return (
            "Some non-trivial build signals are present, but implementation "
            "depth, scope, or repeated delivery is limited."
        )
    return "Little visible implementation depth from public evidence."


# =====================================================================
# Internal contradiction checks (v0.4)
# =====================================================================

def _check_contradictions(
    dimensions: list[DimensionResult],
    sig: SignalSet,
) -> list[DimensionResult]:
    """Post-process dimensions to fix internally contradictory outputs."""
    dim_map = {d.name: d for d in dimensions}

    sc = sig.steward_contribution
    cc = sig.contribution_calibration
    ic = sig.impact_calibration

    # 1. Weak contribution despite overwhelming owned-project/stewardship evidence
    contrib = dim_map.get("Contribution Quality")
    if contrib and contrib.score in (ScoreBand.LOW, ScoreBand.EMERGING):
        if sc.governance_weighted_contribution_signal >= 0.5:
            contrib.score = ScoreBand.MODERATE
            contrib.interpretation = (
                "Adjusted: strong stewardship or project ownership evidence "
                "supports at least moderate contribution quality despite "
                "sparse PR authorship."
            )

    # 2. Moderate impact despite extreme centrality
    ecosystem = dim_map.get("Ecosystem Impact")
    if ecosystem and ecosystem.score == ScoreBand.MODERATE:
        if ic.ecosystem_centrality_tier == "extreme" or ic.public_reliance_tier == "extreme":
            ecosystem.score = ScoreBand.STRONG
            ecosystem.interpretation = (
                "Adjusted: extreme repo centrality or public reliance supports "
                "at least strong ecosystem impact."
            )

    # 3. High specialization confidence with low domain confidence
    spec = dim_map.get("Specialization Strength")
    if spec and spec.confidence == ConfidenceBand.HIGH:
        if sig.specialization.domain_inference_confidence < 0.35:
            spec.confidence = ConfidenceBand.MEDIUM

    # v0.5: 4. Moderate contribution with zero independent acceptance, zero adoption,
    # and self-governed-only execution — should not remain Moderate
    # v0.6: exception for profiles with strong builder sophistication
    bs = sig.builder_sophistication
    if contrib and contrib.score == ScoreBand.MODERATE:
        if cc.independent_validation_absence and cc.self_governed_execution_ratio >= 0.9:
            if bs.builder_sophistication_signal < 0.35:
                contrib.score = ScoreBand.EMERGING
                contrib.interpretation = (
                    "Public evidence shows execution activity in self-governed "
                    "contexts only. No independent acceptance, owned project "
                    "adoption, or stewardship evidence supports higher scoring."
                )

    # v0.5: 5. Promising specialization with weak domain confidence
    if spec and spec.score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG):
        if sig.specialization.domain_inference_confidence < 0.25:
            spec.score = ScoreBand.MODERATE
            spec.interpretation = (
                "Adjusted: specialization score reduced due to low domain "
                "inference confidence. The domain assignment may be unreliable."
            )

    # v0.6: 6. Builder sophistication must NOT raise trust
    trust = dim_map.get("Maintainer / Community Trust")
    builder_dim = dim_map.get("Builder Sophistication")
    if trust and builder_dim:
        if (builder_dim.score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG)
                and trust.score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG)):
            c = sig.contribution
            # If trust is high purely because builder sophistication inflated signals,
            # and there's no real independent acceptance or stewardship, cap trust
            has_real_trust = (
                c.independent_acceptance_count >= 3
                or sig.stewardship.stewardship_signal >= 0.2
                or sig.owned_projects.owned_public_project_visibility_score >= 5.0
            )
            if not has_real_trust:
                trust.score = ScoreBand.MODERATE
                trust.interpretation = (
                    "Adjusted: trust score reduced. High builder sophistication "
                    "does not substitute for independent acceptance or stewardship."
                )

    # v0.6: 7. Builder sophistication must NOT raise ecosystem impact
    if ecosystem and builder_dim:
        if (builder_dim.score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG)
                and ecosystem.score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG)):
            has_real_impact = (
                sig.ecosystem.contributions_to_high_adoption_repos > 0
                or sig.owned_projects.owned_public_project_visibility_score >= 5.0
                or sig.stewardship.owned_repo_centrality_score >= 3.0
                or ic.central_repo_impact_override
            )
            if not has_real_impact:
                ecosystem.score = ScoreBand.MODERATE
                ecosystem.interpretation = (
                    "Adjusted: ecosystem impact reduced. Builder sophistication "
                    "does not imply public adoption or centrality."
                )

    return dimensions


# =====================================================================
# Stage-aware interpretation (v0.4)
# =====================================================================

def _compute_stage_interpretation(
    sig: SignalSet,
    archetypes: list[ArchetypeResult],
    dimensions: list[DimensionResult],
) -> StageInterpretation:
    """Produce the stage-aware interpretation from maturity, promise, and archetype signals.

    v1.0: role-shaped readiness buckets (§5.3) — readiness language now
    references concrete role categories (builder-heavy, external contributor,
    infrastructure ownership, stewardship) and incorporates foundational
    builder archetype awareness.
    """
    mat = sig.maturity
    prom = sig.promise
    mp = sig.mature_profile
    bs = sig.builder_sophistication
    sc = sig.specialization_coherence

    # Maturity band
    try:
        maturity_band = MaturityBand(mat.maturity_band)
    except ValueError:
        maturity_band = MaturityBand.EMERGING

    # Contributor type based on detected archetypes
    detected = [a for a in archetypes if a.detected]
    if detected:
        best = max(detected, key=lambda a: a.confidence)
        archetype_label = best.archetype.value.lower()
    else:
        archetype_label = "contributor"

    maturity_prefix = {
        MaturityBand.EMERGING: "emerging",
        MaturityBand.DEVELOPING: "developing",
        MaturityBand.ESTABLISHED: "established",
        MaturityBand.STEWARD: "steward-level",
    }
    prefix = maturity_prefix.get(maturity_band, "emerging")
    contributor_type = f"{prefix} {archetype_label}"

    # --- Promise summary (v0.8: sparse, bounded, descriptive) ---
    if mp.promise_suppression_flag:
        if mp.mature_profile_mode == "steward":
            promise_summary = (
                "Established steward profile. Assessment reflects demonstrated "
                "infrastructure leadership and sustained public impact, "
                "not early-stage promise."
            )
        else:
            promise_summary = (
                "Established contributor profile with demonstrated impact. "
                "Assessment is based on evidence of sustained contribution, "
                "not early-stage potential."
            )
    elif maturity_band in (MaturityBand.EMERGING, MaturityBand.DEVELOPING):
        # v0.8: only surface promise facets that are meaningful and coherent
        promise_parts = []
        if prom.promising_execution_score >= 0.5:
            promise_parts.append("strong early execution signal")
        if prom.promising_external_acceptance_score >= 0.5:
            promise_parts.append("credible external acceptance for evidence depth")
        # v0.8: use descriptive text instead of raw numbers for specialization
        if prom.promising_specialization_score >= 0.5:
            if sc.domain_directionality_label:
                promise_parts.append(sc.domain_directionality_label)
            else:
                promise_parts.append("developing domain focus")
        elif sc.domain_directionality_signal >= 0.4:
            promise_parts.append(sc.domain_directionality_label or "emerging domain direction")
        # v0.8: builder promise reflects actual builder signal strength
        if prom.promising_builder_sophistication_score >= 0.5:
            promise_parts.append("clear self-directed product/system building evidence")
        elif prom.promising_builder_sophistication_score >= 0.3:
            promise_parts.append("promising builder sophistication")
        if prom.early_signal_strength >= 0.4 and not promise_parts:
            promise_parts.append("notable signal quality relative to evidence volume")

        if promise_parts:
            promise_summary = (
                f"Promising {prefix} profile with: {'; '.join(promise_parts)}."
            )
        else:
            promise_summary = (
                "Early-stage profile. Evidence is sparse but "
                "no negative indicators detected."
            )
    elif maturity_band == MaturityBand.STEWARD:
        promise_summary = (
            "Established steward profile. Promise assessment is not "
            "applicable — demonstrated impact is the primary lens."
        )
    else:
        # Established but not suppressed — include builder/strength info if present
        strength_parts = []
        if bs.builder_sophistication_signal >= 0.3:
            strength_parts.append("meaningful visible builder sophistication")
        if strength_parts:
            promise_summary = (
                f"Established contributor profile with: {'; '.join(strength_parts)}. "
                "Assessment is based on demonstrated evidence."
            )
        else:
            promise_summary = (
                "Established contributor profile. Assessment is based on "
                "demonstrated evidence rather than potential."
            )

    # --- Readiness summary (v1.0: role-shaped readiness buckets §5.3) ---
    dim_scores = {d.name: d.score for d in dimensions}
    contrib_score = dim_scores.get("Contribution Quality", ScoreBand.LOW)
    trust_score = dim_scores.get("Maintainer / Community Trust", ScoreBand.LOW)
    builder_score = dim_scores.get("Builder Sophistication", ScoreBand.LOW)

    # Check for foundational builder archetype
    is_foundational = any(
        a.detected and a.archetype == Archetype.FOUNDATIONAL_INFRASTRUCTURE_BUILDER
        for a in archetypes
    )

    if maturity_band == MaturityBand.STEWARD:
        if is_foundational:
            readiness_summary = (
                "Evidence supports infrastructure ownership roles: foundational "
                "systems stewardship, governance, and high-trust technical leadership."
            )
        else:
            readiness_summary = (
                "Evidence supports stewardship-level roles: infrastructure ownership, "
                "governance, mentorship, and high-trust technical leadership."
            )
    elif maturity_band == MaturityBand.ESTABLISHED:
        if _SCORE_ORDER.index(trust_score) >= _SCORE_ORDER.index(ScoreBand.STRONG):
            readiness_summary = (
                "Evidence supports established contributor roles with demonstrated "
                "external trust and meaningful project impact."
            )
        elif _SCORE_ORDER.index(builder_score) >= _SCORE_ORDER.index(ScoreBand.STRONG):
            readiness_summary = (
                "Evidence supports builder-heavy contributor roles: "
                "self-directed product/system building, early project ownership, "
                "and technical leadership within owned projects."
            )
        else:
            readiness_summary = (
                "Evidence supports established contributor roles with "
                "meaningful public output, though external trust scope is moderate."
            )
    elif maturity_band == MaturityBand.DEVELOPING:
        if _SCORE_ORDER.index(builder_score) >= _SCORE_ORDER.index(ScoreBand.MODERATE):
            readiness_summary = (
                "Growing evidence base with visible building activity suggests "
                "readiness for builder-heavy contributor roles or early project ownership."
            )
        elif _SCORE_ORDER.index(contrib_score) >= _SCORE_ORDER.index(ScoreBand.MODERATE):
            readiness_summary = (
                "Growing evidence base suggests readiness for external "
                "contributor roles or early project ownership."
            )
        else:
            readiness_summary = (
                "Developing evidence base. Continued public contribution "
                "will strengthen the profile further."
            )
    else:
        if prom.early_signal_strength >= 0.4:
            readiness_summary = (
                "Early but promising signals. Suitable for early-stage "
                "contributor or mentored project opportunities."
            )
        else:
            readiness_summary = (
                "Limited public evidence. Profile would benefit from "
                "additional visible public contributions."
            )

    return StageInterpretation(
        maturity_band=maturity_band,
        maturity_basis=mat.maturity_basis,
        promise_summary=promise_summary,
        contributor_type=contributor_type,
        readiness_summary=readiness_summary,
    )


# =====================================================================
# v1.0: Finalize dimensions into canonical FinalDimensionResult
# =====================================================================

def _finalize_dimensions(
    dimensions: list[DimensionResult],
    sig: SignalSet,
) -> list[FinalDimensionResult]:
    """Convert raw DimensionResult objects into canonical FinalDimensionResult.

    All output surfaces must render from these objects exclusively.
    A dimension cannot simultaneously be scored and not reliably observable.
    """
    er = sig.evidence_regime
    bs = sig.builder_sophistication
    ci = sig.consistency_interpretation
    finals: list[FinalDimensionResult] = []

    for dim in dimensions:
        f = FinalDimensionResult(name=dim.name)
        f.claim = dim.claim
        f.evidence_summary = dim.evidence_summary
        f.interpretation = dim.interpretation
        f.limitation = dim.limitation

        is_nro = dim.observability_status == ObservabilityStatus.NOT_RELIABLY_OBSERVED.value

        if is_nro:
            f.status = "not_reliably_observable"
            f.score_label = ""
            f.confidence_label = ""
            f.observability_label = "Not Reliably Observable"
            f.display_label = "Not Reliably Observable"
            f.observability_constraint_applied = True
        else:
            f.status = "scored"
            f.score_label = dim.score.value if isinstance(dim.score, ScoreBand) else str(dim.score)
            f.confidence_label = dim.confidence.value if isinstance(dim.confidence, ConfidenceBand) else str(dim.confidence)
            obs_val = dim.observability_status
            if obs_val == "partially_observed":
                f.observability_label = "Partially Observed"
                f.observability_constraint_applied = True
            else:
                f.observability_label = "Well Observed"
            f.display_label = f"{f.score_label} / {f.confidence_label}"

        # Determine explanation mode and supporting route
        if dim.name == "Specialization Strength":
            if er.sparse_evidence_flag or er.specialization_sparse_cap_applied:
                f.explanation_mode = "sparse_evidence"
                f.score_cap_applied = er.specialization_sparse_cap_applied
                f.cap_reason = "sparse evidence regime"
            if er.evidence_regime == "limited":
                f.score_cap_applied = True
                f.cap_reason = "limited evidence regime"
            f.dominant_scoring_route = "metadata + activity"

        elif dim.name == "Builder Sophistication":
            if bs.foundational_builder_route_active and not is_nro:
                f.explanation_mode = "foundational_route"
                f.supporting_route = "Route C (foundational infrastructure)"
                f.dominant_scoring_route = "foundational infrastructure ownership"
            elif dim.observability_status == "partially_observed":
                f.supporting_route = "Route A (PR delivery) + Route B (repo substance)"
                f.dominant_scoring_route = "PR delivery + repo substance"
            elif is_nro:
                f.explanation_mode = "nro_steward"
            else:
                f.supporting_route = "Route A (PR delivery)"
                f.dominant_scoring_route = "PR delivery"

        elif dim.name == "Consistency Over Time":
            if not ci.temporal_denominator_valid or ci.temporal_evidence_completeness == "none":
                f.explanation_mode = "temporal_fallback"

        elif dim.name == "Contribution Quality":
            # Identify dominant contribution route
            c = sig.contribution
            sc = sig.steward_contribution
            if sc.steward_contribution_signal >= 0.3:
                f.dominant_scoring_route = "stewardship"
            elif c.independent_acceptance_count >= 3:
                f.dominant_scoring_route = "independent external acceptance"
            elif sig.owned_projects.owned_public_project_visibility_score >= 3.0:
                f.dominant_scoring_route = "owned public projects"
            elif bs.builder_sophistication_signal >= 0.35:
                f.dominant_scoring_route = "builder sophistication"
            else:
                f.dominant_scoring_route = "mixed"

        finals.append(f)

    return finals


# =====================================================================
# Main evaluation entry point
# =====================================================================

def evaluate(evidence: Evidence, signals: SignalSet) -> EvaluationResult:
    """Produce the full evaluation result (v1.0).

    Pipeline: archetypes → 7 dimensions → contradiction checks →
    integrity checks → finalization → stage interpretation → result.
    """

    # Detect archetypes before dimension scoring
    archetypes = _detect_archetypes(signals)

    dimensions = [
        _eval_contribution(signals),
        _eval_collaboration(signals, archetypes),
        _eval_trust(signals),
        _eval_ecosystem(signals),
        _eval_specialization(signals),
        _eval_consistency(signals, archetypes),
        _eval_builder_sophistication(signals, archetypes),
    ]

    # v0.4: internal contradiction checks
    dimensions = _check_contradictions(dimensions, signals)

    # v0.8: report integrity checks (runs after dimensions, before report)
    from .signals import _compute_report_integrity
    _compute_report_integrity(signals, dimensions)

    # v1.0: finalize dimensions into canonical FinalDimensionResult
    final_dimensions = _finalize_dimensions(dimensions, signals)

    # v0.4: stage-aware interpretation
    stage_interpretation = _compute_stage_interpretation(
        signals, archetypes, dimensions,
    )

    sp = signals.specialization
    domain_inference = DomainInference(
        primary_domain=sp.primary_domain,
        secondary_domains=sp.secondary_domains,
        evidence=(
            f"Based on repository topics, descriptions, name patterns, and "
            f"language distribution across {len(evidence.repositories)} "
            f"evaluated repositories."
        ),
        confidence=sp.domain_inference_confidence,
        override_applied=sp.domain_override_applied,
    )

    return EvaluationResult(
        subject=evidence.profile.username,
        observation_window_start=evidence.observation_window_start,
        observation_window_end=evidence.observation_window_end,
        repos_evaluated=len(evidence.repositories),
        dimensions=dimensions,
        domain_inference=domain_inference,
        archetypes=archetypes,
        stage_interpretation=stage_interpretation,
        final_dimensions=final_dimensions,
    )
