"""GitHub GraphQL data collection module.

Gathers profile, repository, PR, review, issue, and release data for a
single GitHub user using the GraphQL API exclusively.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .cache import Cache
from .errors import AuthenticationError, CollectionError, RateLimitError

GRAPHQL_URL = "https://api.github.com/graphql"
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, multiplied by attempt number


def _load_dotenv() -> None:
    """Load variables from a .env file if it exists (no third-party dependency)."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            break


def _resolve_token(explicit_token: str | None = None) -> str:
    """Resolve GitHub token: explicit > env var > .env file.

    Raises AuthenticationError if no token can be found.
    """
    if explicit_token:
        return explicit_token
    _load_dotenv()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise AuthenticationError(
            "GitHub token not provided. Pass github_token explicitly, "
            "set GITHUB_TOKEN in the environment, or add it to a .env file."
        )
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
    }


class GitHubCollector:
    """Collects public GitHub data for a single user via GraphQL."""

    def __init__(self, cache: Cache | None = None, token: str | None = None):
        self._token = _resolve_token(token)
        self._client = httpx.Client(timeout=30.0)
        self._cache = cache or Cache(enabled=False)

    # ------------------------------------------------------------------
    # Low-level GraphQL helpers
    # ------------------------------------------------------------------

    def _execute(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        variables = variables or {}
        cached = self._cache.get(query, variables)
        if cached is not None:
            return cached

        payload = {"query": query, "variables": variables}
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._client.post(
                    GRAPHQL_URL,
                    json=payload,
                    headers=_headers(self._token),
                )
                if resp.status_code == 403:
                    # Likely rate-limited
                    reset = resp.headers.get("X-RateLimit-Reset")
                    wait = max(int(reset) - int(time.time()), 1) if reset else 60
                    print(f"  Rate-limited. Waiting {wait}s …", file=sys.stderr)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if "errors" in data:
                    msgs = [e.get("message", "") for e in data["errors"]]
                    raise CollectionError(f"GraphQL errors: {'; '.join(msgs)}")
                self._cache.put(query, variables, data["data"])
                return data["data"]
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                time.sleep(RETRY_BACKOFF * attempt)
            except httpx.TransportError as exc:
                last_exc = exc
                time.sleep(RETRY_BACKOFF * attempt)

        raise CollectionError(f"GitHub API request failed after {MAX_RETRIES} retries") from last_exc

    def _paginate(
        self,
        query: str,
        variables: dict[str, Any],
        path: list[str],
        max_items: int = 500,
    ) -> list[dict]:
        """Auto-paginate a connection that exposes pageInfo + edges."""
        items: list[dict] = []
        variables = {**variables, "cursor": None}

        while True:
            data = self._execute(query, variables)
            node = data
            for key in path:
                node = node[key]
            edges = node.get("edges", [])
            for edge in edges:
                items.append(edge["node"])
                if len(items) >= max_items:
                    return items
            page_info = node.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break
            variables["cursor"] = page_info["endCursor"]

        return items

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    _PROFILE_QUERY = """
    query($login: String!) {
      user(login: $login) {
        login
        url
        createdAt
        repositories(privacy: PUBLIC) { totalCount }
        followers { totalCount }
        following { totalCount }
        bio
        name
        company
        location
      }
    }
    """

    def fetch_profile(self, username: str) -> dict:
        data = self._execute(self._PROFILE_QUERY, {"login": username})
        u = data["user"]
        return {
            "username": u["login"],
            "url": u["url"],
            "created_at": u["createdAt"],
            "public_repo_count": u["repositories"]["totalCount"],
            "followers": u["followers"]["totalCount"],
            "following": u["following"]["totalCount"],
            "bio": u.get("bio"),
            "name": u.get("name"),
            "company": u.get("company"),
            "location": u.get("location"),
        }

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    _REPOS_QUERY = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(
          first: 50
          after: $cursor
          privacy: PUBLIC
          orderBy: {field: UPDATED_AT, direction: DESC}
          ownerAffiliations: OWNER
        ) {
          pageInfo { hasNextPage endCursor }
          edges {
            node {
              name
              owner { login }
              url
              description
              primaryLanguage { name }
              repositoryTopics(first: 20) { edges { node { topic { name } } } }
              stargazerCount
              forkCount
              watchers { totalCount }
              issues(states: OPEN) { totalCount }
              createdAt
              updatedAt
              isArchived
              isFork
              isTemplate
              defaultBranchRef { name }
              licenseInfo { spdxId }
              diskUsage
            }
          }
        }
      }
    }
    """

    def fetch_owned_repos(self, username: str, max_repos: int = 100) -> list[dict]:
        nodes = self._paginate(
            self._REPOS_QUERY,
            {"login": username},
            ["user", "repositories"],
            max_items=max_repos,
        )
        return [self._normalize_repo(n, username) for n in nodes]

    @staticmethod
    def _normalize_repo(node: dict, subject: str) -> dict:
        topics = [
            e["node"]["topic"]["name"]
            for e in node.get("repositoryTopics", {}).get("edges", [])
        ]
        return {
            "name": node["name"],
            "owner": node["owner"]["login"],
            "url": node["url"],
            "description": node.get("description"),
            "primary_language": (node.get("primaryLanguage") or {}).get("name"),
            "topics": topics,
            "stars": node.get("stargazerCount", 0),
            "forks": node.get("forkCount", 0),
            "watchers": node.get("watchers", {}).get("totalCount", 0),
            "open_issues": node.get("issues", {}).get("totalCount", 0),
            "created_at": node["createdAt"],
            "updated_at": node["updatedAt"],
            "is_archived": node.get("isArchived", False),
            "is_fork": node.get("isFork", False),
            "is_template": node.get("isTemplate", False),
            "default_branch": (node.get("defaultBranchRef") or {}).get("name", "main"),
            "license_name": (node.get("licenseInfo") or {}).get("spdxId"),
            "is_owned_by_subject": node["owner"]["login"].lower() == subject.lower(),
            "disk_usage_kb": node.get("diskUsage"),
        }

    # ------------------------------------------------------------------
    # Contributed-to repos (repos where subject has PRs but doesn't own)
    # ------------------------------------------------------------------

    _CONTRIBUTED_REPOS_QUERY = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositoriesContributedTo(
          first: 50
          after: $cursor
          contributionTypes: [COMMIT, PULL_REQUEST, PULL_REQUEST_REVIEW, ISSUE]
          privacy: PUBLIC
        ) {
          pageInfo { hasNextPage endCursor }
          edges {
            node {
              name
              owner { login }
              url
              description
              primaryLanguage { name }
              repositoryTopics(first: 20) { edges { node { topic { name } } } }
              stargazerCount
              forkCount
              watchers { totalCount }
              issues(states: OPEN) { totalCount }
              createdAt
              updatedAt
              isArchived
              isFork
              isTemplate
              defaultBranchRef { name }
              licenseInfo { spdxId }
              diskUsage
            }
          }
        }
      }
    }
    """

    def fetch_contributed_repos(self, username: str, max_repos: int = 100) -> list[dict]:
        nodes = self._paginate(
            self._CONTRIBUTED_REPOS_QUERY,
            {"login": username},
            ["user", "repositoriesContributedTo"],
            max_items=max_repos,
        )
        return [self._normalize_repo(n, username) for n in nodes]

    # ------------------------------------------------------------------
    # Pull requests authored by subject in a given repo
    # ------------------------------------------------------------------

    _PRS_QUERY = """
    query($query: String!, $cursor: String) {
      search(query: $query, type: ISSUE, first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            ... on PullRequest {
              number
              title
              state
              createdAt
              mergedAt
              closedAt
              additions
              deletions
              changedFiles
              reviews { totalCount }
              comments { totalCount }
              mergedBy { login }
              repository {
                name
                owner { login }
              }
            }
          }
        }
      }
    }
    """

    def fetch_prs_by_user(
        self,
        username: str,
        repo_owner: str,
        repo_name: str,
        since: str | None = None,
        max_items: int = 200,
    ) -> list[dict]:
        q = f"type:pr author:{username} repo:{repo_owner}/{repo_name}"
        if since:
            q += f" created:>={since}"
        nodes = self._paginate(
            self._PRS_QUERY,
            {"query": q},
            ["search"],
            max_items=max_items,
        )
        results = []
        for n in nodes:
            if not n.get("number"):
                continue
            repo = n.get("repository", {})
            results.append({
                "repo_owner": repo.get("owner", {}).get("login", repo_owner),
                "repo_name": repo.get("name", repo_name),
                "number": n["number"],
                "title": n.get("title", ""),
                "state": n["state"].lower(),
                "created_at": n["createdAt"],
                "merged_at": n.get("mergedAt"),
                "closed_at": n.get("closedAt"),
                "additions": n.get("additions", 0),
                "deletions": n.get("deletions", 0),
                "changed_files": n.get("changedFiles", 0),
                "review_count": n.get("reviews", {}).get("totalCount", 0),
                "comment_count": n.get("comments", {}).get("totalCount", 0),
                "merged_by": (n.get("mergedBy") or {}).get("login"),
            })
        return results

    # ------------------------------------------------------------------
    # Reviews authored by subject in a given repo
    # ------------------------------------------------------------------

    _REVIEWS_QUERY = """
    query($query: String!, $cursor: String) {
      search(query: $query, type: ISSUE, first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            ... on PullRequest {
              number
              repository {
                name
                owner { login }
              }
              reviews(first: 50, author: $author) {
                edges {
                  node {
                    state
                    submittedAt
                    body
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    # Because the reviews(author:) filter requires an ID not login in
    # search context, we use a different approach: fetch PRs the user
    # reviewed via the search API.

    _REVIEWED_PRS_QUERY = """
    query($query: String!, $cursor: String) {
      search(query: $query, type: ISSUE, first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            ... on PullRequest {
              number
              repository {
                name
                owner { login }
              }
              reviews(first: 100) {
                edges {
                  node {
                    author { login }
                    state
                    submittedAt
                    body
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    def fetch_reviews_by_user(
        self,
        username: str,
        repo_owner: str,
        repo_name: str,
        since: str | None = None,
        max_items: int = 200,
    ) -> list[dict]:
        q = f"type:pr reviewed-by:{username} repo:{repo_owner}/{repo_name}"
        if since:
            q += f" created:>={since}"
        nodes = self._paginate(
            self._REVIEWED_PRS_QUERY,
            {"query": q},
            ["search"],
            max_items=max_items,
        )
        results = []
        for n in nodes:
            if not n.get("number"):
                continue
            repo = n.get("repository", {})
            reviews = n.get("reviews", {}).get("edges", [])
            for edge in reviews:
                rv = edge["node"]
                if (rv.get("author") or {}).get("login", "").lower() != username.lower():
                    continue
                body = rv.get("body") or ""
                results.append({
                    "repo_owner": repo.get("owner", {}).get("login", repo_owner),
                    "repo_name": repo.get("name", repo_name),
                    "pr_number": n["number"],
                    "state": rv["state"].lower(),
                    "submitted_at": rv["submittedAt"],
                    "body_length": len(body),
                })
        return results

    # ------------------------------------------------------------------
    # Issue participation
    # ------------------------------------------------------------------

    _ISSUES_QUERY = """
    query($query: String!, $cursor: String) {
      search(query: $query, type: ISSUE, first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            ... on Issue {
              number
              title
              author { login }
              createdAt
              comments(first: 100) {
                edges {
                  node {
                    author { login }
                  }
                }
              }
              repository {
                name
                owner { login }
              }
            }
          }
        }
      }
    }
    """

    def fetch_issue_participation(
        self,
        username: str,
        repo_owner: str,
        repo_name: str,
        since: str | None = None,
        max_items: int = 100,
    ) -> list[dict]:
        # Issues authored or commented on by user
        q = f"type:issue involves:{username} repo:{repo_owner}/{repo_name}"
        if since:
            q += f" created:>={since}"
        nodes = self._paginate(
            self._ISSUES_QUERY,
            {"query": q},
            ["search"],
            max_items=max_items,
        )
        results = []
        for n in nodes:
            if not n.get("number"):
                continue
            repo = n.get("repository", {})
            author_login = (n.get("author") or {}).get("login", "")
            is_author = author_login.lower() == username.lower()
            comment_count = sum(
                1
                for e in n.get("comments", {}).get("edges", [])
                if (e["node"].get("author") or {}).get("login", "").lower() == username.lower()
            )
            results.append({
                "repo_owner": repo.get("owner", {}).get("login", repo_owner),
                "repo_name": repo.get("name", repo_name),
                "issue_number": n["number"],
                "title": n.get("title", ""),
                "is_author": is_author,
                "comment_count": comment_count,
                "created_at": n["createdAt"],
            })
        return results

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------

    _RELEASES_QUERY = """
    query($owner: String!, $name: String!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        releases(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          edges {
            node {
              tagName
              name
              createdAt
              author { login }
            }
          }
        }
      }
    }
    """

    def fetch_releases(
        self,
        username: str,
        repo_owner: str,
        repo_name: str,
        max_items: int = 50,
    ) -> list[dict]:
        nodes = self._paginate(
            self._RELEASES_QUERY,
            {"owner": repo_owner, "name": repo_name},
            ["repository", "releases"],
            max_items=max_items,
        )
        results = []
        for n in nodes:
            author_login = (n.get("author") or {}).get("login", "")
            results.append({
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "tag_name": n.get("tagName", ""),
                "name": n.get("name"),
                "created_at": n["createdAt"],
                "is_author": author_login.lower() == username.lower(),
            })
        return results

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()
