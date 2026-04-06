"""CLI entry point for opportunity-txt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cache import FileCache
from .errors import AuthenticationError, OpportunityTxtError
from .evaluate import evaluate_github_profile
from .models import EvaluateGitHubProfileRequest

VALID_WINDOWS = ("1y", "2y", "3y", "5y", "all")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="opportunity-txt",
        description="Evaluate a GitHub contributor from public evidence.",
    )
    parser.add_argument(
        "username",
        help="GitHub username to evaluate.",
    )
    parser.add_argument(
        "--window",
        default="3y",
        choices=VALID_WINDOWS,
        help="Observation window (default: 3y).",
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=50,
        help="Maximum repositories to evaluate (default: 50).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory for output artifacts (default: output).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass local cache and re-fetch all data.",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=".cache",
        help="Directory for API response cache (default: .cache).",
    )
    parser.add_argument(
        "--mode",
        default="user",
        choices=("user", "debug"),
        help="Run mode (default: user).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Write structured JSON result to output dir.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache = FileCache(
        cache_dir=Path(args.cache_dir),
        enabled=not args.refresh,
    )

    request = EvaluateGitHubProfileRequest(
        github_username=args.username,
        observation_window=args.window,
        max_repositories=args.max_repos,
        include_markdown_report=True,
        include_summary=True,
        include_raw_evidence=args.mode == "debug",
        include_signals=args.mode == "debug",
        run_mode=args.mode,
    )

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  opportunity-txt — Contributor Evaluation", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    try:
        result = evaluate_github_profile(request, cache=cache)
    except AuthenticationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except OpportunityTxtError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Save outputs
    username = args.username
    report_path = output_dir / f"{username}_report.md"

    if result.markdown_report:
        report_path.write_text(result.markdown_report)

    if args.json_output:
        json_path = output_dir / f"{username}_result.json"
        json_path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
        print(f"    Result:   {json_path}", file=sys.stderr)

    print(f"\n  Outputs saved:", file=sys.stderr)
    print(f"    Report:   {report_path}", file=sys.stderr)

    # Print summary to stdout
    if result.summary:
        s = result.summary
        print(f"\n{'='*50}")
        print(f"  {s.username} — Evaluation Summary")
        print(f"{'='*50}\n")
        for d in s.dimensions:
            if d.status == "not_reliably_observable":
                print(f"  {d.name:<30} {'N/R Observable':<15}")
            else:
                print(f"  {d.name:<30} {d.score_label:<15} (confidence: {d.confidence_label})")
        print()
        if s.primary_domain:
            print(f"  Primary domain: {s.primary_domain}")
            if s.secondary_domains:
                print(f"  Secondary: {', '.join(s.secondary_domains)}")
        print()


if __name__ == "__main__":
    main()
