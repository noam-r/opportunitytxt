"""Internal data models for the evaluation pipeline.

All models are plain dataclasses that serialize to/from dicts for JSON output.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ScoreBand(str, Enum):
    LOW = "Low"
    EMERGING = "Emerging"
    MODERATE = "Moderate"
    STRONG = "Strong"
    VERY_STRONG = "Very Strong"


class ConfidenceBand(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class PRState(str, Enum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"  # closed without merge


class Archetype(str, Enum):
    EXTERNAL_CONTRIBUTOR = "External Contributor"
    INDEPENDENT_BUILDER = "Independent Builder"
    OWNED_PROJECT_MAINTAINER = "Owned Public Project Maintainer"
    MAINTAINER_STEWARD = "Maintainer / Steward / Governor"
    BURST_EXECUTION = "Burst Execution Profile"
    SUSTAINED_CONTRIBUTOR = "Sustained Public Contributor"
    COMPLEX_PRODUCT_BUILDER = "Complex Product Builder"
    FOUNDATIONAL_INFRASTRUCTURE_BUILDER = "Foundational Infrastructure Builder"  # v0.9


class MaturityBand(str, Enum):
    EMERGING = "Emerging Public Contributor"
    DEVELOPING = "Developing Public Contributor"
    ESTABLISHED = "Established Public Contributor"
    STEWARD = "Public Maintainer / Steward"


class ReviewOutcome(str, Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    COMMENTED = "commented"
    DISMISSED = "dismissed"


class ObservabilityStatus(str, Enum):
    """v0.7: whether a dimension is reliably observable in the current evidence mode."""
    WELL_OBSERVED = "well_observed"
    PARTIALLY_OBSERVED = "partially_observed"
    NOT_RELIABLY_OBSERVED = "not_reliably_observed"


# ---------------------------------------------------------------------------
# Profile-level
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    username: str
    url: str
    created_at: str  # ISO-8601
    public_repo_count: int
    followers: int
    following: int
    bio: str | None = None
    name: str | None = None
    company: str | None = None
    location: str | None = None


# ---------------------------------------------------------------------------
# Repository-level
# ---------------------------------------------------------------------------

@dataclass
class Repository:
    name: str
    owner: str
    url: str
    description: str | None
    primary_language: str | None
    topics: list[str]
    stars: int
    forks: int
    watchers: int
    open_issues: int
    created_at: str
    updated_at: str
    is_archived: bool
    is_fork: bool
    is_template: bool
    default_branch: str
    license_name: str | None
    is_owned_by_subject: bool
    # Derived during collection
    contributor_count: int | None = None
    disk_usage_kb: int | None = None


# ---------------------------------------------------------------------------
# Contribution-level events
# ---------------------------------------------------------------------------

@dataclass
class PullRequest:
    repo_owner: str
    repo_name: str
    number: int
    title: str
    state: PRState
    created_at: str
    merged_at: str | None
    closed_at: str | None
    additions: int
    deletions: int
    changed_files: int
    review_count: int
    comment_count: int
    is_repo_owned_by_subject: bool = False
    merged_by: str | None = None  # login of the user who merged
    is_self_merged: bool | None = None  # True if merged by the PR author


@dataclass
class Review:
    repo_owner: str
    repo_name: str
    pr_number: int
    state: ReviewOutcome
    submitted_at: str
    body_length: int  # length of review body, not the body text itself


@dataclass
class IssueParticipation:
    repo_owner: str
    repo_name: str
    issue_number: int
    title: str
    is_author: bool
    comment_count: int  # comments by the subject
    created_at: str


@dataclass
class ReleaseInvolvement:
    repo_owner: str
    repo_name: str
    tag_name: str
    name: str | None
    created_at: str
    is_author: bool


# ---------------------------------------------------------------------------
# Counterparty (lightweight – no profile fetching in v1)
# ---------------------------------------------------------------------------

@dataclass
class Counterparty:
    username: str
    interaction_count: int
    repos: list[str]  # repo full names where interaction occurred
    interaction_types: list[str]  # e.g. ["review", "merge", "comment"]


# ---------------------------------------------------------------------------
# Aggregate evidence container
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """Complete normalized evidence for one subject."""

    profile: Profile
    observation_window_start: str  # ISO-8601
    observation_window_end: str    # ISO-8601
    repositories: list[Repository] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    issue_participations: list[IssueParticipation] = field(default_factory=list)
    release_involvements: list[ReleaseInvolvement] = field(default_factory=list)
    counterparties: list[Counterparty] = field(default_factory=list)
    collection_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Signal set
# ---------------------------------------------------------------------------

@dataclass
class ContributionSignals:
    total_prs_opened: int = 0
    merged_pr_count: int = 0
    closed_unmerged_pr_count: int = 0
    merge_ratio: float = 0.0
    repeat_merged_contribution_count: int = 0  # repos with >1 merged PR
    repos_with_merged_contributions: int = 0
    merged_contributions_per_active_month: float = 0.0
    accepted_contribution_concentration: dict[str, int] = field(default_factory=dict)  # repo -> merged count
    authored_repo_activity_signal: float = 0.0  # activity level in own repos
    # v0.2: ownership-aware splits
    merged_pr_count_self_owned: int = 0
    merged_pr_count_external: int = 0
    repos_with_merged_contributions_self_owned: int = 0
    repos_with_merged_contributions_external: int = 0
    self_merged_pr_count: int = 0
    externally_merged_pr_count: int = 0
    external_repo_externally_merged_pr_count: int = 0
    self_repo_self_merged_pr_count: int = 0
    repeat_external_accepted_contribution_count: int = 0  # external repos with >1 merged PR
    # v0.3: governance independence
    independent_acceptance_count: int = 0  # external repo + not self-merged
    independent_acceptance_repo_count: int = 0
    independent_acceptance_ratio: float = 0.0
    external_repo_self_merged_pr_count: int = 0
    external_repo_independently_merged_pr_count: int = 0


@dataclass
class OwnedProjectSignals:
    owned_public_project_count: int = 0
    owned_public_project_visibility_score: float = 0.0
    owned_public_project_release_count: int = 0
    owned_public_project_external_interest_score: float = 0.0
    owned_public_project_age_score: float = 0.0
    owned_public_project_maintenance_score: float = 0.0


@dataclass
class StewardshipSignals:
    issue_response_activity_count: int = 0
    issue_participation_count: int = 0
    repo_governance_activity_score: float = 0.0
    release_stewardship_count: int = 0
    owned_repo_centrality_score: float = 0.0
    owned_repo_public_reliance_score: float = 0.0
    maintainer_visibility_score: float = 0.0
    stewardship_signal: float = 0.0


@dataclass
class ExecutionIntensitySignals:
    merged_work_per_active_month: float = 0.0
    change_volume_per_active_month: float = 0.0
    active_repo_count_during_peak_window: int = 0
    burst_execution_score: float = 0.0


@dataclass
class MaturitySignals:
    """v0.4: public-evidence maturity classification signals."""
    history_depth_score: float = 0.0  # account age + window coverage
    evidence_depth_score: float = 0.0  # volume of evidence
    evidence_diversity_score: float = 0.0  # variety of evidence types
    stage_readiness_score: float = 0.0  # composite maturity indicator
    maturity_band: str = ""  # will be set to MaturityBand value
    maturity_basis: str = ""  # why this band was assigned


@dataclass
class PromiseSignals:
    """v0.4: promise/potential signals for stage-aware interpretation.

    v0.8: promise fields are now bounded by dimension scores and confidence.
    They are derived signals, not independent scoreboard entries.
    """
    early_signal_strength: float = 0.0
    promising_execution_score: float = 0.0
    promising_specialization_score: float = 0.0
    promising_external_acceptance_score: float = 0.0
    # v0.6: builder sophistication promise
    promising_builder_sophistication_score: float = 0.0
    # v0.8: promise redesign metadata
    promise_render_mode: str = "developing"  # developing / mature / suppressed
    promise_suppressed_reason: str = ""  # why promise was suppressed
    specialization_promise_ceiling_reason: str = ""  # why spec promise was capped


@dataclass
class StewardContributionSignals:
    """v0.4: steward contribution path signals."""
    steward_contribution_signal: float = 0.0
    owned_public_build_signal: float = 0.0
    governance_weighted_contribution_signal: float = 0.0


@dataclass
class ImpactCalibrationSignals:
    """v0.4: ecosystem impact calibration signals."""
    central_repo_impact_override: bool = False
    ecosystem_centrality_tier: str = "none"  # none/moderate/high/extreme
    public_reliance_tier: str = "none"  # none/moderate/high/extreme


@dataclass
class ContributionCalibrationSignals:
    """v0.5: contribution calibration signals."""
    self_governed_execution_ratio: float = 0.0  # fraction of merged work that is self-governed
    independent_validation_absence: bool = False  # True when no independent acceptance + no adoption + no stewardship
    contribution_ceiling_reason: str = ""  # why a cap was applied, if any


@dataclass
class ArchetypeSoftClassification:
    """v0.5: secondary archetype hints."""
    secondary_archetype_candidates: list[str] = field(default_factory=list)
    secondary_archetype_strengths: dict[str, float] = field(default_factory=dict)  # archetype name -> 0-1 strength


@dataclass
class SpecializationReliabilitySignals:
    """v0.5: specialization reliability signals."""
    domain_evidence_source_mix: str = ""  # e.g. "self-only", "mixed", "external-validated"
    domain_signal_quality_score: float = 0.0  # overall quality of domain evidence
    override_dependency_flag: bool = False  # True if domain assignment heavily relies on override


@dataclass
class ConsistencyInterpretationSignals:
    """v0.5: consistency interpretation signals."""
    window_visibility_limited: bool = False  # True when window likely misses real activity
    archetype_adjusted_consistency_confidence: float = 0.0  # adjusted confidence for steward profiles
    # v0.9: temporal edge-case safety
    temporal_evidence_completeness: str = "sufficient"  # none / partial / sufficient
    temporal_denominator_valid: bool = True  # False when 0-of-0 months
    consistency_fallback_reason: str = ""  # why consistency was marked not observable


@dataclass
class DimensionCoverageSignals:
    """v0.7: dimension observability/coverage status for key dimensions."""
    collaboration_observability_status: str = "well_observed"  # well_observed / partially_observed / not_reliably_observed
    consistency_observability_status: str = "well_observed"
    builder_observability_status: str = "well_observed"


@dataclass
class MatureProfileSignals:
    """v0.7: mature-profile interpretation signals."""
    mature_profile_mode: str = ""  # steward / established / none
    promise_suppression_flag: bool = False  # True when promise fields should be suppressed
    established_impact_profile_flag: bool = False  # True when profile has demonstrated impact


@dataclass
class SpecializationCoherenceSignals:
    """v0.7: specialization coherence signals."""
    domain_centrality_signal: float = 0.0  # strength of domain association from central repos
    specialization_override_penalty: float = 0.0  # penalty for override-dependent classification
    specialization_confidence_ceiling_reason: str = ""  # why confidence was capped
    # v0.8: domain directionality (trends toward domain without strong specialization)
    domain_directionality_signal: float = 0.0  # 0-1, whether contributor trends toward a domain
    domain_directionality_label: str = ""  # e.g. "visible movement toward build-systems"


@dataclass
class WordingStateSignals:
    """v0.8: wording-state signals for coherence enforcement."""
    external_acceptance_wording_state: str = ""  # none_detected / limited / meaningful / strong
    stewardship_wording_state: str = ""  # none_detected / limited / meaningful / strong
    collaboration_wording_state: str = ""  # none_detected / limited / meaningful / strong


@dataclass
class ReportIntegritySignals:
    """v0.8/v1.0: final-stage report integrity check results."""
    report_integrity_passed: bool = True
    promise_dimension_coherence_passed: bool = True
    wording_coherence_passed: bool = True
    observability_coherence_passed: bool = True
    integrity_issues: list[str] = field(default_factory=list)  # descriptions of issues found
    # v0.9: integrity mode and degraded flag
    integrity_mode: str = "user"  # user / debug
    report_degraded_flag: bool = False  # True if report has unresolvable issues
    # v1.0: auto-corrections tracking
    auto_corrections_applied: list[str] = field(default_factory=list)  # list of corrections made


@dataclass
class EvidenceRegimeSignals:
    """v0.9: sparse-evidence meta-classification."""
    evidence_regime: str = "normal"  # sparse / limited / normal / rich
    sparse_evidence_flag: bool = False  # True when in sparse regime
    specialization_sparse_cap_applied: bool = False  # True when specialization was capped
    evidence_regime_basis: str = ""  # human-readable explanation
    # Contributing factors
    total_collected_artifacts: int = 0
    external_evidence_present: bool = False
    observation_window_activity_count: int = 0
    # v1.0: evidence source tier for specialization (Priority C)
    specialization_source_tier: str = "metadata_only"  # metadata_only / metadata_plus_activity / metadata_plus_external_validation / rich_mixed_domain_evidence


@dataclass
class FoundationalBuilderSignals:
    """v0.9: foundational infrastructure builder signals (Route C)."""
    foundational_infrastructure_builder_signal: float = 0.0  # composite 0-1
    central_repo_substance_score: float = 0.0  # technical substance of central repos
    foundational_system_ownership_signal: float = 0.0  # ownership of foundational systems
    long_lived_repo_substance_score: float = 0.0  # substance of long-lived repos
    technical_foundation_signal: float = 0.0  # systems-level technical depth
    systems_scope_signal: float = 0.0  # scope of systems-level work


@dataclass
class BuilderSophisticationSignals:
    """v0.6: complex self-directed building signals."""
    # PR / change complexity
    large_pr_count: int = 0  # PRs with >= 200 additions
    very_large_pr_count: int = 0  # PRs with >= 500 additions
    median_additions_per_pr: float = 0.0
    max_additions_per_pr: int = 0
    median_changed_files_per_pr: float = 0.0
    max_changed_files_per_pr: int = 0
    multi_subsystem_pr_count: int = 0  # PRs touching >= 5 files
    large_pr_repo_count: int = 0  # repos with at least one large PR
    # Product breadth
    cross_layer_change_count: int = 0  # PRs with code + config/docs/deploy changes
    code_and_docs_change_count: int = 0
    code_and_deployment_change_count: int = 0
    product_scope_signal: float = 0.0  # breadth of product concerns
    repo_complexity_score: float = 0.0  # average complexity across all repos
    owned_repo_complexity_score: float = 0.0  # average complexity across owned repos
    # Delivery signals
    repeated_feature_delivery_count: int = 0  # repos with >= 3 large PRs
    repeated_major_delivery_count: int = 0  # repos with >= 2 very large PRs
    delivery_depth_signal: float = 0.0  # depth of repeated delivery
    # Composite builder signals
    builder_sophistication_signal: float = 0.0  # composite 0-1
    product_system_complexity_score: float = 0.0  # composite 0-1
    self_directed_build_depth_score: float = 0.0  # composite for self-directed only
    # Archetype support
    complex_product_builder_strength: float = 0.0  # archetype strength 0-1
    # v0.7: builder observability
    builder_observability_mode: str = ""  # pr_visible / repo_visible_but_pr_sparse / steward_dominant / insufficient_builder_evidence
    builder_observability_confidence: float = 0.0
    builder_evidence_coverage: float = 0.0  # 0-1 how much builder evidence is available
    builder_signal_path: str = ""  # pr_delivery / repo_complexity / mixed / insufficient
    # v0.7: Route B — repo substance signals (non-PR builder evidence)
    repo_substance_score: float = 0.0  # composite from owned repo breadth/substance
    owned_repo_breadth_score: float = 0.0  # diversity of owned repos
    # v0.9: Route C — foundational infrastructure builder signals
    foundational_builder_route_active: bool = False  # True when Route C applies
    foundational_builder_score: float = 0.0  # composite Route C score


@dataclass
class CollaborationSignals:
    review_activity_count: int = 0
    substantive_review_count: int = 0  # reviews with body > threshold
    issue_discussion_count: int = 0
    repos_with_repeated_collaboration: int = 0
    counterparty_count: int = 0
    accepted_after_feedback_count: int = 0  # PRs merged that had review iterations
    cross_repo_collaborator_diversity: int = 0  # counterparties seen in >1 repo
    # v0.2: expanded collaboration context
    unique_counterparty_count: int = 0
    repeated_counterparty_count: int = 0  # counterparties with >1 interaction
    external_counterparty_count: int = 0  # counterparties from external repos only
    multi_repo_counterparty_count: int = 0  # counterparties active in >1 repo
    review_iteration_count: int = 0  # reviews on PRs that had multiple rounds
    pr_with_discussion_count: int = 0  # PRs with comments + reviews


@dataclass
class TrustSignals:
    repeat_merges_same_repo: int = 0  # repos where merged >= 3
    sustained_repos: int = 0  # repos with activity spanning > 6 months
    repos_with_release_involvement: int = 0
    owned_repos_with_external_stars: int = 0
    owned_repos_with_external_contributors: int = 0
    maintainer_evidence_score: float = 0.0
    # v0.2: ownership-aware trust
    repeat_merges_external_repo: int = 0  # external repos where merged >= 3
    sustained_external_repos: int = 0  # external repos with >6mo activity span
    external_acceptance_visible: bool = False  # any externally merged PR exists


@dataclass
class EcosystemSignals:
    weighted_repo_importance: float = 0.0
    owned_repo_visibility: float = 0.0
    contributions_to_high_adoption_repos: int = 0
    release_involvement_count: int = 0


@dataclass
class SpecializationSignals:
    domain_distribution: dict[str, float] = field(default_factory=dict)  # domain -> weight
    domain_concentration_score: float = 0.0  # HHI-style
    primary_domain: str | None = None
    secondary_domains: list[str] = field(default_factory=list)
    language_distribution: dict[str, float] = field(default_factory=dict)
    # v0.2: richer domain context
    repos_per_domain: dict[str, int] = field(default_factory=dict)
    external_repos_per_domain: dict[str, int] = field(default_factory=dict)
    active_months_per_domain: dict[str, int] = field(default_factory=dict)
    domain_signal_support_count: int = 0  # repos that matched any domain
    # v0.3: domain confidence
    domain_inference_confidence: float = 0.0
    domain_override_applied: bool = False
    domain_support_breadth: int = 0  # repos supporting primary domain
    domain_support_duration: int = 0  # months of activity in primary domain


@dataclass
class ConsistencySignals:
    observed_months_active: int = 0
    total_months_in_window: int = 0
    active_month_ratio: float = 0.0
    burstiness: float = 0.0  # 0 = perfectly even, 1 = all in one month
    recency_score: float = 0.0  # higher = more recent activity
    repeat_return_repos: int = 0  # repos with activity in >1 quarter
    # v0.2: expanded consistency
    longest_inactive_gap_months: int = 0
    active_quarter_count: int = 0
    multi_quarter_repo_count: int = 0  # same as repeat_return_repos (explicit alias)


@dataclass
class SignalSet:
    contribution: ContributionSignals = field(default_factory=ContributionSignals)
    owned_projects: OwnedProjectSignals = field(default_factory=OwnedProjectSignals)
    stewardship: StewardshipSignals = field(default_factory=StewardshipSignals)
    execution_intensity: ExecutionIntensitySignals = field(default_factory=ExecutionIntensitySignals)
    collaboration: CollaborationSignals = field(default_factory=CollaborationSignals)
    trust: TrustSignals = field(default_factory=TrustSignals)
    ecosystem: EcosystemSignals = field(default_factory=EcosystemSignals)
    specialization: SpecializationSignals = field(default_factory=SpecializationSignals)
    consistency: ConsistencySignals = field(default_factory=ConsistencySignals)
    # v0.4: maturity, promise, steward contribution, impact calibration
    maturity: MaturitySignals = field(default_factory=MaturitySignals)
    promise: PromiseSignals = field(default_factory=PromiseSignals)
    steward_contribution: StewardContributionSignals = field(default_factory=StewardContributionSignals)
    impact_calibration: ImpactCalibrationSignals = field(default_factory=ImpactCalibrationSignals)
    # v0.5: calibration, archetype soft classification, specialization reliability, consistency interpretation
    contribution_calibration: ContributionCalibrationSignals = field(default_factory=ContributionCalibrationSignals)
    archetype_soft: ArchetypeSoftClassification = field(default_factory=ArchetypeSoftClassification)
    specialization_reliability: SpecializationReliabilitySignals = field(default_factory=SpecializationReliabilitySignals)
    consistency_interpretation: ConsistencyInterpretationSignals = field(default_factory=ConsistencyInterpretationSignals)
    # v0.6: builder sophistication
    builder_sophistication: BuilderSophisticationSignals = field(default_factory=BuilderSophisticationSignals)
    # v0.7: dimension coverage, mature profile, specialization coherence
    dimension_coverage: DimensionCoverageSignals = field(default_factory=DimensionCoverageSignals)
    mature_profile: MatureProfileSignals = field(default_factory=MatureProfileSignals)
    specialization_coherence: SpecializationCoherenceSignals = field(default_factory=SpecializationCoherenceSignals)
    # v0.8: wording state, report integrity
    wording_state: WordingStateSignals = field(default_factory=WordingStateSignals)
    report_integrity: ReportIntegritySignals = field(default_factory=ReportIntegritySignals)
    # v0.9: evidence regime, foundational builder
    evidence_regime: EvidenceRegimeSignals = field(default_factory=EvidenceRegimeSignals)
    foundational_builder: FoundationalBuilderSignals = field(default_factory=FoundationalBuilderSignals)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Dimension results
# ---------------------------------------------------------------------------

@dataclass
class DimensionResult:
    name: str
    score: ScoreBand
    confidence: ConfidenceBand
    claim: str
    evidence_summary: str
    interpretation: str
    limitation: str
    # v0.7: observability status
    observability_status: str = "well_observed"  # well_observed / partially_observed / not_reliably_observed


@dataclass
class FinalDimensionResult:
    """v1.0: single canonical rendered dimension result.

    All output surfaces (CLI summary, markdown report, JSON, API) must render
    exclusively from these fields.  No renderer may read raw internal score
    fields directly for user-facing output.
    """
    name: str
    # Resolved display state
    status: str = "scored"  # scored / not_reliably_observable / suppressed
    score_label: str = ""  # e.g. "Strong", "" when not scored
    confidence_label: str = ""  # e.g. "Medium", "" when not scored
    observability_label: str = ""  # e.g. "Well Observed", "Not Reliably Observable"
    display_label: str = ""  # final user-facing one-liner, e.g. "Strong / Medium"
    # Explanation
    explanation_mode: str = "standard"  # standard / sparse_evidence / foundational_route / temporal_fallback / nro_steward
    supporting_route: str = ""  # e.g. "Route A (PR delivery)", "Route C (foundational infrastructure)", ""
    # Evidence provenance (§3.2)
    dominant_scoring_route: str = ""  # which evidence family contributed most
    score_cap_applied: bool = False  # whether any cap was applied
    cap_reason: str = ""  # why a cap was applied, if any
    observability_constraint_applied: bool = False  # whether observability limited the result
    # Content
    claim: str = ""
    evidence_summary: str = ""
    interpretation: str = ""
    limitation: str = ""


@dataclass
class DomainInference:
    primary_domain: str | None
    secondary_domains: list[str]
    evidence: str  # what drove the inference
    confidence: float = 0.0  # v0.3: 0-1 domain inference confidence
    override_applied: bool = False


@dataclass
class ArchetypeResult:
    archetype: Archetype
    detected: bool
    confidence: float  # 0-1
    basis: str  # why it was detected or not


@dataclass
class StageInterpretation:
    """v0.4: stage-aware interpretation layer."""
    maturity_band: MaturityBand
    maturity_basis: str
    promise_summary: str  # stage-aware promise statement
    contributor_type: str  # e.g. "established independent builder"
    readiness_summary: str  # what opportunities this evidence suggests


@dataclass
class EvaluationResult:
    subject: str
    observation_window_start: str
    observation_window_end: str
    repos_evaluated: int
    dimensions: list[DimensionResult]
    domain_inference: DomainInference
    archetypes: list[ArchetypeResult] = field(default_factory=list)
    stage_interpretation: StageInterpretation | None = None
    # v1.0: canonical final dimension results for rendering
    final_dimensions: list[FinalDimensionResult] = field(default_factory=list)
    methodology_version: str = "1.0.0"

    def to_dict(self) -> dict:
        d = asdict(self)
        # Enum values need to be serialized as strings
        for dim in d["dimensions"]:
            dim["score"] = dim["score"] if isinstance(dim["score"], str) else dim["score"].value
            dim["confidence"] = dim["confidence"] if isinstance(dim["confidence"], str) else dim["confidence"].value
        return d


# =========================================================================
# Package-contract models (Design 1–4 from decision record)
# =========================================================================

# ---------------------------------------------------------------------------
# EvaluationReport section models (Design 1)
# ---------------------------------------------------------------------------

@dataclass
class SubjectSummary:
    """Display-safe subject summary."""
    username: str
    name: str | None = None
    account_created: str | None = None  # ISO-8601
    public_repos: int = 0
    followers: int = 0
    bio: str | None = None


@dataclass
class EvaluationScope:
    """Observation window and collection counts."""
    window_start: str  # ISO-8601
    window_end: str
    repos_evaluated: int = 0
    pull_requests_collected: int = 0
    reviews_collected: int = 0
    issues_collected: int = 0
    releases_collected: int = 0
    counterparties_tracked: int = 0


@dataclass
class MaturitySection:
    """Maturity band and evidence regime context."""
    band: str  # MaturityBand value
    basis: str  # human-readable explanation
    evidence_regime: str  # sparse / limited / normal / rich
    source_tier: str = ""  # specialization source tier


@dataclass
class ReadinessSection:
    """Stage interpretation for report display."""
    contributor_type: str
    readiness_summary: str
    promise_summary: str = ""  # may be suppressed for mature profiles


@dataclass
class RepositoryEntry:
    """Typed repository entry for the report repository table."""
    name: str
    owner: str
    stars: int = 0
    language: str | None = None
    role: str = ""  # e.g. "owner", "contributor"
    is_primary: bool = False


@dataclass
class BuilderRouteHighlight:
    """Builder route signal summary for report display."""
    route_label: str  # "Route A (PR delivery)", etc.
    active: bool = False
    key_signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalHighlights:
    """Typed signal highlight sections for report display.

    Contains only the signal families intended for report rendering,
    not the full internal signal set.
    """
    builder_routes: list[BuilderRouteHighlight] = field(default_factory=list)
    contribution_highlights: dict[str, Any] = field(default_factory=dict)
    evidence_regime_detail: dict[str, Any] = field(default_factory=dict)
    specialization_summary: dict[str, Any] = field(default_factory=dict)
    consistency_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegritySection:
    """Report integrity state for display."""
    passed: bool = True
    degraded: bool = False
    mode: str = "user"
    issue_summary: list[str] = field(default_factory=list)
    auto_corrections: list[str] = field(default_factory=list)


@dataclass
class MethodologySection:
    """Methodology metadata and scope statement."""
    methodology_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    scope_statement: str = (
        "This report measures public GitHub-visible evidence — contribution "
        "patterns, stewardship signals, builder signals, and public adoption "
        "proxies.  It does not measure total professional ability, private "
        "work, organizational leadership, hiring skill, strategic judgment, "
        "or business success."
    )
    experimental_labels: list[str] = field(default_factory=lambda: ["Specialization Strength"])


@dataclass
class EvaluationReport:
    """Typed structured report — all renderers serialize from this model.

    Contains display-safe sections.  Canonical final dimension results
    live in the ``dimensions`` field.
    """
    subject: SubjectSummary
    scope: EvaluationScope
    archetypes: list[ArchetypeResult] = field(default_factory=list)
    maturity: MaturitySection | None = None
    dimensions: list[FinalDimensionResult] = field(default_factory=list)
    readiness: ReadinessSection | None = None
    signal_highlights: SignalHighlights | None = None
    repository_set: list[RepositoryEntry] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    integrity: IntegritySection | None = None
    methodology: MethodologySection = field(default_factory=MethodologySection)
    domain_inference: DomainInference | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# CompactSummary (Design 2)
# ---------------------------------------------------------------------------

@dataclass
class DimensionSummaryEntry:
    """Compact per-dimension entry for summaries."""
    name: str
    status: str  # scored / not_reliably_observable / suppressed
    score_label: str = ""
    confidence_label: str = ""


@dataclass
class CompactSummary:
    """Compact summary for CLI output, UI cards, and previews."""
    username: str
    maturity_band: str = ""
    evidence_regime: str = ""
    primary_domain: str | None = None
    secondary_domains: list[str] = field(default_factory=list)
    dimensions: list[DimensionSummaryEntry] = field(default_factory=list)
    readiness_summary: str = ""
    methodology_version: str = "1.0.0"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Request / Result contract (Design 2)
# ---------------------------------------------------------------------------

@dataclass
class EvaluateGitHubProfileRequest:
    """Structured request for the package entry point."""
    github_username: str
    observation_window: str = "3y"  # 1y / 2y / 3y / 5y / all
    max_repositories: int = 50
    include_markdown_report: bool = True
    include_summary: bool = True
    include_raw_evidence: bool = False
    include_signals: bool = False
    github_token: str | None = None
    run_mode: str = "user"  # user / debug


@dataclass
class EvaluateGitHubProfileResult:
    """Top-level result returned by evaluate_github_profile().

    Layers that were not requested are set to None (field is always present).
    """
    methodology_version: str
    schema_version: str
    generated_at: str  # ISO-8601
    report: EvaluationReport
    evidence: dict | None = None  # full normalized evidence when requested
    signals: dict | None = None  # full signal snapshot when requested
    markdown_report: str | None = None
    summary: CompactSummary | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d
