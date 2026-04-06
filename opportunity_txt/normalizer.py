"""Normalization module.

Converts raw GitHub API dicts into typed internal models and builds
the complete Evidence container for one subject.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from .cache import Cache
from .collector import GitHubCollector
from .models import (
    Counterparty,
    Evidence,
    IssueParticipation,
    PRState,
    Profile,
    PullRequest,
    ReleaseInvolvement,
    Repository,
    Review,
    ReviewOutcome,
)

_PR_STATE_MAP = {
    "merged": PRState.MERGED,
    "closed": PRState.CLOSED,
    "open": PRState.OPEN,
}

_REVIEW_STATE_MAP = {
    "approved": ReviewOutcome.APPROVED,
    "changes_requested": ReviewOutcome.CHANGES_REQUESTED,
    "commented": ReviewOutcome.COMMENTED,
    "dismissed": ReviewOutcome.DISMISSED,
}

WINDOW_MAP: dict[str, int] = {
    "1y": 365,
    "2y": 730,
    "3y": 1095,
    "5y": 1825,
}


def _parse_window(window: str) -> int | None:
    """Return number of days for a window string, or None for 'all'."""
    if window == "all":
        return None
    return WINDOW_MAP.get(window, 1095)  # default 3y


def _repo_key(owner: str, name: str) -> str:
    return f"{owner}/{name}"


def _is_trivial_fork(repo: dict) -> bool:
    """Heuristic: fork with no stars, no description change, very low activity."""
    if not repo.get("is_fork", False):
        return False
    if repo.get("stars", 0) > 2:
        return False
    return True


def collect_and_normalize(
    username: str,
    *,
    window: str = "3y",
    max_repos: int = 50,
    cache: Cache | None = None,
    token: str | None = None,
) -> Evidence:
    """Run the full collection + normalization pipeline for one user."""

    collector = GitHubCollector(cache=cache, token=token)

    try:
        return _run(collector, username, window=window, max_repos=max_repos)
    finally:
        collector.close()


def _run(
    collector: GitHubCollector,
    username: str,
    *,
    window: str,
    max_repos: int,
) -> Evidence:
    # -- Observation window ---------------------------------------------------
    now = datetime.now(timezone.utc)
    window_days = _parse_window(window)
    if window_days is not None:
        window_start = now - timedelta(days=window_days)
    else:
        window_start = datetime(2008, 1, 1, tzinfo=timezone.utc)  # GitHub epoch
    since_iso = window_start.strftime("%Y-%m-%d")

    print(f"Evaluating: {username}", file=sys.stderr)
    print(f"Window: {since_iso} → {now.date().isoformat()}", file=sys.stderr)

    # -- Profile --------------------------------------------------------------
    print("  Fetching profile …", file=sys.stderr)
    profile_raw = collector.fetch_profile(username)
    profile = Profile(**profile_raw)

    # -- Repositories ---------------------------------------------------------
    print("  Fetching owned repos …", file=sys.stderr)
    owned_raw = collector.fetch_owned_repos(username, max_repos=max_repos)

    print("  Fetching contributed-to repos …", file=sys.stderr)
    contrib_raw = collector.fetch_contributed_repos(username, max_repos=max_repos)

    # Deduplicate and merge
    seen: dict[str, dict] = {}
    for r in owned_raw + contrib_raw:
        key = _repo_key(r["owner"], r["name"])
        if key not in seen:
            seen[key] = r

    # Filter: remove trivial forks, archived
    repos_raw = [
        r for r in seen.values()
        if not _is_trivial_fork(r) and not r.get("is_archived", False)
    ]

    # Cap to max_repos, preferring owned + higher star count
    repos_raw.sort(
        key=lambda r: (r.get("is_owned_by_subject", False), r.get("stars", 0)),
        reverse=True,
    )
    repos_raw = repos_raw[:max_repos]

    repositories = [Repository(**r) for r in repos_raw]
    print(f"  Selected {len(repositories)} repositories", file=sys.stderr)

    # -- Per-repo collection --------------------------------------------------
    all_prs: list[PullRequest] = []
    all_reviews: list[Review] = []
    all_issues: list[IssueParticipation] = []
    all_releases: list[ReleaseInvolvement] = []
    counterparty_map: dict[str, dict] = defaultdict(
        lambda: {"interaction_count": 0, "repos": set(), "interaction_types": set()}
    )

    for i, repo in enumerate(repositories, 1):
        rk = _repo_key(repo.owner, repo.name)
        print(f"  [{i}/{len(repositories)}] {rk}", file=sys.stderr)

        # PRs
        prs_raw = collector.fetch_prs_by_user(
            username, repo.owner, repo.name, since=since_iso
        )
        for p in prs_raw:
            state = _PR_STATE_MAP.get(p["state"], PRState.OPEN)
            if p.get("merged_at"):
                state = PRState.MERGED
            merged_by = p.get("merged_by")
            is_self_merged: bool | None = None
            if state == PRState.MERGED and merged_by is not None:
                is_self_merged = merged_by.lower() == username.lower()
            all_prs.append(PullRequest(
                repo_owner=p["repo_owner"],
                repo_name=p["repo_name"],
                number=p["number"],
                title=p["title"],
                state=state,
                created_at=p["created_at"],
                merged_at=p.get("merged_at"),
                closed_at=p.get("closed_at"),
                additions=p.get("additions", 0),
                deletions=p.get("deletions", 0),
                changed_files=p.get("changed_files", 0),
                review_count=p.get("review_count", 0),
                comment_count=p.get("comment_count", 0),
                is_repo_owned_by_subject=repo.is_owned_by_subject,
                merged_by=merged_by,
                is_self_merged=is_self_merged,
            ))

        # Reviews by this user
        reviews_raw = collector.fetch_reviews_by_user(
            username, repo.owner, repo.name, since=since_iso
        )
        for rv in reviews_raw:
            state = _REVIEW_STATE_MAP.get(rv["state"], ReviewOutcome.COMMENTED)
            all_reviews.append(Review(
                repo_owner=rv["repo_owner"],
                repo_name=rv["repo_name"],
                pr_number=rv["pr_number"],
                state=state,
                submitted_at=rv["submitted_at"],
                body_length=rv.get("body_length", 0),
            ))
            # Track counterparties from review interactions
            # The PR author is a counterparty (we don't fetch who, but repo owner is a proxy)
            if repo.owner.lower() != username.lower():
                cp = counterparty_map[repo.owner]
                cp["interaction_count"] += 1
                cp["repos"].add(rk)
                cp["interaction_types"].add("review")

        # Issue participation
        issues_raw = collector.fetch_issue_participation(
            username, repo.owner, repo.name, since=since_iso
        )
        for iss in issues_raw:
            all_issues.append(IssueParticipation(
                repo_owner=iss["repo_owner"],
                repo_name=iss["repo_name"],
                issue_number=iss["issue_number"],
                title=iss["title"],
                is_author=iss["is_author"],
                comment_count=iss["comment_count"],
                created_at=iss["created_at"],
            ))

        # Releases (only for owned repos to keep API calls reasonable)
        if repo.is_owned_by_subject:
            releases_raw = collector.fetch_releases(
                username, repo.owner, repo.name
            )
            for rel in releases_raw:
                all_releases.append(ReleaseInvolvement(
                    repo_owner=rel["repo_owner"],
                    repo_name=rel["repo_name"],
                    tag_name=rel["tag_name"],
                    name=rel.get("name"),
                    created_at=rel["created_at"],
                    is_author=rel["is_author"],
                ))

        # Track counterparties from merged PRs
        merged_in_repo = [p for p in prs_raw if p.get("merged_at")]
        if merged_in_repo and repo.owner.lower() != username.lower():
            cp = counterparty_map[repo.owner]
            cp["interaction_count"] += len(merged_in_repo)
            cp["repos"].add(rk)
            cp["interaction_types"].add("merge")

    # -- Build counterparties -------------------------------------------------
    counterparties = [
        Counterparty(
            username=name,
            interaction_count=info["interaction_count"],
            repos=sorted(info["repos"]),
            interaction_types=sorted(info["interaction_types"]),
        )
        for name, info in counterparty_map.items()
    ]

    # -- Assemble evidence ----------------------------------------------------
    evidence = Evidence(
        profile=profile,
        observation_window_start=window_start.isoformat(),
        observation_window_end=now.isoformat(),
        repositories=repositories,
        pull_requests=all_prs,
        reviews=all_reviews,
        issue_participations=all_issues,
        release_involvements=all_releases,
        counterparties=counterparties,
        collection_metadata={
            "window": window,
            "max_repos": max_repos,
            "repos_collected": len(repositories),
            "prs_collected": len(all_prs),
            "reviews_collected": len(all_reviews),
            "issues_collected": len(all_issues),
            "releases_collected": len(all_releases),
            "counterparties_tracked": len(counterparties),
        },
    )

    print("  Collection complete.", file=sys.stderr)
    return evidence
