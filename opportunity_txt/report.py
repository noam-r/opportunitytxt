"""Report generation module (v1.0).

Produces the three output artifacts:
1. Raw evidence JSON
2. Computed signals JSON
3. Human-readable Markdown report

v1.0 changes:
- All dimension rendering uses canonical FinalDimensionResult (Priority A)
- Evidence regime display section (sparse/limited/normal/rich)
- Foundational builder signal display (Route C)
- Builder route labeling in dimension output
- Temporal safety rendering (NRO consistency for empty windows)
- Integrity mode user/debug with explicit issue reporting
- Report header with explicit scope statement
- Updated methodology steps for v1.0 pipeline
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import (
    Archetype,
    ArchetypeResult,
    ConfidenceBand,
    DimensionResult,
    EvaluationResult,
    Evidence,
    FinalDimensionResult,
    MaturityBand,
    ObservabilityStatus,
    ScoreBand,
    SignalSet,
    StageInterpretation,
)

_SCORE_ICONS = {
    ScoreBand.LOW: "⬜",
    ScoreBand.EMERGING: "🟨",
    ScoreBand.MODERATE: "🟧",
    ScoreBand.STRONG: "🟩",
    ScoreBand.VERY_STRONG: "🟢",
}

_CONFIDENCE_ICONS = {
    ConfidenceBand.LOW: "◻️",
    ConfidenceBand.MEDIUM: "◼️",
    ConfidenceBand.HIGH: "⬛",
}


def save_evidence(evidence: Evidence, path: Path) -> None:
    path.write_text(json.dumps(evidence.to_dict(), indent=2, default=str))


def save_signals(signals: SignalSet, path: Path) -> None:
    path.write_text(json.dumps(signals.to_dict(), indent=2, default=str))


def save_report(
    evidence: Evidence,
    signals: SignalSet,
    result: EvaluationResult,
    path: Path,
) -> None:
    md = _render_report(evidence, signals, result)
    path.write_text(md)


# ------------------------------------------------------------------
# Markdown rendering
# ------------------------------------------------------------------

def _render_report(
    evidence: Evidence,
    signals: SignalSet,
    result: EvaluationResult,
) -> str:
    lines: list[str] = []
    w = lines.append

    # Title
    w(f"# Evaluation Report: {result.subject}")
    w("")
    w(f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  ")
    w(f"**Methodology version:** {result.methodology_version}")
    w("")
    # v1.0: explicit scope statement (§5.2)
    w("> **What this report measures:** public GitHub-visible evidence — contribution "
      "patterns, stewardship signals, builder signals, and public adoption proxies.  ")
    w("> **What it does not measure:** total professional ability, private work, "
      "organizational leadership, hiring skill, strategic judgment, or business success.")
    w("")

    # 1. Subject summary
    w("## 1. Subject Summary")
    w("")
    p = evidence.profile
    w(f"- **Username:** [{p.username}]({p.url})")
    if p.name:
        w(f"- **Name:** {p.name}")
    w(f"- **Account created:** {p.created_at[:10]}")
    w(f"- **Public repositories:** {p.public_repo_count}")
    w(f"- **Followers:** {p.followers}")
    if p.bio:
        w(f"- **Bio:** {p.bio}")
    w("")
    w("> Profile text (bio, name) is shown for context only and does not influence scoring.")
    w("")

    # 2. Evaluation scope
    w("## 2. Evaluation Scope")
    w("")
    w(f"- **Observation window:** {result.observation_window_start[:10]} -> {result.observation_window_end[:10]}")
    w(f"- **Repositories evaluated:** {result.repos_evaluated}")
    meta = evidence.collection_metadata
    w(f"- **Pull requests collected:** {meta.get('prs_collected', 'N/A')}")
    w(f"- **Reviews collected:** {meta.get('reviews_collected', 'N/A')}")
    w(f"- **Issues collected:** {meta.get('issues_collected', 'N/A')}")
    w(f"- **Releases collected:** {meta.get('releases_collected', 'N/A')}")
    w(f"- **Counterparties tracked:** {meta.get('counterparties_tracked', 'N/A')}")
    w("")

    # 3. Archetype Detection (v0.3)
    w("## 3. Archetype Detection")
    w("")
    detected = [a for a in result.archetypes if a.detected]
    if detected:
        w("Detected public-work archetypes:")
        w("")
        for a in detected:
            conf_pct = f"{a.confidence:.0%}"
            w(f"- **{a.archetype.value}** (confidence: {conf_pct}) -- {a.basis}")
        w("")
    else:
        w("No strong archetype patterns detected from available evidence.")
        w("")
    not_detected = [a for a in result.archetypes if not a.detected]
    if not_detected:
        # v0.5: show secondary archetype hints for non-detected archetypes with signal
        secondary = signals.archetype_soft
        has_secondary = False
        for a in not_detected:
            strength = secondary.secondary_archetype_strengths.get(a.archetype.value, 0)
            if strength >= 0.3:
                if not has_secondary:
                    w("**Secondary archetype signals:**")
                    w("")
                    has_secondary = True
                w(f"- Weak **{a.archetype.value}** signal (strength: {strength:.0%}) -- {a.basis}")
        if has_secondary:
            w("")
        w("<details>")
        w("<summary>Archetypes not detected</summary>")
        w("")
        for a in not_detected:
            w(f"- {a.archetype.value}: {a.basis}")
        w("")
        w("</details>")
        w("")

    # 4. Public Evidence Maturity (v0.4)
    w("## 4. Public Evidence Maturity")
    w("")
    mat = signals.maturity
    if mat.maturity_band:
        w(f"**Maturity band:** {mat.maturity_band}")
        w("")
        w(f"**Basis:** {mat.maturity_basis}")
        w("")
        w("| Signal | Value |")
        w("|--------|------:|")
        w(f"| History depth | {mat.history_depth_score:.2f} |")
        w(f"| Evidence depth | {mat.evidence_depth_score:.2f} |")
        w(f"| Evidence diversity | {mat.evidence_diversity_score:.2f} |")
        w(f"| Stage readiness | {mat.stage_readiness_score:.2f} |")
        w("")
    else:
        w("Maturity classification not available.")
        w("")

    # 5. Promise / Readiness (v0.8: redesigned as sparse derived interpretation)
    w("## 5. Promise / Readiness")
    w("")
    si = result.stage_interpretation
    if si:
        w(f"**Contributor type:** {si.contributor_type}")
        w("")
        w(f"**Promise:** {si.promise_summary}")
        w("")
        w(f"**Readiness:** {si.readiness_summary}")
        w("")
        # v0.8: sparse promise table — only show meaningful nonzero values
        mp = signals.mature_profile
        prom = signals.promise
        if prom.promise_render_mode == "suppressed":
            w(f"> Promise-detail table suppressed: {prom.promise_suppressed_reason}")
            w("")
        elif prom.promise_render_mode == "mature":
            # For mature (non-suppressed) profiles, show only if values are meaningful
            rows = []
            if prom.promising_builder_sophistication_score >= 0.3:
                rows.append(("Builder sophistication", prom.promising_builder_sophistication_score))
            if prom.promising_execution_score >= 0.3:
                rows.append(("Execution", prom.promising_execution_score))
            if rows:
                w("| Demonstrated Strength | Signal |")
                w("|----------------------|-------:|")
                for label, val in rows:
                    w(f"| {label} | {val:.2f} |")
                w("")
        else:
            # Developing mode: show promise facets that are meaningful (>= 0.2)
            rows = []
            if prom.early_signal_strength >= 0.2:
                rows.append(("Early signal strength", prom.early_signal_strength))
            if prom.promising_execution_score >= 0.2:
                rows.append(("Promising execution", prom.promising_execution_score))
            if prom.promising_specialization_score >= 0.2:
                label = "Promising specialization"
                if prom.specialization_promise_ceiling_reason:
                    label += f" (ceiling: {prom.specialization_promise_ceiling_reason})"
                rows.append((label, prom.promising_specialization_score))
            if prom.promising_external_acceptance_score >= 0.2:
                rows.append(("Promising external acceptance", prom.promising_external_acceptance_score))
            if prom.promising_builder_sophistication_score >= 0.2:
                rows.append(("Promising builder sophistication", prom.promising_builder_sophistication_score))
            if rows:
                w("| Promise Signal | Value |")
                w("|----------------|------:|")
                for label, val in rows:
                    w(f"| {label} | {val:.2f} |")
                w("")
    else:
        w("Stage-aware interpretation not available.")
        w("")

    # 6. Interpretation Context (v0.4)
    w("## 6. Interpretation Context")
    w("")
    if si:
        w(f"This report should be read primarily as a **{si.maturity_band.value.lower()}** profile.")
        w("")
        w("> Dimension scores reflect absolute public evidence. "
          "The interpretation context above indicates the contributor's "
          "evidence maturity stage. Scores should be understood within "
          "that stage context, not compared directly across stages.")
        w("")
        # v0.5: contribution calibration note
        cc = signals.contribution_calibration
        if cc.contribution_ceiling_reason:
            w(f"> :information_source: **Contribution calibration:** {cc.contribution_ceiling_reason} "
              "Execution strength is reflected in the promise/readiness interpretation.")
            w("")
        # v0.7: builder observability note
        # v1.0: do NOT show NRO banner if Route C produced a scored builder result
        bs = signals.builder_sophistication
        dc = signals.dimension_coverage
        builder_fd = next((fd for fd in result.final_dimensions if fd.name == "Builder Sophistication"), None)
        builder_is_scored = builder_fd and builder_fd.status == "scored"

        if dc.builder_observability_status == ObservabilityStatus.NOT_RELIABLY_OBSERVED.value and not builder_is_scored:
            w("> :eye: **Builder Sophistication is Not Reliably Observable** for this profile. "
              f"Builder observability mode: *{bs.builder_observability_mode}*. "
              "The evidence mode (primarily stewardship/governance) does not reliably "
              "surface builder sophistication signals. This is not a negative finding.")
            w("")
        elif builder_is_scored and bs.builder_sophistication_signal >= 0.25:
            w("> :hammer_and_wrench: **Builder sophistication detected.** "
              "This profile shows meaningful visible self-directed product/system building. "
              "Builder Sophistication is scored as a separate dimension and does not "
              "automatically raise trust or ecosystem impact.")
            w("")

        # v0.9: foundational builder note
        fb = signals.foundational_builder
        if bs.foundational_builder_route_active:
            w("> :bricks: **Foundational infrastructure builder (Route C) active.** "
              f"Foundational builder signal: *{fb.foundational_infrastructure_builder_signal:.2f}*. "
              "Builder sophistication is assessed via foundational infrastructure ownership "
              "rather than PR-delivery evidence.")
            w("")

        # v0.9: evidence regime note
        er = signals.evidence_regime
        if er.evidence_regime == "sparse":
            w(f"> :warning: **Sparse evidence base.** {er.evidence_regime_basis}. "
              "Dimension scores, especially specialization, are conservatively "
              "capped to prevent overstatement.")
            w("")
        elif er.evidence_regime == "limited":
            w(f"> :information_source: **Limited evidence base.** {er.evidence_regime_basis}. "
              "Some dimension scores may be constrained by evidence depth.")
            w("")
    else:
        w("No stage-aware interpretation context available.")
        w("")

    # 7. Repository set
    w("## 7. Repository Set")
    w("")
    owned_repos = [r for r in evidence.repositories if r.is_owned_by_subject]
    external_repos = [r for r in evidence.repositories if not r.is_owned_by_subject]
    w(f"**Owned:** {len(owned_repos)} | **External:** {len(external_repos)} | **Total:** {len(evidence.repositories)}")
    w("")
    w("| Repository | Owner | Stars | Language | Topics |")
    w("|-----------|-------|------:|----------|--------|")
    for repo in sorted(evidence.repositories, key=lambda r: r.stars, reverse=True)[:25]:
        topics = ", ".join(repo.topics[:4]) if repo.topics else "--"
        lang = repo.primary_language or "--"
        owned = " *" if repo.is_owned_by_subject else ""
        w(f"| [{repo.name}]({repo.url}){owned} | {repo.owner} | {repo.stars:,} | {lang} | {topics} |")
    if len(evidence.repositories) > 25:
        w(f"| ... and {len(evidence.repositories) - 25} more | | | | |")
    w("")
    w("\\* = owned by subject")
    w("")

    # 8. Governance Context (v0.3)
    w("## 8. Governance Context")
    w("")
    c = signals.contribution
    w("| Category | Count |")
    w("|----------|------:|")
    w(f"| Total merged PRs | {c.merged_pr_count} |")
    w(f"| Independently accepted (external repo, external merge) | {c.independent_acceptance_count} |")
    w(f"| External repo, self-merged | {c.external_repo_self_merged_pr_count} |")
    w(f"| Self-owned repo, self-merged | {c.self_repo_self_merged_pr_count} |")
    w(f"| Independent acceptance ratio | {c.independent_acceptance_ratio:.0%} |")
    w(f"| Repos with independent acceptance | {c.independent_acceptance_repo_count} |")
    w("")
    if c.independent_acceptance_count == 0 and c.merged_pr_count > 0:
        w("> :warning: No independently accepted contributions detected. "
          "All merges are either self-governed or in self-owned repos.")
        w("")
    if c.external_repo_self_merged_pr_count > 0:
        w(f"> :information_source: {c.external_repo_self_merged_pr_count} PRs in external repos were self-merged. "
          "These are not counted as independently accepted.")
        w("")

    # 9. Owned Public Projects (v0.3)
    w("## 9. Owned Public Projects")
    w("")
    op = signals.owned_projects
    if op.owned_public_project_count > 0:
        w(f"**{op.owned_public_project_count}** owned public projects evaluated.")
        w("")
        w("| Metric | Value |")
        w("|--------|------:|")
        w(f"| Visibility score | {op.owned_public_project_visibility_score:.1f} |")
        w(f"| External interest score | {op.owned_public_project_external_interest_score:.2f} |")
        w(f"| Release count | {op.owned_public_project_release_count} |")
        w(f"| Average age score | {op.owned_public_project_age_score:.1f} |")
        w(f"| Maintenance score | {op.owned_public_project_maintenance_score:.2f} |")
        w("")
        if op.owned_public_project_visibility_score >= 5.0:
            w("> Owned projects show meaningful public adoption.")
            w("")
    else:
        w("No owned public projects in the evaluated set.")
        w("")

    # 10. Stewardship Signals (v0.3)
    w("## 10. Stewardship Signals")
    w("")
    st = signals.stewardship
    w("| Signal | Value |")
    w("|--------|------:|")
    w(f"| Issue participation | {st.issue_participation_count} |")
    w(f"| Issue response activity | {st.issue_response_activity_count} |")
    w(f"| Release stewardship | {st.release_stewardship_count} |")
    w(f"| Governance activity score | {st.repo_governance_activity_score:.2f} |")
    w(f"| Owned repo centrality | {st.owned_repo_centrality_score:.1f} |")
    w(f"| Public reliance score | {st.owned_repo_public_reliance_score:.2f} |")
    w(f"| Maintainer visibility | {st.maintainer_visibility_score:.2f} |")
    w(f"| **Stewardship signal** | **{st.stewardship_signal:.2f}** |")
    w("")

    # 11. Execution Intensity (v0.3)
    w("## 11. Execution Intensity")
    w("")
    ei = signals.execution_intensity
    w("| Metric | Value |")
    w("|--------|------:|")
    w(f"| Merged work per active month | {ei.merged_work_per_active_month:.1f} |")
    w(f"| Change volume per active month | {ei.change_volume_per_active_month:.0f} |")
    w(f"| Active repos during peak window | {ei.active_repo_count_during_peak_window} |")
    w(f"| **Burst execution score** | **{ei.burst_execution_score:.2f}** |")
    w("")

    # 11b. Builder Sophistication Signals (v0.7/v1.0)
    bs = signals.builder_sophistication
    if bs.builder_sophistication_signal > 0 or bs.large_pr_count > 0 or bs.builder_observability_mode:
        w("## 11b. Builder Sophistication Signals")
        w("")
        # v0.7: show observability mode and signal path
        if bs.builder_observability_mode:
            w(f"**Observability mode:** {bs.builder_observability_mode}  ")
            w(f"**Signal path:** {bs.builder_signal_path}  ")
            w(f"**Evidence coverage:** {bs.builder_evidence_coverage:.2f}  ")
            w(f"**Observability confidence:** {bs.builder_observability_confidence:.2f}")
            w("")
        # v1.0: label these as route-specific inputs, not final dimension
        w("*The signals below are route-specific inputs. See Dimension Results for the final builder score.*")
        w("")
        w("**Route A — PR-delivery signals:**")
        w("")
        w("| Metric | Value |")
        w("|--------|------:|")
        w(f"| Large PRs (>=200 adds) | {bs.large_pr_count} |")
        w(f"| Very large PRs (>=500 adds) | {bs.very_large_pr_count} |")
        w(f"| Median additions per PR | {bs.median_additions_per_pr:.0f} |")
        w(f"| Max additions per PR | {bs.max_additions_per_pr} |")
        w(f"| Median changed files per PR | {bs.median_changed_files_per_pr:.1f} |")
        w(f"| Multi-subsystem PRs (>=5 files) | {bs.multi_subsystem_pr_count} |")
        w(f"| Repos with large PRs | {bs.large_pr_repo_count} |")
        w(f"| Repeated feature delivery repos | {bs.repeated_feature_delivery_count} |")
        w(f"| Repeated major delivery repos | {bs.repeated_major_delivery_count} |")
        w(f"| Product scope signal | {bs.product_scope_signal:.2f} |")
        w("")
        w("**Route B — Repo-substance signals:**")
        w("")
        w("| Metric | Value |")
        w("|--------|------:|")
        w(f"| Repo complexity score | {bs.repo_complexity_score:.2f} |")
        w(f"| Owned repo complexity | {bs.owned_repo_complexity_score:.2f} |")
        w(f"| Repo substance | {bs.repo_substance_score:.2f} |")
        w(f"| Owned repo breadth | {bs.owned_repo_breadth_score:.2f} |")
        w("")
        w(f"**Composite builder sophistication signal:** {bs.builder_sophistication_signal:.2f}")
        w("")

    # 11c. Foundational Builder Signals (v0.9)
    fb = signals.foundational_builder
    if fb.foundational_infrastructure_builder_signal > 0 or bs.foundational_builder_route_active:
        w("## 11c. Foundational Builder Signals")
        w("")
        w(f"**Route C active:** {'yes' if bs.foundational_builder_route_active else 'no'}  ")
        w(f"**Foundational builder score:** {bs.foundational_builder_score:.2f}")
        w("")
        w("| Signal | Value |")
        w("|--------|------:|")
        w(f"| Foundational infrastructure builder signal | {fb.foundational_infrastructure_builder_signal:.2f} |")
        w(f"| Central repo substance | {fb.central_repo_substance_score:.2f} |")
        w(f"| Foundational system ownership | {fb.foundational_system_ownership_signal:.2f} |")
        w(f"| Long-lived repo substance | {fb.long_lived_repo_substance_score:.2f} |")
        w(f"| Technical foundation signal | {fb.technical_foundation_signal:.2f} |")
        w(f"| Systems scope signal | {fb.systems_scope_signal:.2f} |")
        w("")

    # 11d. Evidence Regime (v0.9)
    er = signals.evidence_regime
    w("## 11d. Evidence Regime")
    w("")
    w(f"**Evidence regime:** {er.evidence_regime}  ")
    w(f"**Sparse evidence flag:** {'yes' if er.sparse_evidence_flag else 'no'}  ")
    w(f"**Total collected artifacts:** {er.total_collected_artifacts}  ")
    w(f"**External evidence present:** {'yes' if er.external_evidence_present else 'no'}  ")
    if er.specialization_sparse_cap_applied:
        w("**Specialization sparse cap:** applied")
    w("")
    w(f"> {er.evidence_regime_basis}")
    w("")

    # 12. Dimension results — rendered from canonical FinalDimensionResult (v1.0)
    w("## 12. Dimension Results")
    w("")
    w("### Summary")
    w("")
    w("| Dimension | Score | Confidence | Observability |")
    w("|-----------|-------|------------|---------------|")
    for fd in result.final_dimensions:
        if fd.status == "not_reliably_observable":
            score_display = "⚠️ Not Reliably Observable"
            conf_display = "--"
        else:
            # Look up icons from the raw dimension score for display
            raw_dim = next((d for d in result.dimensions if d.name == fd.name), None)
            if raw_dim:
                score_icon = _SCORE_ICONS.get(raw_dim.score, "")
                conf_icon = _CONFIDENCE_ICONS.get(raw_dim.confidence, "")
            else:
                score_icon = ""
                conf_icon = ""
            score_display = f"{score_icon} {fd.score_label}"
            conf_display = f"{conf_icon} {fd.confidence_label}"
        obs_label = fd.observability_label if fd.observability_label != "Well Observed" else ""
        w(f"| {fd.name} | {score_display} | {conf_display} | {obs_label} |")
    w("")

    # Detailed dimension sections — rendered from FinalDimensionResult
    for fd in result.final_dimensions:
        w(f"### {fd.name}")
        w("")
        if fd.status == "not_reliably_observable":
            w("**Score:** Not Reliably Observable  ")
            w("**Confidence:** N/A")
            w("")
            w("> :eye: This dimension is not reliably observable from the current evidence mode.")
            w("")
        else:
            w(f"**Score:** {fd.score_label}  ")
            w(f"**Confidence:** {fd.confidence_label}")
            w("")
            if fd.observability_label and fd.observability_label != "Well Observed":
                w(f"> :information_source: Observability: {fd.observability_label}")
                w("")
        # v1.0: show supporting route if present
        if fd.supporting_route:
            w(f"> :hammer_and_wrench: Scoring route: {fd.supporting_route}")
            w("")
        if fd.score_cap_applied and fd.cap_reason:
            w(f"> :warning: Score cap applied: {fd.cap_reason}")
            w("")
        w(f"**Claim:** {fd.claim}")
        w("")
        w(f"**Evidence:** {fd.evidence_summary}")
        w("")
        w(f"**Interpretation:** {fd.interpretation}")
        w("")
        w(f"**Limitation:** {fd.limitation}")
        w("")

    # 13. Domain Inference + Confidence (v0.3)
    w("## 13. Domain Inference")
    w("")
    di = result.domain_inference
    w(f"- **Primary domain:** {di.primary_domain or 'Not detected'}")
    if di.secondary_domains:
        w(f"- **Secondary domains:** {', '.join(di.secondary_domains)}")
    w(f"- **Domain confidence:** {di.confidence:.0%}")
    if di.override_applied:
        w("- **Curated override applied:** yes")
    w(f"- **Basis:** {di.evidence}")
    w("")
    sp = signals.specialization
    if sp.repos_per_domain:
        w("| Domain | Repos | External Repos | Active Months |")
        w("|--------|------:|---------------:|--------------:|")
        for domain in sorted(sp.repos_per_domain, key=sp.repos_per_domain.get, reverse=True):
            repos = sp.repos_per_domain.get(domain, 0)
            ext = sp.external_repos_per_domain.get(domain, 0)
            months = sp.active_months_per_domain.get(domain, 0)
            w(f"| {domain} | {repos} | {ext} | {months} |")
        w("")

    # 14. Key evidence highlights
    w("## 14. Key Evidence Highlights")
    w("")
    highlights = _compute_highlights(evidence, signals, result)
    for h in highlights:
        w(f"- {h}")
    w("")

    # 15. Report Integrity (v1.0)
    w("## 15. Report Integrity")
    w("")
    ri = signals.report_integrity
    # v1.0: integrity mode and degraded flag
    if ri.report_degraded_flag:
        w(":warning: **Report degraded:** coherence issues were detected and "
          "auto-corrected. Details below.")
        w("")
    if ri.report_integrity_passed:
        w(":white_check_mark: All coherence checks passed.")
    else:
        w(":warning: Coherence issues detected:")
        w("")
        for issue in ri.integrity_issues:
            w(f"- {issue}")
    w("")
    # v1.0: show auto-corrections if any
    if ri.auto_corrections_applied:
        w("**Auto-corrections applied:**")
        w("")
        for correction in ri.auto_corrections_applied:
            w(f"- {correction}")
        w("")
    w("| Check | Status |")
    w("|-------|--------|")
    w(f"| Promise–dimension coherence | {'✅' if ri.promise_dimension_coherence_passed else '⚠️ corrected'} |")
    w(f"| Wording coherence | {'✅' if ri.wording_coherence_passed else '⚠️ corrected'} |")
    w(f"| Observability coherence | {'✅' if ri.observability_coherence_passed else '⚠️ corrected'} |")
    w("")

    # 16. Limitations
    w("## 16. Limitations")
    w("")
    w("This evaluation is subject to the following limitations:")
    w("")
    w("- Based **only on public GitHub-visible work**. Private repositories, internal company contributions, and non-GitHub work are invisible.")
    w("- **Public contribution does not represent total professional ability.** Many skilled engineers have limited public profiles.")
    w("- **Management and organizational impact cannot be reliably inferred** from code contribution patterns.")
    w("- **Sparse evidence reduces confidence**, not the score itself. A contributor with limited public history may still be highly skilled.")
    w("- Repository metadata and public workflow structures are **imperfect proxies** for actual engineering quality.")
    w("- Domain inference is based on keyword matching against repository metadata and **may misclassify nuanced expertise**.")
    w("- Contribution patterns vary by employer policy, project culture, and personal preference -- these factors are not controlled for.")
    w("- **Self-merged work in external repos** may reflect commit access or organizational roles, not independent external acceptance.")
    w("")

    # 17. Methodology
    w("## 17. Methodology")
    w("")
    w(f"**Version:** {result.methodology_version}")
    w("")
    w("This report was generated by a deterministic evaluation pipeline that:")
    w("")
    w("1. Collects public GitHub data via the GraphQL API")
    w("2. Normalizes raw data into a consistent internal model")
    w("3. Detects public-work archetypes from evidence patterns (including Foundational Infrastructure Builder)")
    w("4. Classifies public-evidence maturity signals")
    w("5. Computes evidence regime classification (sparse / limited / normal / rich)")
    w("6. Computes deterministic signals across seven dimensions plus governance, stewardship, execution intensity, and builder sophistication")
    w("7. Computes foundational builder signals (Route C) for central infrastructure creators")
    w("8. Computes builder observability, dimension coverage, mature-profile, domain directionality, and specialization coherence signals")
    w("9. Applies secondary-domain cleanup for central low-level profiles")
    w("10. Computes temporal safety signals and validates observation-window integrity")
    w("11. Computes promise signals bounded by dimension scores and confidence (derived, not independent)")
    w("12. Computes wording-state signals for language coherence enforcement")
    w("13. Maps signals to score bands using archetype-safe, multi-path threshold-based rules")
    w("14. Applies sparse-evidence specialization cap (§4.2) and evidence-regime conservatism")
    w("15. Applies dimension observability status (well observed / partially observed / not reliably observable)")
    w("16. Applies internal coherence and contradiction checks")
    w("17. Runs final report integrity checks (promise–dimension, wording, observability coherence)")
    w("18. Produces stage-aware interpretation with sparse, bounded promise facets")
    w("19. Estimates confidence based on evidence volume, diversity, and consistency")
    w("20. Generates this explainable report")
    w("")
    w("No machine learning or LLM is used in scoring or evaluation. All conclusions are deterministic and reproducible given the same input data.")
    w("")

    w("---")
    w("")
    w("*This report is a proof-of-concept evaluation. It should be reviewed by a human and used as supplementary context, not as a definitive assessment.*")

    return "\n".join(lines)


def _compute_highlights(
    evidence: Evidence,
    signals: SignalSet,
    result: EvaluationResult,
) -> list[str]:
    """Generate notable evidence highlights for the report."""
    highlights: list[str] = []

    # v0.4: stage-aware maturity highlight
    mat = signals.maturity
    if mat.maturity_band:
        highlights.append(f"Evidence maturity: **{mat.maturity_band}**.")

    c = signals.contribution
    if c.merged_pr_count > 0:
        highlights.append(
            f"Merged **{c.merged_pr_count}** pull requests with a "
            f"**{c.merge_ratio:.0%}** acceptance rate "
            f"(**{c.independent_acceptance_count}** independently accepted, "
            f"**{c.merged_pr_count_self_owned}** self-owned)."
        )

    if c.independent_acceptance_count > 0:
        highlights.append(
            f"**{c.independent_acceptance_count}** PRs were independently accepted "
            f"by external maintainers across "
            f"**{c.independent_acceptance_repo_count}** repositories."
        )

    if c.external_repo_self_merged_pr_count > 0:
        highlights.append(
            f"**{c.external_repo_self_merged_pr_count}** PRs in external repos "
            f"were self-merged (not independently validated)."
        )

    # v0.5: contribution calibration
    cc = signals.contribution_calibration
    if cc.self_governed_execution_ratio >= 0.8 and c.merged_pr_count >= 5:
        highlights.append(
            f"Self-governed execution ratio: **{cc.self_governed_execution_ratio:.0%}** "
            f"of merged work. "
            + ("**No independent validation** detected." if cc.independent_validation_absence else "")
        )

    # v0.6: builder sophistication highlights
    bs = signals.builder_sophistication
    if bs.builder_sophistication_signal >= 0.25:
        highlights.append(
            f"Builder sophistication signal: **{bs.builder_sophistication_signal:.2f}** "
            f"({bs.large_pr_count} large PRs across {bs.large_pr_repo_count} repos)."
        )
    if bs.repeated_feature_delivery_count >= 1:
        highlights.append(
            f"Repeated feature delivery in **{bs.repeated_feature_delivery_count}** repos."
        )

    # v0.9: foundational builder highlight
    fb = signals.foundational_builder
    if bs.foundational_builder_route_active:
        highlights.append(
            f"Foundational infrastructure builder (Route C) active. "
            f"Signal: **{fb.foundational_infrastructure_builder_signal:.2f}**."
        )

    # v0.9: evidence regime highlight
    er = signals.evidence_regime
    if er.sparse_evidence_flag:
        highlights.append(
            f"**Sparse evidence base** ({er.total_collected_artifacts} artifacts). "
            "Dimension scores are conservatively capped."
        )

    # Archetypes
    detected = [a for a in result.archetypes if a.detected]
    if detected:
        names = ", ".join(f"**{a.archetype.value}**" for a in detected)
        highlights.append(f"Detected archetypes: {names}.")

    # Owned projects
    op = signals.owned_projects
    if op.owned_public_project_count > 0 and op.owned_public_project_visibility_score >= 3.0:
        highlights.append(
            f"Owns **{op.owned_public_project_count}** public projects "
            f"with visibility score **{op.owned_public_project_visibility_score:.1f}**."
        )

    # Stewardship
    st = signals.stewardship
    if st.stewardship_signal >= 0.2:
        highlights.append(
            f"Stewardship signal: **{st.stewardship_signal:.2f}** "
            f"({st.issue_participation_count} issue participations, "
            f"{st.release_stewardship_count} releases)."
        )

    co = signals.collaboration
    if co.review_activity_count > 0:
        highlights.append(
            f"Authored **{co.review_activity_count}** code reviews "
            f"({co.substantive_review_count} substantive)."
        )

    if co.counterparty_count > 0:
        highlights.append(
            f"Interacted with **{co.counterparty_count}** distinct collaborators "
            f"(**{co.repeated_counterparty_count}** repeated)."
        )

    t = signals.trust
    if t.sustained_repos > 0:
        extras = f" ({t.sustained_external_repos} external)" if t.sustained_external_repos else ""
        highlights.append(
            f"Sustained engagement (>6 months) in **{t.sustained_repos}** repositories{extras}."
        )

    if t.repos_with_release_involvement > 0:
        highlights.append(
            f"Involved in releases for **{t.repos_with_release_involvement}** repositories."
        )

    e = signals.ecosystem
    if e.contributions_to_high_adoption_repos > 0:
        highlights.append(
            f"Contributed to **{e.contributions_to_high_adoption_repos}** "
            f"high-adoption repositories (>=500 stars)."
        )

    cs = signals.consistency
    if cs.observed_months_active > 0:
        highlights.append(
            f"Active in **{cs.observed_months_active}** months "
            f"({cs.active_month_ratio:.0%} of observation window)."
        )

    ei = signals.execution_intensity
    if ei.burst_execution_score >= 0.4:
        highlights.append(
            f"Execution intensity: **{ei.merged_work_per_active_month:.1f}** "
            f"merged PRs/active month."
        )

    if not highlights:
        highlights.append("Limited public evidence available for this profile.")

    return highlights
