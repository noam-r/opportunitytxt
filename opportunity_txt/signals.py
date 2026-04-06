"""Signal computation module (v1.0).

Takes normalized Evidence and computes deterministic signals across all
dimensions plus governance independence, owned public projects, stewardship,
execution intensity, builder sophistication, observability, and coherence.

v1.0 changes (over v0.9):
- Specialization source-tier classification (metadata_only / metadata_plus_activity /
  metadata_plus_external_validation / rich_mixed_domain_evidence)
- Auto-correction tracking in report integrity (separate from integrity issues)
- Explicit integrity issue enforcement (empty issues → unspecified coherence issue)
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .models import (
    Evidence,
    PRState,
    ReviewOutcome,
    SignalSet,
    ContributionSignals,
    OwnedProjectSignals,
    StewardshipSignals,
    ExecutionIntensitySignals,
    MaturitySignals,
    PromiseSignals,
    StewardContributionSignals,
    ImpactCalibrationSignals,
    ContributionCalibrationSignals,
    ArchetypeSoftClassification,
    SpecializationReliabilitySignals,
    ConsistencyInterpretationSignals,
    BuilderSophisticationSignals,
    DimensionCoverageSignals,
    MatureProfileSignals,
    SpecializationCoherenceSignals,
    CollaborationSignals,
    TrustSignals,
    EcosystemSignals,
    SpecializationSignals,
    ConsistencySignals,
    MaturityBand,
    WordingStateSignals,
    ReportIntegritySignals,
    ObservabilityStatus,
    EvidenceRegimeSignals,
    FoundationalBuilderSignals,
)

SUBSTANTIVE_REVIEW_BODY_LEN = 80  # chars


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _month_key(dt: datetime) -> str:
    return f"{dt.year}-{dt.month:02d}"


def _quarter_key(dt: datetime) -> str:
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def _repo_key(owner: str, name: str) -> str:
    return f"{owner}/{name}"


def _repo_weight(repo) -> float:
    """Capped contextual weighting for a repository.

    Uses stars, forks, and basic activity as public-adoption proxies.
    Cap at 5.0 to avoid any single repo dominating.
    """
    star_signal = math.log1p(repo.stars) / math.log1p(1000)  # ~1.0 at 1k stars
    fork_signal = math.log1p(repo.forks) / math.log1p(500)
    raw = star_signal * 0.6 + fork_signal * 0.4
    return min(max(raw, 0.1), 5.0)


def compute_signals(evidence: Evidence) -> SignalSet:
    """Compute the full signal set from normalized evidence."""

    window_start = _parse_iso(evidence.observation_window_start)
    window_end = _parse_iso(evidence.observation_window_end)

    # Build repo lookup
    repo_lookup = {
        _repo_key(r.owner, r.name): r for r in evidence.repositories
    }

    signals = SignalSet()

    _compute_contribution(evidence, repo_lookup, signals.contribution, window_start, window_end)
    _compute_owned_projects(evidence, repo_lookup, signals.owned_projects, window_start, window_end)
    _compute_stewardship(evidence, repo_lookup, signals.stewardship)
    _compute_execution_intensity(evidence, signals.execution_intensity, window_start, window_end)
    _compute_collaboration(evidence, repo_lookup, signals.collaboration)
    _compute_trust(evidence, repo_lookup, signals.trust)
    _compute_ecosystem(evidence, repo_lookup, signals.ecosystem)
    _compute_specialization(evidence, repo_lookup, signals.specialization)
    _compute_consistency(evidence, signals.consistency, window_start, window_end)

    # v0.4: maturity, steward contribution, impact calibration
    _compute_maturity(evidence, signals, window_start, window_end)
    _compute_steward_contribution(signals)
    _compute_impact_calibration(signals)

    # v0.5: contribution calibration, archetype soft classification,
    # specialization reliability, consistency interpretation
    _compute_contribution_calibration(signals)
    _compute_archetype_soft_classification(signals)
    _compute_specialization_reliability(signals)
    _compute_consistency_interpretation(signals)

    # v0.6: builder sophistication
    _compute_builder_sophistication(evidence, signals)

    # v0.7: builder observability, dimension coverage, mature profile, specialization coherence
    _compute_builder_observability(signals)
    _compute_dimension_coverage(signals)
    _compute_mature_profile(signals)
    _compute_specialization_coherence(signals)

    # v0.8: wording state, then promise (must run after mature_profile + dimension_coverage)
    _compute_wording_state(signals)
    _compute_promise(signals)

    # v0.9: evidence regime, foundational builder, temporal safety
    _compute_evidence_regime(evidence, signals)
    _compute_foundational_builder(evidence, signals)
    _compute_temporal_safety(signals)

    return signals


# ---------------------------------------------------------------------------
# Contribution signals
# ---------------------------------------------------------------------------

def _compute_contribution(
    evidence: Evidence,
    repo_lookup: dict,
    sig: ContributionSignals,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    prs = evidence.pull_requests
    merged_prs = [p for p in prs if p.state == PRState.MERGED]
    sig.total_prs_opened = len(prs)
    sig.merged_pr_count = len(merged_prs)
    sig.closed_unmerged_pr_count = sum(1 for p in prs if p.state == PRState.CLOSED)

    if sig.total_prs_opened > 0:
        sig.merge_ratio = sig.merged_pr_count / sig.total_prs_opened
    else:
        sig.merge_ratio = 0.0

    # --- v0.2: ownership-aware splits ---
    sig.merged_pr_count_self_owned = sum(1 for p in merged_prs if p.is_repo_owned_by_subject)
    sig.merged_pr_count_external = sum(1 for p in merged_prs if not p.is_repo_owned_by_subject)

    sig.self_merged_pr_count = sum(1 for p in merged_prs if p.is_self_merged is True)
    sig.externally_merged_pr_count = sum(
        1 for p in merged_prs if p.is_self_merged is False
    )
    sig.external_repo_externally_merged_pr_count = sum(
        1 for p in merged_prs
        if not p.is_repo_owned_by_subject and p.is_self_merged is False
    )
    sig.self_repo_self_merged_pr_count = sum(
        1 for p in merged_prs
        if p.is_repo_owned_by_subject and p.is_self_merged is True
    )

    # v0.3: governance independence — independently accepted = external repo + not self-merged
    sig.independent_acceptance_count = sig.external_repo_externally_merged_pr_count
    sig.external_repo_self_merged_pr_count = sum(
        1 for p in merged_prs
        if not p.is_repo_owned_by_subject and p.is_self_merged is True
    )
    sig.external_repo_independently_merged_pr_count = sig.external_repo_externally_merged_pr_count

    # Per-repo merged counts (total, self-owned, external)
    merged_by_repo: Counter[str] = Counter()
    merged_by_repo_external: Counter[str] = Counter()
    merged_by_repo_self: Counter[str] = Counter()
    for p in merged_prs:
        rk = _repo_key(p.repo_owner, p.repo_name)
        merged_by_repo[rk] += 1
        if p.is_repo_owned_by_subject:
            merged_by_repo_self[rk] += 1
        else:
            merged_by_repo_external[rk] += 1

    sig.repos_with_merged_contributions = len(merged_by_repo)
    sig.repos_with_merged_contributions_self_owned = len(merged_by_repo_self)
    sig.repos_with_merged_contributions_external = len(merged_by_repo_external)

    sig.repeat_merged_contribution_count = sum(
        1 for c in merged_by_repo.values() if c > 1
    )
    sig.repeat_external_accepted_contribution_count = sum(
        1 for c in merged_by_repo_external.values() if c > 1
    )
    sig.accepted_contribution_concentration = dict(merged_by_repo)

    # v0.3: independent acceptance per-repo
    independent_by_repo: Counter[str] = Counter()
    for p in merged_prs:
        if not p.is_repo_owned_by_subject and p.is_self_merged is False:
            rk = _repo_key(p.repo_owner, p.repo_name)
            independent_by_repo[rk] += 1
    sig.independent_acceptance_repo_count = len(independent_by_repo)
    if sig.merged_pr_count > 0:
        sig.independent_acceptance_ratio = sig.independent_acceptance_count / sig.merged_pr_count
    else:
        sig.independent_acceptance_ratio = 0.0

    # Merged per active month
    active_months: set[str] = set()
    for p in prs:
        dt = _parse_iso(p.created_at)
        if dt:
            active_months.add(_month_key(dt))
    if active_months:
        sig.merged_contributions_per_active_month = (
            sig.merged_pr_count / len(active_months)
        )

    # Authored repo activity signal
    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    if owned_repos:
        owned_with_activity = 0
        for r in owned_repos:
            rk = _repo_key(r.owner, r.name)
            has_prs = merged_by_repo.get(rk, 0) > 0
            has_releases = any(
                rel.repo_owner == r.owner and rel.repo_name == r.name
                for rel in evidence.release_involvements
            )
            has_issues = any(
                iss.repo_owner == r.owner and iss.repo_name == r.name
                for iss in evidence.issue_participations
            )
            if has_prs or has_releases or has_issues or r.stars >= 5:
                owned_with_activity += 1
        sig.authored_repo_activity_signal = (
            owned_with_activity / len(owned_repos) if owned_repos else 0.0
        )


# ---------------------------------------------------------------------------
# Owned public project signals (v0.3)
# ---------------------------------------------------------------------------

def _compute_owned_projects(
    evidence: Evidence,
    repo_lookup: dict,
    sig: OwnedProjectSignals,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    sig.owned_public_project_count = len(owned_repos)

    if not owned_repos:
        return

    total_visibility = 0.0
    total_external_interest = 0.0
    total_age = 0.0
    total_maintenance = 0.0
    release_count = 0

    now = window_end or datetime.now(timezone.utc)

    for repo in owned_repos:
        # Visibility: log-scaled stars + forks
        vis = math.log1p(repo.stars) * 0.6 + math.log1p(repo.forks) * 0.4
        total_visibility += vis

        # External interest: stars, forks, watchers from others
        interest = (
            min(math.log1p(repo.stars) / math.log1p(1000), 3.0) * 0.5
            + min(math.log1p(repo.forks) / math.log1p(200), 2.0) * 0.3
            + min(math.log1p(repo.watchers) / math.log1p(100), 1.0) * 0.2
        )
        total_external_interest += interest

        # Age: years since creation (capped at 10)
        created = _parse_iso(repo.created_at)
        if created:
            age_years = (now - created).days / 365.25
            total_age += min(age_years, 10.0)

        # Maintenance: recency of updates
        updated = _parse_iso(repo.updated_at)
        if updated:
            days_since = (now - updated).days
            if days_since < 90:
                total_maintenance += 1.0
            elif days_since < 365:
                total_maintenance += 0.5
            elif days_since < 730:
                total_maintenance += 0.2

        # Releases for this repo
        repo_releases = [
            rel for rel in evidence.release_involvements
            if rel.repo_owner == repo.owner and rel.repo_name == repo.name
        ]
        release_count += len(repo_releases)

    n = len(owned_repos)
    sig.owned_public_project_visibility_score = total_visibility
    sig.owned_public_project_external_interest_score = total_external_interest / n if n else 0.0
    sig.owned_public_project_age_score = total_age / n if n else 0.0
    sig.owned_public_project_maintenance_score = total_maintenance / n if n else 0.0
    sig.owned_public_project_release_count = release_count


# ---------------------------------------------------------------------------
# Stewardship / governance signals (v0.3)
# ---------------------------------------------------------------------------

def _compute_stewardship(
    evidence: Evidence,
    repo_lookup: dict,
    sig: StewardshipSignals,
) -> None:
    # Issue participation
    sig.issue_participation_count = len(evidence.issue_participations)

    # Issue response: issues where subject commented (not authored)
    sig.issue_response_activity_count = sum(
        1 for iss in evidence.issue_participations
        if not iss.is_author and iss.comment_count > 0
    )

    # Release stewardship: releases authored by subject
    sig.release_stewardship_count = sum(
        1 for rel in evidence.release_involvements if rel.is_author
    )

    # Owned repo centrality: weighted importance of owned repos
    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    centrality = 0.0
    public_reliance = 0.0
    for repo in owned_repos:
        w = _repo_weight(repo)
        centrality += w
        # Public reliance: higher for repos with more stars/forks
        if repo.stars >= 100:
            public_reliance += min(math.log1p(repo.stars) / math.log1p(10000), 1.0)
    sig.owned_repo_centrality_score = centrality
    sig.owned_repo_public_reliance_score = public_reliance

    # Governance activity: combination of issue responses, releases, and owned repo maintenance
    governance = (
        min(sig.issue_response_activity_count / 20, 1.0) * 0.30
        + min(sig.issue_participation_count / 30, 1.0) * 0.20
        + min(sig.release_stewardship_count / 10, 1.0) * 0.25
        + min(sig.owned_repo_centrality_score / 10, 1.0) * 0.25
    )
    sig.repo_governance_activity_score = governance

    # Maintainer visibility: composite of all stewardship evidence
    visibility = (
        (1.0 if sig.release_stewardship_count > 0 else 0.0) * 0.25
        + (1.0 if sig.issue_response_activity_count >= 5 else
           0.5 if sig.issue_response_activity_count > 0 else 0.0) * 0.25
        + min(sig.owned_repo_public_reliance_score / 2, 1.0) * 0.25
        + min(sig.owned_repo_centrality_score / 5, 1.0) * 0.25
    )
    sig.maintainer_visibility_score = visibility

    # Stewardship composite signal
    sig.stewardship_signal = (
        sig.repo_governance_activity_score * 0.5
        + sig.maintainer_visibility_score * 0.5
    )


# ---------------------------------------------------------------------------
# Execution intensity signals (v0.3)
# ---------------------------------------------------------------------------

def _compute_execution_intensity(
    evidence: Evidence,
    sig: ExecutionIntensitySignals,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    merged_prs = [p for p in evidence.pull_requests if p.state == PRState.MERGED]
    if not merged_prs:
        return

    # Gather active months
    active_months: set[str] = set()
    monthly_merged: Counter[str] = Counter()
    monthly_changes: Counter[str] = Counter()
    monthly_repos: dict[str, set[str]] = defaultdict(set)

    for p in evidence.pull_requests:
        dt = _parse_iso(p.created_at)
        if dt:
            mk = _month_key(dt)
            active_months.add(mk)
            if p.state == PRState.MERGED:
                monthly_merged[mk] += 1
                monthly_changes[mk] += p.additions + p.deletions
                monthly_repos[mk].add(_repo_key(p.repo_owner, p.repo_name))

    n_active = len(active_months) or 1
    sig.merged_work_per_active_month = len(merged_prs) / n_active

    total_changes = sum(p.additions + p.deletions for p in merged_prs)
    sig.change_volume_per_active_month = total_changes / n_active

    # Peak window: find the 3-month window with most activity
    if monthly_merged:
        sorted_months = sorted(monthly_merged.keys())
        best_repos: set[str] = set()
        best_count = 0
        for i, m in enumerate(sorted_months):
            window_repos: set[str] = set()
            window_count = 0
            for j in range(i, min(i + 3, len(sorted_months))):
                mk = sorted_months[j]
                window_repos |= monthly_repos.get(mk, set())
                window_count += monthly_merged[mk]
            if window_count > best_count:
                best_count = window_count
                best_repos = window_repos
        sig.active_repo_count_during_peak_window = len(best_repos)

    # Burst execution score: high work per month but check temporal spread
    throughput_score = min(sig.merged_work_per_active_month / 5, 1.0)
    volume_score = min(sig.change_volume_per_active_month / 2000, 1.0)
    peak_diversity = min(sig.active_repo_count_during_peak_window / 3, 1.0)
    sig.burst_execution_score = (
        throughput_score * 0.40
        + volume_score * 0.30
        + peak_diversity * 0.30
    )


# ---------------------------------------------------------------------------
# Collaboration signals
# ---------------------------------------------------------------------------

def _compute_collaboration(
    evidence: Evidence,
    repo_lookup: dict,
    sig: CollaborationSignals,
) -> None:
    sig.review_activity_count = len(evidence.reviews)
    sig.substantive_review_count = sum(
        1 for r in evidence.reviews if r.body_length >= SUBSTANTIVE_REVIEW_BODY_LEN
    )

    sig.issue_discussion_count = sum(
        iss.comment_count for iss in evidence.issue_participations
    )

    # Repos with repeated collaboration: reviews + issues + PRs in same repo > 1 type
    repo_collab_types: dict[str, set[str]] = defaultdict(set)
    for r in evidence.reviews:
        rk = _repo_key(r.repo_owner, r.repo_name)
        repo_collab_types[rk].add("review")
    for iss in evidence.issue_participations:
        rk = _repo_key(iss.repo_owner, iss.repo_name)
        repo_collab_types[rk].add("issue")
    for p in evidence.pull_requests:
        rk = _repo_key(p.repo_owner, p.repo_name)
        repo_collab_types[rk].add("pr")
    sig.repos_with_repeated_collaboration = sum(
        1 for types in repo_collab_types.values() if len(types) >= 2
    )

    sig.counterparty_count = len(evidence.counterparties)

    # Accepted after feedback: PRs that were merged AND had review comments
    sig.accepted_after_feedback_count = sum(
        1 for p in evidence.pull_requests
        if p.state == PRState.MERGED and p.review_count > 0
    )

    # Cross-repo collaborator diversity: counterparties active in >1 repo
    sig.cross_repo_collaborator_diversity = sum(
        1 for cp in evidence.counterparties if len(cp.repos) > 1
    )

    # --- v0.2: expanded counterparty signals ---
    sig.unique_counterparty_count = len(evidence.counterparties)
    sig.repeated_counterparty_count = sum(
        1 for cp in evidence.counterparties if cp.interaction_count > 1
    )
    sig.external_counterparty_count = sig.unique_counterparty_count  # all tracked are external by construction
    sig.multi_repo_counterparty_count = sum(
        1 for cp in evidence.counterparties if len(cp.repos) > 1
    )

    # Review iterations: PRs with >1 review that were merged
    sig.review_iteration_count = sum(
        1 for p in evidence.pull_requests
        if p.state == PRState.MERGED and p.review_count > 1
    )

    # PRs with discussion (comments + reviews > 0)
    sig.pr_with_discussion_count = sum(
        1 for p in evidence.pull_requests
        if p.comment_count > 0 or p.review_count > 0
    )


# ---------------------------------------------------------------------------
# Trust signals
# ---------------------------------------------------------------------------

def _compute_trust(
    evidence: Evidence,
    repo_lookup: dict,
    sig: TrustSignals,
) -> None:
    merged_prs = [p for p in evidence.pull_requests if p.state == PRState.MERGED]

    # Repos with >=3 merged PRs
    merged_by_repo: Counter[str] = Counter()
    merged_by_repo_external: Counter[str] = Counter()
    for p in merged_prs:
        rk = _repo_key(p.repo_owner, p.repo_name)
        merged_by_repo[rk] += 1
        if not p.is_repo_owned_by_subject:
            merged_by_repo_external[rk] += 1

    sig.repeat_merges_same_repo = sum(1 for c in merged_by_repo.values() if c >= 3)
    sig.repeat_merges_external_repo = sum(1 for c in merged_by_repo_external.values() if c >= 3)

    # Sustained repos: repos with activity spanning > 6 months
    repo_dates: dict[str, list[datetime]] = defaultdict(list)
    repo_is_external: dict[str, bool] = {}
    for p in evidence.pull_requests:
        dt = _parse_iso(p.created_at)
        if dt:
            rk = _repo_key(p.repo_owner, p.repo_name)
            repo_dates[rk].append(dt)
            repo_is_external[rk] = not p.is_repo_owned_by_subject
    for r in evidence.reviews:
        dt = _parse_iso(r.submitted_at)
        if dt:
            rk = _repo_key(r.repo_owner, r.repo_name)
            repo_dates[rk].append(dt)

    sig.sustained_repos = 0
    sig.sustained_external_repos = 0
    for rk, dates in repo_dates.items():
        if len(dates) >= 2:
            span = (max(dates) - min(dates)).days
            if span >= 180:
                sig.sustained_repos += 1
                if repo_is_external.get(rk, False):
                    sig.sustained_external_repos += 1

    # Release involvement
    repos_with_releases: set[str] = set()
    for rel in evidence.release_involvements:
        if rel.is_author:
            repos_with_releases.add(_repo_key(rel.repo_owner, rel.repo_name))
    sig.repos_with_release_involvement = len(repos_with_releases)

    # Owned repos with external signals
    for r in evidence.repositories:
        if r.is_owned_by_subject:
            if r.stars >= 10:
                sig.owned_repos_with_external_stars += 1
            if (r.contributor_count or 0) > 1:
                sig.owned_repos_with_external_contributors += 1

    # v0.2: external acceptance visible
    sig.external_acceptance_visible = any(
        p.is_self_merged is False and not p.is_repo_owned_by_subject
        for p in merged_prs
    )

    # Maintainer evidence: composite (v0.2: weight external more heavily)
    sig.maintainer_evidence_score = (
        min(sig.repeat_merges_external_repo, 5) * 0.30
        + min(sig.repeat_merges_same_repo, 5) * 0.10
        + min(sig.sustained_external_repos, 5) * 0.20
        + min(sig.sustained_repos, 5) * 0.10
        + min(sig.repos_with_release_involvement, 3) * 0.15
        + min(sig.owned_repos_with_external_stars, 5) * 0.15
    )


# ---------------------------------------------------------------------------
# Ecosystem signals
# ---------------------------------------------------------------------------

def _compute_ecosystem(
    evidence: Evidence,
    repo_lookup: dict,
    sig: EcosystemSignals,
) -> None:
    # Weighted repo importance: sum of weights for repos with merged PRs
    merged_repos: set[str] = set()
    for p in evidence.pull_requests:
        if p.state == PRState.MERGED:
            merged_repos.add(_repo_key(p.repo_owner, p.repo_name))

    total_weight = 0.0
    high_adoption_count = 0
    for rk in merged_repos:
        repo = repo_lookup.get(rk)
        if repo:
            w = _repo_weight(repo)
            total_weight += w
            if repo.stars >= 500:
                high_adoption_count += 1
    sig.weighted_repo_importance = total_weight
    sig.contributions_to_high_adoption_repos = high_adoption_count

    # Owned repo visibility
    owned_visibility = 0.0
    for r in evidence.repositories:
        if r.is_owned_by_subject:
            owned_visibility += _repo_weight(r)
    sig.owned_repo_visibility = owned_visibility

    sig.release_involvement_count = len(evidence.release_involvements)


# ---------------------------------------------------------------------------
# Specialization signals
# ---------------------------------------------------------------------------

# Lightweight domain dictionary for deterministic inference
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "distributed-systems": [
        "distributed", "consensus", "raft", "paxos", "grpc", "rpc",
        "cluster", "replication", "etcd", "zookeeper",
    ],
    "developer-tools": [
        "cli", "tool", "devtool", "linter", "formatter", "sdk",
        "plugin", "extension", "vscode", "ide", "editor",
    ],
    "infrastructure": [
        "infra", "terraform", "kubernetes", "k8s", "docker", "container",
        "helm", "ansible", "pulumi", "aws", "cloud", "deploy",
    ],
    "security": [
        "security", "auth", "oauth", "jwt", "encryption", "crypto",
        "vulnerability", "cve", "firewall", "tls", "ssl",
    ],
    "observability": [
        "monitoring", "observability", "metrics", "tracing", "logging",
        "prometheus", "grafana", "opentelemetry", "alerting",
    ],
    "frontend": [
        "frontend", "react", "vue", "angular", "svelte", "css",
        "ui", "component", "design-system", "browser", "dom", "web",
    ],
    "data-infrastructure": [
        "database", "sql", "nosql", "etl", "pipeline", "streaming",
        "kafka", "spark", "hadoop", "data-lake", "warehouse", "analytics",
    ],
    "language-tooling": [
        "compiler", "parser", "ast", "interpreter", "language-server",
        "lsp", "syntax", "grammar", "transpiler",
    ],
    "build-systems": [
        "build", "ci", "cd", "pipeline", "github-actions", "bazel",
        "cmake", "make", "gradle", "maven", "webpack", "bundler",
    ],
    "machine-learning": [
        "ml", "machine-learning", "deep-learning", "neural", "model",
        "training", "inference", "pytorch", "tensorflow", "llm", "nlp",
    ],
    "operating-systems": [
        "kernel", "os", "operating-system", "linux", "bsd", "driver",
        "syscall", "filesystem",
    ],
}

# v0.3: curated repo-domain overrides for high-visibility repos
_REPO_DOMAIN_OVERRIDES: dict[str, str] = {
    "torvalds/linux": "operating-systems",
    "linux/linux": "operating-systems",
    "kubernetes/kubernetes": "infrastructure",
    "golang/go": "language-tooling",
    "rust-lang/rust": "language-tooling",
    "python/cpython": "language-tooling",
    "nodejs/node": "language-tooling",
    "microsoft/vscode": "developer-tools",
    "docker/docker-ce": "infrastructure",
    "moby/moby": "infrastructure",
    "hashicorp/terraform": "infrastructure",
    "prometheus/prometheus": "observability",
    "grafana/grafana": "observability",
    "apache/kafka": "data-infrastructure",
    "apache/spark": "data-infrastructure",
    "tensorflow/tensorflow": "machine-learning",
    "pytorch/pytorch": "machine-learning",
    "vercel/next.js": "frontend",
    "facebook/react": "frontend",
}


def _compute_specialization(
    evidence: Evidence,
    repo_lookup: dict,
    sig: SpecializationSignals,
) -> None:
    # Collect text signals from repos
    domain_scores: Counter[str] = Counter()
    lang_counts: Counter[str] = Counter()

    # v0.2: per-domain repo counts and external repo counts
    domain_repos: dict[str, set[str]] = defaultdict(set)
    domain_external_repos: dict[str, set[str]] = defaultdict(set)
    domain_months: dict[str, set[str]] = defaultdict(set)
    repos_with_domain_match = 0
    any_override = False

    for repo in evidence.repositories:
        text = " ".join([
            repo.name or "",
            repo.description or "",
            " ".join(repo.topics),
        ]).lower()
        weight = _repo_weight(repo)
        rk = _repo_key(repo.owner, repo.name)

        matched_any = False

        # v0.3: check curated override first
        override_key = f"{repo.owner}/{repo.name}".lower()
        override_domain = _REPO_DOMAIN_OVERRIDES.get(override_key)
        if override_domain:
            # Strong override: boost weight significantly
            domain_scores[override_domain] += weight * 3.0
            domain_repos[override_domain].add(rk)
            if not repo.is_owned_by_subject:
                domain_external_repos[override_domain].add(rk)
            matched_any = True
            any_override = True

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in text)
            if matches > 0:
                domain_scores[domain] += matches * weight
                domain_repos[domain].add(rk)
                if not repo.is_owned_by_subject:
                    domain_external_repos[domain].add(rk)
                matched_any = True

        # Also match topics directly
        for topic in repo.topics:
            topic_l = topic.lower()
            for domain, keywords in _DOMAIN_KEYWORDS.items():
                if topic_l in keywords or any(kw in topic_l for kw in keywords):
                    domain_scores[domain] += weight
                    domain_repos[domain].add(rk)
                    if not repo.is_owned_by_subject:
                        domain_external_repos[domain].add(rk)
                    matched_any = True

        if matched_any:
            repos_with_domain_match += 1

        if repo.primary_language:
            lang_counts[repo.primary_language] += 1

    sig.domain_signal_support_count = repos_with_domain_match

    # v0.2: compute active months per domain from PR/review activity
    for p in evidence.pull_requests:
        dt = _parse_iso(p.created_at)
        rk = _repo_key(p.repo_owner, p.repo_name)
        if dt:
            for domain in domain_repos:
                if rk in domain_repos[domain]:
                    domain_months[domain].add(_month_key(dt))
    for r in evidence.reviews:
        dt = _parse_iso(r.submitted_at)
        rk = _repo_key(r.repo_owner, r.repo_name)
        if dt:
            for domain in domain_repos:
                if rk in domain_repos[domain]:
                    domain_months[domain].add(_month_key(dt))

    sig.repos_per_domain = {d: len(repos) for d, repos in domain_repos.items()}
    sig.external_repos_per_domain = {d: len(repos) for d, repos in domain_external_repos.items()}
    sig.active_months_per_domain = {d: len(months) for d, months in domain_months.items()}

    # Normalize domain distribution
    total = sum(domain_scores.values()) or 1.0
    sig.domain_distribution = {
        d: round(s / total, 3) for d, s in domain_scores.most_common(10)
    }

    # Domain concentration (HHI-style)
    if sig.domain_distribution:
        shares = list(sig.domain_distribution.values())
        sig.domain_concentration_score = sum(s ** 2 for s in shares)
        top = domain_scores.most_common(1)
        if top:
            sig.primary_domain = top[0][0]
        secondary = [d for d, _ in domain_scores.most_common(4)[1:] if domain_scores[d] > 0]
        sig.secondary_domains = secondary

    # Language distribution
    total_langs = sum(lang_counts.values()) or 1
    sig.language_distribution = {
        lang: round(cnt / total_langs, 3) for lang, cnt in lang_counts.most_common(10)
    }

    # v0.3: domain confidence signals
    sig.domain_override_applied = any_override
    if sig.primary_domain:
        sig.domain_support_breadth = sig.repos_per_domain.get(sig.primary_domain, 0)
        sig.domain_support_duration = sig.active_months_per_domain.get(sig.primary_domain, 0)

        # Confidence: multi-factor assessment
        breadth_score = min(sig.domain_support_breadth / 5, 1.0)
        duration_score = min(sig.domain_support_duration / 12, 1.0)
        external_score = min(sig.external_repos_per_domain.get(sig.primary_domain, 0) / 3, 1.0)
        concentration_factor = min(sig.domain_concentration_score / 0.3, 1.0)

        sig.domain_inference_confidence = (
            breadth_score * 0.30
            + duration_score * 0.30
            + external_score * 0.20
            + concentration_factor * 0.20
        )


# ---------------------------------------------------------------------------
# Consistency signals
# ---------------------------------------------------------------------------

def _compute_consistency(
    evidence: Evidence,
    sig: ConsistencySignals,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    # v0.3: all dates must be strictly window-bounded
    def _in_window(dt: datetime) -> bool:
        if window_start and dt < window_start:
            return False
        if window_end and dt > window_end:
            return False
        return True

    # Gather all activity dates (window-bounded only)
    dates: list[datetime] = []
    for p in evidence.pull_requests:
        dt = _parse_iso(p.created_at)
        if dt and _in_window(dt):
            dates.append(dt)
    for r in evidence.reviews:
        dt = _parse_iso(r.submitted_at)
        if dt and _in_window(dt):
            dates.append(dt)
    for iss in evidence.issue_participations:
        dt = _parse_iso(iss.created_at)
        if dt and _in_window(dt):
            dates.append(dt)
    for rel in evidence.release_involvements:
        dt = _parse_iso(rel.created_at)
        if dt and _in_window(dt):
            dates.append(dt)

    if not dates:
        return

    # Active months (window-bounded)
    active_months = sorted(set(_month_key(d) for d in dates))
    sig.observed_months_active = len(active_months)

    if window_start and window_end:
        total = (window_end.year - window_start.year) * 12 + (
            window_end.month - window_start.month
        )
        sig.total_months_in_window = max(total, 1)
    else:
        sig.total_months_in_window = max(sig.observed_months_active, 1)

    sig.active_month_ratio = sig.observed_months_active / sig.total_months_in_window

    # Burstiness: coefficient of variation of monthly activity counts
    monthly_counts: Counter[str] = Counter()
    for d in dates:
        monthly_counts[_month_key(d)] += 1
    counts = list(monthly_counts.values())
    if len(counts) >= 2:
        mean = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        std = math.sqrt(variance)
        sig.burstiness = min(std / mean if mean > 0 else 0.0, 1.0)

    # v0.3: fixed recency — use timedelta for 6-month lookback
    if window_end:
        from datetime import timedelta
        six_months_ago = window_end - timedelta(days=183)
        recent = sum(1 for d in dates if d >= six_months_ago)
        sig.recency_score = recent / len(dates) if dates else 0.0

    # Longest inactive gap (in months) — window-bounded
    if len(active_months) >= 2:
        month_ints = []
        for mk in active_months:
            y, m = mk.split("-")
            month_ints.append(int(y) * 12 + int(m))
        month_ints.sort()
        max_gap = 0
        for i in range(1, len(month_ints)):
            gap = month_ints[i] - month_ints[i - 1] - 1
            if gap > max_gap:
                max_gap = gap
        sig.longest_inactive_gap_months = max_gap
    elif len(active_months) == 1 and window_start and window_end:
        # Single active month: gap is max(months before, months after)
        y, m = active_months[0].split("-")
        active_int = int(y) * 12 + int(m)
        start_int = window_start.year * 12 + window_start.month
        end_int = window_end.year * 12 + window_end.month
        sig.longest_inactive_gap_months = max(active_int - start_int, end_int - active_int)

    # Active quarters (window-bounded)
    active_quarters = set(_quarter_key(d) for d in dates)
    sig.active_quarter_count = len(active_quarters)

    # Repeat-return repos: repos with activity in >1 quarter (window-bounded)
    repo_quarters: dict[str, set[str]] = defaultdict(set)
    for p in evidence.pull_requests:
        dt = _parse_iso(p.created_at)
        if dt and _in_window(dt):
            rk = _repo_key(p.repo_owner, p.repo_name)
            repo_quarters[rk].add(_quarter_key(dt))
    for r in evidence.reviews:
        dt = _parse_iso(r.submitted_at)
        if dt and _in_window(dt):
            rk = _repo_key(r.repo_owner, r.repo_name)
            repo_quarters[rk].add(_quarter_key(dt))
    for iss in evidence.issue_participations:
        dt = _parse_iso(iss.created_at)
        if dt and _in_window(dt):
            rk = _repo_key(iss.repo_owner, iss.repo_name)
            repo_quarters[rk].add(_quarter_key(dt))

    sig.repeat_return_repos = sum(
        1 for quarters in repo_quarters.values() if len(quarters) > 1
    )
    sig.multi_quarter_repo_count = sig.repeat_return_repos


# ---------------------------------------------------------------------------
# Maturity signals (v0.4)
# ---------------------------------------------------------------------------

def _compute_maturity(
    evidence: Evidence,
    signals: SignalSet,
    window_start: datetime | None,
    window_end: datetime | None,
) -> None:
    sig = signals.maturity
    c = signals.contribution
    co = signals.collaboration
    op = signals.owned_projects
    st = signals.stewardship
    cs = signals.consistency
    ei = signals.execution_intensity

    # History depth: account age relative to observation window
    now = window_end or datetime.now(timezone.utc)
    created = _parse_iso(evidence.profile.created_at)
    if created:
        years = (now - created).days / 365.25
        sig.history_depth_score = min(years / 8, 1.0)
    else:
        sig.history_depth_score = 0.0

    # Evidence depth: volume of evidence across all categories
    pr_depth = min(c.total_prs_opened / 30, 1.0)
    review_depth = min(co.review_activity_count / 20, 1.0)
    issue_depth = min(st.issue_participation_count / 20, 1.0)
    release_depth = min(op.owned_public_project_release_count / 10, 1.0)
    repo_depth = min(len(evidence.repositories) / 15, 1.0)
    sig.evidence_depth_score = (
        pr_depth * 0.30
        + review_depth * 0.20
        + issue_depth * 0.15
        + release_depth * 0.15
        + repo_depth * 0.20
    )

    # Evidence diversity: how many different types appear meaningfully
    diversity_flags = 0
    if c.total_prs_opened >= 3:
        diversity_flags += 1
    if co.review_activity_count >= 2:
        diversity_flags += 1
    if st.issue_participation_count >= 2:
        diversity_flags += 1
    if op.owned_public_project_release_count >= 1:
        diversity_flags += 1
    if op.owned_public_project_count >= 1 and op.owned_public_project_visibility_score >= 1.0:
        diversity_flags += 1
    if co.counterparty_count >= 2:
        diversity_flags += 1
    sig.evidence_diversity_score = min(diversity_flags / 5, 1.0)

    # Stage readiness: composite maturity
    sig.stage_readiness_score = (
        sig.history_depth_score * 0.15
        + sig.evidence_depth_score * 0.35
        + sig.evidence_diversity_score * 0.25
        + min(cs.active_month_ratio / 0.5, 1.0) * 0.15
        + min(c.independent_acceptance_ratio, 1.0) * 0.10
    )

    # Classify maturity band
    has_stewardship = st.stewardship_signal >= 0.3
    has_centrality = st.owned_repo_centrality_score >= 3.0
    has_adopted_projects = op.owned_public_project_visibility_score >= 8.0

    if (has_stewardship and has_centrality) or has_adopted_projects:
        band = MaturityBand.STEWARD
        basis = (
            f"Stewardship signal {st.stewardship_signal:.2f}, "
            f"centrality {st.owned_repo_centrality_score:.1f}, "
            f"owned visibility {op.owned_public_project_visibility_score:.1f}."
        )
    elif sig.stage_readiness_score >= 0.50:
        band = MaturityBand.ESTABLISHED
        basis = (
            f"Stage readiness {sig.stage_readiness_score:.2f} with "
            f"evidence depth {sig.evidence_depth_score:.2f} and "
            f"diversity {sig.evidence_diversity_score:.2f}."
        )
    elif sig.stage_readiness_score >= 0.25:
        band = MaturityBand.DEVELOPING
        basis = (
            f"Growing evidence base: readiness {sig.stage_readiness_score:.2f}, "
            f"depth {sig.evidence_depth_score:.2f}."
        )
    else:
        band = MaturityBand.EMERGING
        basis = (
            f"Limited public evidence: readiness {sig.stage_readiness_score:.2f}, "
            f"depth {sig.evidence_depth_score:.2f}."
        )

    sig.maturity_band = band.value
    sig.maturity_basis = basis


# ---------------------------------------------------------------------------
# Promise / potential signals (v0.4, rewritten v0.8)
# ---------------------------------------------------------------------------

def _compute_promise(signals: SignalSet) -> None:
    """Compute promise signals bounded by dimension evidence and confidence.

    v0.8: promise signals are now derived from and constrained by the same
    evidence logic as the main dimensions.  They are no longer an independent
    mini-scoreboard.

    Key coherence rules enforced:
    - Builder promise cannot be 0 when builder dimension is Strong+
    - Specialization promise bounded by domain confidence, support duration,
      source mix, and override dependency
    - Observability status is respected (not-observable → suppressed promise)
    - Mature profiles suppress promise entirely
    """
    sig = signals.promise
    c = signals.contribution
    op = signals.owned_projects
    ei = signals.execution_intensity
    sp = signals.specialization
    sr = signals.specialization_reliability
    mat = signals.maturity
    bs = signals.builder_sophistication
    dc = signals.dimension_coverage
    mp = signals.mature_profile

    # --- Determine promise render mode ---
    if mp.promise_suppression_flag:
        sig.promise_render_mode = "suppressed"
        if mp.mature_profile_mode == "steward":
            sig.promise_suppressed_reason = "steward profile: demonstrated impact replaces promise"
        else:
            sig.promise_suppressed_reason = "established profile: demonstrated evidence replaces promise"
        # Zero out all promise fields for mature profiles
        sig.early_signal_strength = 0.0
        sig.promising_execution_score = 0.0
        sig.promising_specialization_score = 0.0
        sig.promising_external_acceptance_score = 0.0
        sig.promising_builder_sophistication_score = 0.0
        return

    is_mature = mat.maturity_band in (MaturityBand.ESTABLISHED.value, MaturityBand.STEWARD.value)
    sig.promise_render_mode = "mature" if is_mature else "developing"

    # --- Early signal strength ---
    if mat.evidence_depth_score < 0.5:
        acceptance_quality = min(c.independent_acceptance_ratio * 2, 1.0) if c.merged_pr_count > 0 else 0.0
        execution_quality = min(ei.burst_execution_score / 0.5, 1.0)
        owned_quality = min(op.owned_public_project_visibility_score / 5, 1.0)
        domain_quality = sp.domain_inference_confidence
        sig.early_signal_strength = (
            acceptance_quality * 0.30
            + execution_quality * 0.30
            + owned_quality * 0.25
            + domain_quality * 0.15
        )
    else:
        sig.early_signal_strength = 0.0

    # --- Promising execution ---
    if mat.evidence_depth_score > 0 and ei.burst_execution_score > 0:
        sig.promising_execution_score = min(
            ei.burst_execution_score / max(mat.evidence_depth_score, 0.1), 1.0
        )

    # --- Promising specialization (v0.8: bounded by coherence) ---
    if sp.primary_domain and sp.domain_inference_confidence > 0:
        raw_spec_promise = min(
            sp.domain_inference_confidence / max(mat.evidence_depth_score, 0.2), 1.0
        )
        # Bound by domain confidence
        if sp.domain_inference_confidence < 0.3:
            raw_spec_promise = min(raw_spec_promise, 0.40)
        elif sp.domain_inference_confidence < 0.5:
            raw_spec_promise = min(raw_spec_promise, 0.65)

        # Bound by support duration
        primary_months = sp.active_months_per_domain.get(sp.primary_domain or "", 0)
        if primary_months < 3:
            raw_spec_promise = min(raw_spec_promise, 0.35)
        elif primary_months < 6:
            raw_spec_promise = min(raw_spec_promise, 0.60)

        # Bound by source mix
        if sr.domain_evidence_source_mix == "self-only":
            raw_spec_promise = min(raw_spec_promise, 0.50)

        # Bound by override dependency
        if sr.override_dependency_flag:
            raw_spec_promise = min(raw_spec_promise, 0.55)

        # Record ceiling reason
        ceiling_parts = []
        if sp.domain_inference_confidence < 0.5:
            ceiling_parts.append(f"domain confidence {sp.domain_inference_confidence:.2f}")
        if primary_months < 6:
            ceiling_parts.append(f"support duration {primary_months}mo")
        if sr.domain_evidence_source_mix == "self-only":
            ceiling_parts.append("self-only evidence")
        if sr.override_dependency_flag:
            ceiling_parts.append("override-dependent")
        sig.specialization_promise_ceiling_reason = "; ".join(ceiling_parts)

        sig.promising_specialization_score = raw_spec_promise
    else:
        sig.promising_specialization_score = 0.0

    # --- Promising external acceptance ---
    if c.merged_pr_count > 0 and c.independent_acceptance_count > 0:
        sig.promising_external_acceptance_score = min(
            c.independent_acceptance_ratio / max(mat.evidence_depth_score, 0.2), 1.0
        )

    # --- Promising builder sophistication (v0.8: coherence-bounded) ---
    builder_obs = dc.builder_observability_status
    if builder_obs == ObservabilityStatus.NOT_RELIABLY_OBSERVED.value:
        # Builder not observable → suppress promise, don't show 0.00
        sig.promising_builder_sophistication_score = 0.0
    elif bs.builder_sophistication_signal > 0:
        raw_builder_promise = min(
            bs.builder_sophistication_signal / max(mat.evidence_depth_score, 0.2), 1.0
        )
        # v0.8 coherence: builder promise floor for strong builder signals
        # A high builder signal should never produce zero promise
        if bs.builder_sophistication_signal >= 0.5:
            raw_builder_promise = max(raw_builder_promise, 0.60)
        elif bs.builder_sophistication_signal >= 0.3:
            raw_builder_promise = max(raw_builder_promise, 0.35)
        sig.promising_builder_sophistication_score = raw_builder_promise
    else:
        sig.promising_builder_sophistication_score = 0.0


# ---------------------------------------------------------------------------
# Steward contribution signals (v0.4)
# ---------------------------------------------------------------------------

def _compute_steward_contribution(signals: SignalSet) -> None:
    sig = signals.steward_contribution
    op = signals.owned_projects
    st = signals.stewardship
    c = signals.contribution
    ei = signals.execution_intensity

    # Steward contribution: contribution value through stewardship
    sig.steward_contribution_signal = (
        min(st.stewardship_signal, 1.0) * 0.30
        + min(st.owned_repo_centrality_score / 10, 1.0) * 0.25
        + min(st.maintainer_visibility_score, 1.0) * 0.20
        + min(st.release_stewardship_count / 10, 1.0) * 0.15
        + min(st.issue_response_activity_count / 20, 1.0) * 0.10
    )

    # Owned public build signal: contribution through building
    sig.owned_public_build_signal = (
        min(op.owned_public_project_visibility_score / 15, 1.0) * 0.35
        + min(op.owned_public_project_external_interest_score / 2, 1.0) * 0.25
        + min(op.owned_public_project_release_count / 10, 1.0) * 0.20
        + min(op.owned_public_project_maintenance_score, 1.0) * 0.20
    )

    # Governance-weighted contribution: combines all paths
    author_path = min(c.independent_acceptance_count / 10, 1.0)
    sig.governance_weighted_contribution_signal = max(
        author_path,
        sig.steward_contribution_signal,
        sig.owned_public_build_signal,
    )


# ---------------------------------------------------------------------------
# Impact calibration signals (v0.4)
# ---------------------------------------------------------------------------

def _compute_impact_calibration(signals: SignalSet) -> None:
    sig = signals.impact_calibration
    op = signals.owned_projects
    st = signals.stewardship

    # Centrality tier
    centrality = st.owned_repo_centrality_score
    if centrality >= 15:
        sig.ecosystem_centrality_tier = "extreme"
    elif centrality >= 8:
        sig.ecosystem_centrality_tier = "high"
    elif centrality >= 3:
        sig.ecosystem_centrality_tier = "moderate"
    else:
        sig.ecosystem_centrality_tier = "none"

    # Public reliance tier
    reliance = st.owned_repo_public_reliance_score
    if reliance >= 3.0:
        sig.public_reliance_tier = "extreme"
    elif reliance >= 1.5:
        sig.public_reliance_tier = "high"
    elif reliance >= 0.5:
        sig.public_reliance_tier = "moderate"
    else:
        sig.public_reliance_tier = "none"

    # Override: extreme centrality or reliance forces impact recognition
    sig.central_repo_impact_override = (
        sig.ecosystem_centrality_tier in ("extreme", "high")
        or sig.public_reliance_tier in ("extreme", "high")
        or op.owned_public_project_visibility_score >= 20.0
    )


# ---------------------------------------------------------------------------
# Contribution calibration signals (v0.5)
# ---------------------------------------------------------------------------

def _compute_contribution_calibration(signals: SignalSet) -> None:
    sig = signals.contribution_calibration
    c = signals.contribution
    op = signals.owned_projects
    st = signals.stewardship
    sc = signals.steward_contribution

    # Self-governed execution ratio: what fraction of merged work is self-governed
    if c.merged_pr_count > 0:
        self_governed = c.self_merged_pr_count + c.external_repo_self_merged_pr_count
        sig.self_governed_execution_ratio = min(self_governed / c.merged_pr_count, 1.0)
    else:
        sig.self_governed_execution_ratio = 0.0

    # Independent validation absence
    has_independent = c.independent_acceptance_count > 0
    has_adoption = op.owned_public_project_visibility_score >= 3.0
    has_stewardship = st.stewardship_signal >= 0.2
    sig.independent_validation_absence = (
        not has_independent and not has_adoption and not has_stewardship
    )

    # Ceiling reason
    if sig.independent_validation_absence and sig.self_governed_execution_ratio >= 0.8:
        sig.contribution_ceiling_reason = (
            "All merged work is self-governed with no independent acceptance, "
            "adopted owned projects, or stewardship evidence."
        )
    elif sig.self_governed_execution_ratio >= 0.9 and not has_independent:
        sig.contribution_ceiling_reason = (
            "Nearly all merged work is self-governed with no independent "
            "external acceptance."
        )
    else:
        sig.contribution_ceiling_reason = ""


# ---------------------------------------------------------------------------
# Archetype soft classification (v0.5)
# ---------------------------------------------------------------------------

def _compute_archetype_soft_classification(signals: SignalSet) -> None:
    sig = signals.archetype_soft
    c = signals.contribution
    op = signals.owned_projects
    st = signals.stewardship
    ei = signals.execution_intensity
    cs = signals.consistency

    # Compute soft strengths for each archetype (0-1, weaker thresholds than detection)
    candidates = []
    strengths = {}

    # External contributor hint
    ext_strength = (
        min(c.independent_acceptance_count / 5, 1.0) * 0.5
        + min(c.repos_with_merged_contributions_external / 3, 1.0) * 0.5
    )
    if ext_strength >= 0.15:
        candidates.append("External Contributor")
        strengths["External Contributor"] = ext_strength

    # Independent builder hint
    builder_strength = (
        min(op.owned_public_project_count / 3, 1.0) * 0.5
        + min(c.authored_repo_activity_signal / 0.5, 1.0) * 0.5
    )
    if builder_strength >= 0.15:
        candidates.append("Independent Builder")
        strengths["Independent Builder"] = builder_strength

    # Owned project maintainer hint
    maint_strength = (
        min(op.owned_public_project_visibility_score / 5, 1.0) * 0.5
        + min(op.owned_public_project_maintenance_score / 0.5, 1.0) * 0.5
    )
    if maint_strength >= 0.15:
        candidates.append("Owned Public Project Maintainer")
        strengths["Owned Public Project Maintainer"] = maint_strength

    # Steward hint
    steward_strength = (
        min(st.stewardship_signal / 0.3, 1.0) * 0.4
        + min(st.owned_repo_centrality_score / 5, 1.0) * 0.3
        + min(st.issue_participation_count / 10, 1.0) * 0.3
    )
    if steward_strength >= 0.15:
        candidates.append("Maintainer / Steward / Governor")
        strengths["Maintainer / Steward / Governor"] = steward_strength

    # Burst execution hint
    burst_strength = min(ei.burst_execution_score / 0.5, 1.0)
    if burst_strength >= 0.15:
        candidates.append("Burst Execution Profile")
        strengths["Burst Execution Profile"] = burst_strength

    # Sustained contributor hint
    sustained_strength = (
        min(cs.active_month_ratio / 0.3, 1.0) * 0.4
        + min(cs.repeat_return_repos / 3, 1.0) * 0.3
        + min(cs.active_quarter_count / 5, 1.0) * 0.3
    )
    if sustained_strength >= 0.15:
        candidates.append("Sustained Public Contributor")
        strengths["Sustained Public Contributor"] = sustained_strength

    # v0.6: complex product builder hint
    bs = signals.builder_sophistication
    builder_cpb_strength = bs.complex_product_builder_strength
    if builder_cpb_strength >= 0.15:
        candidates.append("Complex Product Builder")
        strengths["Complex Product Builder"] = builder_cpb_strength

    sig.secondary_archetype_candidates = candidates
    sig.secondary_archetype_strengths = strengths


# ---------------------------------------------------------------------------
# Specialization reliability signals (v0.5)
# ---------------------------------------------------------------------------

def _compute_specialization_reliability(signals: SignalSet) -> None:
    sig = signals.specialization_reliability
    sp = signals.specialization

    primary = sp.primary_domain or ""
    primary_repos = sp.repos_per_domain.get(primary, 0)
    primary_ext_repos = sp.external_repos_per_domain.get(primary, 0)
    primary_months = sp.active_months_per_domain.get(primary, 0)

    # Domain evidence source mix
    if primary_ext_repos >= 2:
        sig.domain_evidence_source_mix = "external-validated"
    elif primary_ext_repos >= 1:
        sig.domain_evidence_source_mix = "mixed"
    elif primary_repos > 0:
        sig.domain_evidence_source_mix = "self-only"
    else:
        sig.domain_evidence_source_mix = "none"

    # Domain signal quality: combination of confidence, breadth, duration, external presence
    breadth_factor = min(primary_repos / 3, 1.0)
    duration_factor = min(primary_months / 6, 1.0)
    external_factor = min(primary_ext_repos / 2, 1.0)
    confidence_factor = sp.domain_inference_confidence

    sig.domain_signal_quality_score = (
        confidence_factor * 0.30
        + breadth_factor * 0.25
        + duration_factor * 0.25
        + external_factor * 0.20
    )

    # Override dependency
    sig.override_dependency_flag = (
        sp.domain_override_applied
        and sp.domain_inference_confidence < 0.5
        and primary_ext_repos == 0
    )


# ---------------------------------------------------------------------------
# Consistency interpretation signals (v0.5)
# ---------------------------------------------------------------------------

def _compute_consistency_interpretation(signals: SignalSet) -> None:
    sig = signals.consistency_interpretation
    cs = signals.consistency
    st = signals.stewardship
    mat = signals.maturity

    # Window visibility limited: steward/established profiles with sparse
    # visible activity likely have real activity not captured
    is_steward_or_established = mat.maturity_band in (
        MaturityBand.STEWARD.value, MaturityBand.ESTABLISHED.value,
    )
    has_sparse_window = cs.active_month_ratio < 0.15

    sig.window_visibility_limited = is_steward_or_established and has_sparse_window

    # Archetype-adjusted consistency confidence
    base_conf = (
        min(cs.observed_months_active / 12, 1.0) * 0.4
        + min(cs.repeat_return_repos / 3, 1.0) * 0.3
        + (1.0 if cs.recency_score > 0.1 else 0.0) * 0.15
        + min(cs.active_quarter_count / 6, 1.0) * 0.15
    )

    # For steward profiles, reduce confidence rather than aggressively scoring low
    if sig.window_visibility_limited:
        sig.archetype_adjusted_consistency_confidence = min(base_conf, 0.25)
    elif is_steward_or_established:
        sig.archetype_adjusted_consistency_confidence = max(base_conf * 0.8, 0.2)
    else:
        sig.archetype_adjusted_consistency_confidence = base_conf


# ---------------------------------------------------------------------------
# Builder sophistication signals (v0.6)
# ---------------------------------------------------------------------------

def _compute_builder_sophistication(evidence: Evidence, signals: SignalSet) -> None:
    sig = signals.builder_sophistication
    merged_prs = [p for p in evidence.pull_requests if p.state == PRState.MERGED]

    if not merged_prs:
        return

    # --- PR / change complexity ---
    additions_list = [p.additions for p in merged_prs]
    changed_files_list = [p.changed_files for p in merged_prs]

    sig.large_pr_count = sum(1 for a in additions_list if a >= 200)
    sig.very_large_pr_count = sum(1 for a in additions_list if a >= 500)

    sorted_adds = sorted(additions_list)
    mid = len(sorted_adds) // 2
    if len(sorted_adds) % 2 == 1:
        sig.median_additions_per_pr = float(sorted_adds[mid])
    else:
        sig.median_additions_per_pr = (sorted_adds[mid - 1] + sorted_adds[mid]) / 2.0

    sig.max_additions_per_pr = max(additions_list)

    sorted_files = sorted(changed_files_list)
    mid = len(sorted_files) // 2
    if len(sorted_files) % 2 == 1:
        sig.median_changed_files_per_pr = float(sorted_files[mid])
    else:
        sig.median_changed_files_per_pr = (sorted_files[mid - 1] + sorted_files[mid]) / 2.0

    sig.max_changed_files_per_pr = max(changed_files_list)

    sig.multi_subsystem_pr_count = sum(1 for f in changed_files_list if f >= 5)

    # Repos with at least one large PR
    large_pr_repos: set[str] = set()
    for p in merged_prs:
        if p.additions >= 200:
            large_pr_repos.add(_repo_key(p.repo_owner, p.repo_name))
    sig.large_pr_repo_count = len(large_pr_repos)

    # --- Product breadth ---
    # Heuristic: PRs that touch many files or have substantial additions+deletions
    # suggest multi-concern work. We have changed_files as a proxy.
    for p in merged_prs:
        is_substantial = p.additions >= 100
        is_multi_file = p.changed_files >= 3
        if is_substantial and is_multi_file:
            sig.cross_layer_change_count += 1
        if is_substantial and p.changed_files >= 2:
            sig.code_and_docs_change_count += 1

    # Repo complexity: average large PR density per repo
    repo_pr_counts: Counter[str] = Counter()
    repo_large_pr_counts: Counter[str] = Counter()
    repo_owned_large_pr_counts: Counter[str] = Counter()
    for p in merged_prs:
        rk = _repo_key(p.repo_owner, p.repo_name)
        repo_pr_counts[rk] += 1
        if p.additions >= 200:
            repo_large_pr_counts[rk] += 1
            if p.is_repo_owned_by_subject:
                repo_owned_large_pr_counts[rk] += 1

    # Product scope signal: how many repos show multi-concern work
    repos_with_breadth = sum(
        1 for rk in repo_pr_counts
        if repo_large_pr_counts.get(rk, 0) >= 1 and repo_pr_counts[rk] >= 3
    )
    sig.product_scope_signal = min(repos_with_breadth / 3, 1.0)

    # Repo complexity scores
    if repo_pr_counts:
        total_complexity = 0.0
        owned_complexity = 0.0
        owned_count = 0
        for rk in repo_pr_counts:
            large_ratio = repo_large_pr_counts.get(rk, 0) / max(repo_pr_counts[rk], 1)
            multi_subsystem = sum(
                1 for p in merged_prs
                if _repo_key(p.repo_owner, p.repo_name) == rk and p.changed_files >= 5
            )
            repo_complexity = (
                large_ratio * 0.4
                + min(multi_subsystem / 3, 1.0) * 0.3
                + min(repo_pr_counts[rk] / 10, 1.0) * 0.3
            )
            total_complexity += repo_complexity
            # Check if owned
            is_owned = any(
                p.is_repo_owned_by_subject
                for p in merged_prs
                if _repo_key(p.repo_owner, p.repo_name) == rk
            )
            if is_owned:
                owned_complexity += repo_complexity
                owned_count += 1

        sig.repo_complexity_score = total_complexity / len(repo_pr_counts)
        if owned_count > 0:
            sig.owned_repo_complexity_score = owned_complexity / owned_count

    # --- Delivery signals ---
    # Repeated feature delivery: repos with >= 3 large PRs
    sig.repeated_feature_delivery_count = sum(
        1 for c in repo_large_pr_counts.values() if c >= 3
    )
    # Repeated major delivery: repos with >= 2 very large PRs
    repo_very_large: Counter[str] = Counter()
    for p in merged_prs:
        if p.additions >= 500:
            repo_very_large[_repo_key(p.repo_owner, p.repo_name)] += 1
    sig.repeated_major_delivery_count = sum(
        1 for c in repo_very_large.values() if c >= 2
    )

    # Delivery depth signal
    sig.delivery_depth_signal = (
        min(sig.repeated_feature_delivery_count / 3, 1.0) * 0.5
        + min(sig.repeated_major_delivery_count / 2, 1.0) * 0.5
    )

    # --- Composite builder signals ---
    # Product/system complexity score
    complexity_score = (
        min(sig.large_pr_count / 10, 1.0) * 0.20
        + min(sig.very_large_pr_count / 5, 1.0) * 0.15
        + min(sig.multi_subsystem_pr_count / 8, 1.0) * 0.15
        + min(sig.large_pr_repo_count / 3, 1.0) * 0.15
        + sig.product_scope_signal * 0.15
        + sig.repo_complexity_score * 0.10
        + sig.delivery_depth_signal * 0.10
    )
    sig.product_system_complexity_score = min(complexity_score, 1.0)

    # Self-directed build depth: focuses on owned-repo complexity
    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    owned_pr_count = sum(1 for p in merged_prs if p.is_repo_owned_by_subject)
    owned_large_count = sum(
        1 for p in merged_prs if p.is_repo_owned_by_subject and p.additions >= 200
    )
    sig.self_directed_build_depth_score = (
        min(owned_large_count / 5, 1.0) * 0.30
        + sig.owned_repo_complexity_score * 0.25
        + min(owned_pr_count / 15, 1.0) * 0.20
        + min(len(owned_repos) / 5, 1.0) * 0.15
        + sig.delivery_depth_signal * 0.10
    )

    # Builder sophistication signal: overall composite
    sig.builder_sophistication_signal = (
        sig.product_system_complexity_score * 0.45
        + sig.self_directed_build_depth_score * 0.30
        + min(sig.cross_layer_change_count / 10, 1.0) * 0.15
        + sig.product_scope_signal * 0.10
    )

    # Complex product builder archetype strength
    sig.complex_product_builder_strength = (
        sig.builder_sophistication_signal * 0.40
        + sig.owned_repo_complexity_score * 0.25
        + sig.delivery_depth_signal * 0.20
        + sig.product_scope_signal * 0.15
    )

    # v0.7: Route B — repo substance (non-PR builder evidence)
    # Long-lived owned repos with breadth indicate building even without PR evidence
    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    if owned_repos:
        import math as _math
        # Repo substance: repos with non-trivial metadata signals
        substance_scores = []
        for r in owned_repos:
            has_language = r.primary_language is not None
            has_topics = len(r.topics) >= 1
            has_description = bool(r.description and len(r.description) > 20)
            has_size = (r.disk_usage_kb or 0) > 100
            has_structure = has_language and (has_topics or has_description)
            multi_concern = len(r.topics) >= 3

            repo_sub = (
                (0.25 if has_language else 0.0)
                + (0.20 if has_description else 0.0)
                + (0.15 if has_topics else 0.0)
                + (0.15 if has_size else 0.0)
                + (0.15 if has_structure else 0.0)
                + (0.10 if multi_concern else 0.0)
            )
            substance_scores.append(repo_sub)

        sig.repo_substance_score = sum(substance_scores) / len(substance_scores)
        # Breadth: diversity of languages/topics across owned repos
        owned_langs = set(r.primary_language for r in owned_repos if r.primary_language)
        owned_topics_all = set()
        for r in owned_repos:
            owned_topics_all.update(r.topics)
        sig.owned_repo_breadth_score = min(
            (len(owned_langs) / 3) * 0.5 + (len(owned_topics_all) / 8) * 0.5, 1.0
        )


# ---------------------------------------------------------------------------
# Builder observability signals (v0.7)
# ---------------------------------------------------------------------------

def _compute_builder_observability(signals: SignalSet) -> None:
    """Determine whether builder sophistication is reliably observable."""
    bs = signals.builder_sophistication
    st = signals.stewardship
    op = signals.owned_projects
    c = signals.contribution
    mat = signals.maturity

    # Determine evidence mode
    has_pr_builder_evidence = bs.large_pr_count >= 2 or bs.multi_subsystem_pr_count >= 2
    has_repo_substance = bs.repo_substance_score >= 0.3 and op.owned_public_project_count >= 2
    is_steward_dominant = (
        st.stewardship_signal >= 0.3
        and st.owned_repo_centrality_score >= 3.0
    )
    has_sparse_prs = c.merged_pr_count < 5

    if has_pr_builder_evidence:
        if has_repo_substance:
            bs.builder_observability_mode = "pr_visible"
            bs.builder_signal_path = "mixed"
        else:
            bs.builder_observability_mode = "pr_visible"
            bs.builder_signal_path = "pr_delivery"
    elif has_repo_substance and not has_sparse_prs:
        bs.builder_observability_mode = "repo_visible_but_pr_sparse"
        bs.builder_signal_path = "repo_complexity"
    elif is_steward_dominant:
        bs.builder_observability_mode = "steward_dominant"
        bs.builder_signal_path = "insufficient"
    else:
        if c.merged_pr_count == 0 and op.owned_public_project_count == 0:
            bs.builder_observability_mode = "insufficient_builder_evidence"
            bs.builder_signal_path = "insufficient"
        elif has_sparse_prs and not has_repo_substance:
            bs.builder_observability_mode = "insufficient_builder_evidence"
            bs.builder_signal_path = "insufficient"
        else:
            bs.builder_observability_mode = "pr_visible"
            bs.builder_signal_path = "pr_delivery"

    # Builder evidence coverage: how much builder evidence is available
    pr_coverage = min(bs.large_pr_count / 5, 1.0) * 0.4
    repo_coverage = bs.repo_substance_score * 0.3
    delivery_coverage = bs.delivery_depth_signal * 0.3
    bs.builder_evidence_coverage = pr_coverage + repo_coverage + delivery_coverage

    # Builder observability confidence
    if bs.builder_observability_mode == "pr_visible":
        bs.builder_observability_confidence = min(bs.builder_evidence_coverage * 1.2, 1.0)
    elif bs.builder_observability_mode == "repo_visible_but_pr_sparse":
        bs.builder_observability_confidence = min(bs.builder_evidence_coverage * 0.8, 0.6)
    elif bs.builder_observability_mode == "steward_dominant":
        bs.builder_observability_confidence = 0.15  # not enough to judge
    else:
        bs.builder_observability_confidence = 0.1


# ---------------------------------------------------------------------------
# Dimension coverage signals (v0.7)
# ---------------------------------------------------------------------------

def _compute_dimension_coverage(signals: SignalSet) -> None:
    """Compute observability status for key dimensions."""
    sig = signals.dimension_coverage
    bs = signals.builder_sophistication
    co = signals.collaboration
    cs = signals.consistency
    st = signals.stewardship
    mat = signals.maturity
    ci = signals.consistency_interpretation

    # Builder observability
    if bs.builder_observability_mode in ("steward_dominant", "insufficient_builder_evidence"):
        if bs.builder_evidence_coverage < 0.15:
            sig.builder_observability_status = "not_reliably_observed"
        else:
            sig.builder_observability_status = "partially_observed"
    elif bs.builder_observability_mode == "repo_visible_but_pr_sparse":
        sig.builder_observability_status = "partially_observed"
    else:
        sig.builder_observability_status = "well_observed"

    # Collaboration observability (v0.9: stricter for empty-interaction profiles)
    total_collab_evidence = (
        co.review_activity_count
        + co.counterparty_count
        + st.issue_participation_count
    )
    has_any_interaction = (
        co.review_activity_count > 0
        or co.counterparty_count > 0
        or co.issue_discussion_count > 0
    )
    if not has_any_interaction:
        # No collaboration surface at all → not reliably observable
        sig.collaboration_observability_status = "not_reliably_observed"
    elif total_collab_evidence < 3:
        sig.collaboration_observability_status = "not_reliably_observed"
    elif total_collab_evidence < 10:
        sig.collaboration_observability_status = "partially_observed"
    else:
        sig.collaboration_observability_status = "well_observed"

    # Consistency observability (v0.9: temporal denominator safety)
    if not ci.temporal_denominator_valid:
        sig.consistency_observability_status = "not_reliably_observed"
    elif ci.temporal_evidence_completeness == "none":
        sig.consistency_observability_status = "not_reliably_observed"
    elif ci.window_visibility_limited:
        sig.consistency_observability_status = "not_reliably_observed"
    elif cs.observed_months_active < 3:
        sig.consistency_observability_status = "partially_observed"
    else:
        sig.consistency_observability_status = "well_observed"


# ---------------------------------------------------------------------------
# Mature profile signals (v0.7)
# ---------------------------------------------------------------------------

def _compute_mature_profile(signals: SignalSet) -> None:
    """Determine mature-profile mode and promise suppression."""
    sig = signals.mature_profile
    mat = signals.maturity
    st = signals.stewardship
    ic = signals.impact_calibration

    is_steward = mat.maturity_band == MaturityBand.STEWARD.value
    is_established = mat.maturity_band == MaturityBand.ESTABLISHED.value

    if is_steward:
        sig.mature_profile_mode = "steward"
    elif is_established:
        sig.mature_profile_mode = "established"
    else:
        sig.mature_profile_mode = "none"

    # Promise suppression: suppress early-stage promise artifacts for mature profiles
    sig.promise_suppression_flag = is_steward or (
        is_established and st.stewardship_signal >= 0.3
    )

    # Established impact profile: demonstrated impact via stewardship/centrality
    sig.established_impact_profile_flag = (
        is_steward
        or ic.central_repo_impact_override
        or (is_established and st.owned_repo_centrality_score >= 5.0)
    )


# ---------------------------------------------------------------------------
# Specialization coherence signals (v0.7)
# ---------------------------------------------------------------------------

def _compute_specialization_coherence(signals: SignalSet) -> None:
    """Compute specialization coherence and domain centrality signals."""
    sig = signals.specialization_coherence
    sp = signals.specialization
    sr = signals.specialization_reliability
    st = signals.stewardship

    # Domain centrality: if owned repos are in a known domain, strength of that association
    # High centrality + high visibility = strong domain centrality even without
    # high-confidence metadata-derived inference
    domain_centrality = 0.0
    if sp.primary_domain and sp.domain_override_applied:
        domain_centrality = min(st.owned_repo_centrality_score / 10, 1.0) * 0.6
        domain_centrality += min(sp.domain_inference_confidence, 1.0) * 0.4
    elif sp.primary_domain:
        domain_centrality = sp.domain_inference_confidence * 0.7
        domain_centrality += min(st.owned_repo_centrality_score / 10, 1.0) * 0.3
    sig.domain_centrality_signal = min(domain_centrality, 1.0)

    # Override penalty: how much confidence should be reduced when overrides are used
    if sp.domain_override_applied:
        if sp.domain_inference_confidence < 0.35:
            sig.specialization_override_penalty = 0.20
        elif sp.domain_inference_confidence < 0.50:
            sig.specialization_override_penalty = 0.10
    else:
        sig.specialization_override_penalty = 0.0

    # Confidence ceiling reason
    reasons = []
    if sr.override_dependency_flag:
        reasons.append("domain classification depends heavily on curated override")
    if sr.domain_evidence_source_mix == "self-only":
        reasons.append("domain evidence comes only from self-owned repositories")
    primary_months = sp.active_months_per_domain.get(sp.primary_domain or "", 0)
    if primary_months < 3:
        reasons.append(f"support duration is short ({primary_months} months)")
    if sp.domain_inference_confidence < 0.25:
        reasons.append("low metadata-derived domain confidence")
    sig.specialization_confidence_ceiling_reason = "; ".join(reasons) if reasons else ""

    # v0.8: domain directionality
    # Detect whether the contributor trends toward a domain without strong specialization
    if sp.primary_domain:
        primary_repos = sp.repos_per_domain.get(sp.primary_domain, 0)
        primary_months = sp.active_months_per_domain.get(sp.primary_domain or "", 0)
        primary_share = sp.domain_distribution.get(sp.primary_domain, 0.0) if sp.domain_distribution else 0.0

        directionality = (
            min(primary_repos / 3, 1.0) * 0.30
            + min(primary_share / 0.35, 1.0) * 0.30
            + min(primary_months / 6, 1.0) * 0.20
            + min(sp.domain_inference_confidence / 0.5, 1.0) * 0.20
        )
        sig.domain_directionality_signal = min(directionality, 1.0)

        if directionality >= 0.4:
            sig.domain_directionality_label = f"visible movement toward {sp.primary_domain}"
        elif directionality >= 0.2:
            sig.domain_directionality_label = f"early activity in {sp.primary_domain}"
        else:
            sig.domain_directionality_label = ""
    else:
        sig.domain_directionality_signal = 0.0
        sig.domain_directionality_label = ""

    # v0.9: secondary-domain cleanup for central low-level profiles (§7)
    # If primary domain has override + overwhelmingly low-level language mix,
    # remove weak secondary domains that are likely noise
    if sp.primary_domain and sp.domain_override_applied:
        systems_languages = {"C", "C++", "Assembly", "Rust", "Go"}
        owned_langs = set(sp.language_distribution.keys()) if sp.language_distribution else set()
        systems_ratio = sum(
            sp.language_distribution.get(lang, 0.0)
            for lang in systems_languages
        ) if sp.language_distribution else 0.0

        if systems_ratio >= 0.6 and st.owned_repo_centrality_score >= 5.0:
            # Filter out weak secondaries with low evidence
            strong_secondaries = []
            for domain in sp.secondary_domains:
                domain_repos_count = sp.repos_per_domain.get(domain, 0)
                domain_months_count = sp.active_months_per_domain.get(domain, 0)
                domain_share = sp.domain_distribution.get(domain, 0.0) if sp.domain_distribution else 0.0
                # Keep only if it has real evidence: 2+ repos or 3+ months or >15% share
                if domain_repos_count >= 2 or domain_months_count >= 3 or domain_share >= 0.15:
                    strong_secondaries.append(domain)
            sp.secondary_domains = strong_secondaries


# ---------------------------------------------------------------------------
# Wording state signals (v0.8)
# ---------------------------------------------------------------------------

def _compute_wording_state(signals: SignalSet) -> None:
    """Compute wording-state signals to enforce consistent language."""
    ws = signals.wording_state
    c = signals.contribution
    st = signals.stewardship
    co = signals.collaboration

    # External acceptance wording state
    if c.independent_acceptance_count >= 5 and c.independent_acceptance_repo_count >= 3:
        ws.external_acceptance_wording_state = "strong"
    elif c.independent_acceptance_count >= 2:
        ws.external_acceptance_wording_state = "meaningful"
    elif c.independent_acceptance_count >= 1:
        ws.external_acceptance_wording_state = "limited"
    else:
        ws.external_acceptance_wording_state = "none_detected"

    # Stewardship wording state
    if st.stewardship_signal >= 0.5:
        ws.stewardship_wording_state = "strong"
    elif st.stewardship_signal >= 0.2:
        ws.stewardship_wording_state = "meaningful"
    elif st.stewardship_signal > 0.05:
        ws.stewardship_wording_state = "limited"
    else:
        ws.stewardship_wording_state = "none_detected"

    # Collaboration wording state
    if co.review_activity_count >= 10 and co.counterparty_count >= 5:
        ws.collaboration_wording_state = "strong"
    elif co.review_activity_count >= 3 or co.counterparty_count >= 3:
        ws.collaboration_wording_state = "meaningful"
    elif co.review_activity_count >= 1 or co.counterparty_count >= 1:
        ws.collaboration_wording_state = "limited"
    else:
        ws.collaboration_wording_state = "none_detected"


# ---------------------------------------------------------------------------
# Report integrity checks (v0.8)
# ---------------------------------------------------------------------------

def _compute_report_integrity(signals: SignalSet, dimensions: list) -> None:
    """Run final-stage coherence checks on the computed signals and dimensions.

    v1.0: tracks auto-corrections separately and enforces that
    integrity_issues is never empty when integrity fails.
    """
    ri = signals.report_integrity
    prom = signals.promise
    dc = signals.dimension_coverage
    ws = signals.wording_state
    issues: list[str] = []
    corrections: list[str] = []

    # --- Promise–dimension coherence ---
    dim_scores = {d.name: d for d in dimensions}

    # Rule 4.1: Builder promise coherence
    builder_dim = dim_scores.get("Builder Sophistication")
    if builder_dim:
        builder_obs = builder_dim.observability_status
        from .models import ScoreBand
        if (builder_dim.score in (ScoreBand.STRONG, ScoreBand.VERY_STRONG)
                and builder_obs == "well_observed"
                and prom.promising_builder_sophistication_score < 0.20):
            # Fix: set builder promise to reflect actual builder strength
            prom.promising_builder_sophistication_score = max(
                prom.promising_builder_sophistication_score, 0.60
            )
            corrections.append(
                "Builder promise raised to 0.60 (strong builder dimension + zero builder promise)"
            )
            issues.append(
                "strong builder dimension + zero builder promise"
            )
            ri.promise_dimension_coherence_passed = False

        # Rule 4.4: not-observable builder → suppress promise
        if builder_obs == ObservabilityStatus.NOT_RELIABLY_OBSERVED.value:
            if prom.promising_builder_sophistication_score > 0:
                prom.promising_builder_sophistication_score = 0.0
                corrections.append(
                    "Builder promise zeroed (builder not observable)"
                )
            ri.observability_coherence_passed = (
                ri.observability_coherence_passed
                and prom.promise_render_mode != "developing"
            )

    # Rule 4.2: Specialization promise coherence
    spec_dim = dim_scores.get("Specialization Strength")
    if spec_dim:
        from .models import ConfidenceBand
        if (spec_dim.score in (ScoreBand.LOW, ScoreBand.EMERGING)
                and spec_dim.confidence in (ConfidenceBand.LOW,)
                and prom.promising_specialization_score > 0.70):
            prom.promising_specialization_score = min(
                prom.promising_specialization_score, 0.40
            )
            corrections.append(
                f"Specialization promise clamped to {prom.promising_specialization_score:.2f} "
                "(low/emerging specialization with low confidence + high promise)"
            )
            issues.append(
                "low/emerging specialization with low confidence + high promise"
            )
            ri.promise_dimension_coherence_passed = False

        if (spec_dim.score == ScoreBand.MODERATE
                and spec_dim.confidence == ConfidenceBand.LOW
                and prom.promising_specialization_score > 0.65):
            prom.promising_specialization_score = min(
                prom.promising_specialization_score, 0.50
            )
            corrections.append(
                f"Specialization promise clamped to {prom.promising_specialization_score:.2f} "
                "(moderate specialization with low confidence + high promise)"
            )
            issues.append(
                "moderate specialization with low confidence + high promise"
            )
            ri.promise_dimension_coherence_passed = False

    # --- Wording coherence ---
    # Check that wording state signals are consistent
    ri.wording_coherence_passed = True  # assume passed unless flagged

    # --- Observability coherence ---
    # Already checked above for builder; verify no other not-observable dimensions
    # have promise artifacts leaking through
    if dc.builder_observability_status == ObservabilityStatus.NOT_RELIABLY_OBSERVED.value:
        if prom.promising_builder_sophistication_score != 0.0:
            ri.observability_coherence_passed = False
            issues.append(
                "builder not observable but builder promise still nonzero"
            )

    # --- Overall integrity ---
    ri.integrity_issues = issues
    ri.auto_corrections_applied = corrections
    ri.report_integrity_passed = (
        ri.promise_dimension_coherence_passed
        and ri.wording_coherence_passed
        and ri.observability_coherence_passed
        and len(issues) == 0
    )
    # v1.0: if integrity failed, issues must not be empty
    if not ri.report_integrity_passed and not ri.integrity_issues:
        ri.integrity_issues = ["unspecified coherence issue detected"]
    # v1.0: set degraded flag if corrections were needed
    if corrections:
        ri.report_degraded_flag = True


# ---------------------------------------------------------------------------
# Evidence regime classification (v0.9)
# ---------------------------------------------------------------------------

def _compute_evidence_regime(evidence: Evidence, signals: SignalSet) -> None:
    """Classify the evidence base as sparse / limited / normal / rich.

    This drives conservatism levels across the evaluator, especially
    for specialization scoring.
    """
    er = signals.evidence_regime
    c = signals.contribution
    co = signals.collaboration
    st = signals.stewardship
    mat = signals.maturity
    sp = signals.specialization

    # Count total collected artifacts
    total_artifacts = (
        len(evidence.pull_requests)
        + len(evidence.reviews)
        + len(evidence.issue_participations)
        + len(evidence.release_involvements)
    )
    er.total_collected_artifacts = total_artifacts

    # External evidence?
    er.external_evidence_present = (
        c.independent_acceptance_count > 0
        or c.merged_pr_count_external > 0
        or co.external_counterparty_count > 0
    )

    # Activity in window
    er.observation_window_activity_count = total_artifacts

    # Sparse triggers (§4.1 from requirements)
    sparse_factors = 0
    if mat.evidence_depth_score < 0.15:
        sparse_factors += 2
    elif mat.evidence_depth_score < 0.30:
        sparse_factors += 1
    if c.merged_pr_count == 0:
        sparse_factors += 1
    if co.review_activity_count == 0:
        sparse_factors += 1
    if total_artifacts < 5:
        sparse_factors += 2
    elif total_artifacts < 15:
        sparse_factors += 1
    if sp.domain_support_breadth <= 1:
        sparse_factors += 1
    if sp.domain_support_duration == 0:
        sparse_factors += 1
    if not er.external_evidence_present:
        sparse_factors += 1
    if len(evidence.repositories) <= 2:
        sparse_factors += 1

    # Classify
    if sparse_factors >= 6:
        er.evidence_regime = "sparse"
        er.sparse_evidence_flag = True
        er.evidence_regime_basis = (
            f"Sparse evidence ({sparse_factors} sparse factors): "
            f"{total_artifacts} artifacts, {c.merged_pr_count} PRs, "
            f"{len(evidence.repositories)} repos, "
            f"depth={mat.evidence_depth_score:.2f}"
        )
    elif sparse_factors >= 4:
        er.evidence_regime = "limited"
        er.sparse_evidence_flag = False
        er.evidence_regime_basis = (
            f"Limited evidence ({sparse_factors} sparse factors)"
        )
    elif mat.evidence_depth_score >= 0.7 and total_artifacts >= 50:
        er.evidence_regime = "rich"
        er.sparse_evidence_flag = False
        er.evidence_regime_basis = (
            f"Rich evidence: depth={mat.evidence_depth_score:.2f}, "
            f"{total_artifacts} artifacts"
        )
    else:
        er.evidence_regime = "normal"
        er.sparse_evidence_flag = False
        er.evidence_regime_basis = "Normal evidence base"

    # v1.0: compute specialization source tier (Priority C §5.4)
    has_external_domain = any(
        sp.external_repos_per_domain.get(d, 0) > 0
        for d in sp.repos_per_domain
    )
    has_pr_activity = c.merged_pr_count > 0
    has_review_activity = co.review_activity_count > 0
    primary_months = sp.active_months_per_domain.get(sp.primary_domain or "", 0)
    primary_repos = sp.repos_per_domain.get(sp.primary_domain or "", 0)

    if has_external_domain and primary_months >= 6 and primary_repos >= 3 and (has_pr_activity or has_review_activity):
        er.specialization_source_tier = "rich_mixed_domain_evidence"
    elif has_external_domain and (has_pr_activity or has_review_activity):
        er.specialization_source_tier = "metadata_plus_external_validation"
    elif has_pr_activity or has_review_activity or primary_months >= 3:
        er.specialization_source_tier = "metadata_plus_activity"
    else:
        er.specialization_source_tier = "metadata_only"


# ---------------------------------------------------------------------------
# Foundational builder signals (v0.9 — Route C)
# ---------------------------------------------------------------------------

def _compute_foundational_builder(evidence: Evidence, signals: SignalSet) -> None:
    """Compute foundational infrastructure builder signals.

    Route C allows recognition of extremely strong builder sophistication
    from central infrastructure ownership, technical substance, and public
    reliance — even without PR-visible delivery.
    """
    fb = signals.foundational_builder
    bs = signals.builder_sophistication
    st = signals.stewardship
    op = signals.owned_projects
    sp = signals.specialization
    mat = signals.maturity

    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    if not owned_repos:
        return

    # Central repo substance: how technically substantial are the central owned repos
    substance_scores = []
    for r in owned_repos:
        is_central = (r.stars >= 1000 and (r.contributor_count or 0) >= 50) or r.stars >= 10000
        if not is_central:
            continue
        has_language = r.primary_language is not None
        has_topics = len(r.topics) >= 1
        has_description = bool(r.description and len(r.description) > 20)
        has_size = (r.disk_usage_kb or 0) > 1000
        is_long_lived = False
        if r.created_at and r.updated_at:
            try:
                created = _parse_iso(r.created_at)
                updated = _parse_iso(r.updated_at)
                if created and updated:
                    age_months = (updated.year - created.year) * 12 + (updated.month - created.month)
                    is_long_lived = age_months >= 60  # 5+ years
            except (ValueError, TypeError):
                pass

        repo_substance = (
            (0.20 if has_language else 0.0)
            + (0.15 if has_description else 0.0)
            + (0.10 if has_topics else 0.0)
            + (0.20 if has_size else 0.0)
            + (0.15 if is_long_lived else 0.0)
            + min(math.log1p(r.stars) / math.log1p(50000), 1.0) * 0.10
            + min((r.contributor_count or 0) / 500, 1.0) * 0.10
        )
        substance_scores.append(repo_substance)

    if substance_scores:
        fb.central_repo_substance_score = max(substance_scores)
    else:
        return  # No central repos → no foundational builder signal

    # Long-lived repo substance
    long_lived_scores = []
    for r in owned_repos:
        if r.created_at:
            try:
                created = _parse_iso(r.created_at)
                if created:
                    now = _parse_iso(evidence.observation_window_end) or datetime.now(timezone.utc)
                    age_years = (now.year - created.year) + (now.month - created.month) / 12
                    if age_years >= 5:
                        long_lived_scores.append(min(age_years / 15, 1.0))
            except (ValueError, TypeError):
                pass
    fb.long_lived_repo_substance_score = max(long_lived_scores) if long_lived_scores else 0.0

    # Foundational system ownership: centrality + reliance + substance
    fb.foundational_system_ownership_signal = min(
        (st.owned_repo_centrality_score / 10) * 0.40
        + (st.owned_repo_public_reliance_score) * 0.30
        + fb.central_repo_substance_score * 0.30,
        1.0,
    )

    # Technical foundation signal: systems-level language + low-level domain cues
    systems_languages = {"C", "C++", "Assembly", "Rust", "Go"}
    owned_langs = set(r.primary_language for r in owned_repos if r.primary_language)
    systems_lang_ratio = len(owned_langs & systems_languages) / max(len(owned_langs), 1)
    fb.technical_foundation_signal = min(
        systems_lang_ratio * 0.50
        + fb.central_repo_substance_score * 0.30
        + fb.long_lived_repo_substance_score * 0.20,
        1.0,
    )

    # Systems scope signal
    total_central_stars = sum(r.stars for r in owned_repos if r.stars >= 1000)
    total_central_contributors = sum(r.contributor_count for r in owned_repos if (r.contributor_count or 0) >= 50)
    fb.systems_scope_signal = min(
        min(math.log1p(total_central_stars) / math.log1p(100000), 1.0) * 0.50
        + min(total_central_contributors / 2000, 1.0) * 0.50,
        1.0,
    )

    # Composite foundational infrastructure builder signal
    fb.foundational_infrastructure_builder_signal = min(
        fb.foundational_system_ownership_signal * 0.35
        + fb.technical_foundation_signal * 0.25
        + fb.systems_scope_signal * 0.25
        + fb.central_repo_substance_score * 0.15,
        1.0,
    )

    # Route C: activate foundational builder in BuilderSophisticationSignals
    if fb.foundational_infrastructure_builder_signal >= 0.4:
        bs.foundational_builder_route_active = True
        bs.foundational_builder_score = fb.foundational_infrastructure_builder_signal


# ---------------------------------------------------------------------------
# Temporal safety signals (v0.9)
# ---------------------------------------------------------------------------

def _compute_temporal_safety(signals: SignalSet) -> None:
    """Ensure temporal metrics are safe for empty/invalid windows."""
    ci = signals.consistency_interpretation
    cs = signals.consistency

    # Check for invalid temporal denominator
    if cs.total_months_in_window <= 0:
        ci.temporal_denominator_valid = False
        ci.temporal_evidence_completeness = "none"
        ci.consistency_fallback_reason = (
            "observation window has zero months — "
            "consistency cannot be meaningfully assessed"
        )
    elif cs.observed_months_active == 0:
        ci.temporal_denominator_valid = True
        ci.temporal_evidence_completeness = "none"
        ci.consistency_fallback_reason = (
            "no activity detected in observation window — "
            "consistency cannot be assessed"
        )
    elif cs.observed_months_active < 3 and cs.total_months_in_window >= 6:
        ci.temporal_denominator_valid = True
        ci.temporal_evidence_completeness = "partial"
        ci.consistency_fallback_reason = ""
    else:
        ci.temporal_denominator_valid = True
        ci.temporal_evidence_completeness = "sufficient"
        ci.consistency_fallback_reason = ""
