"""
GitHub Daily Commits Service
Given: github repo (owner/repo or URL) + employee github profile (username or URL) + date
Returns: how many commits that person did on that day in that repo.

Uses GitHub REST API:
  GET /repos/{owner}/{repo}/commits?author={username}&since={ISO}&until={ISO}

No extra deps beyond httpx (already available). Supports GITHUB_TOKEN env for rate limits.
"""

import os
import re
from datetime import datetime, timezone, date as date_cls
from typing import Optional
import httpx

GITHUB_API = "https://api.github.com"
_TIMEOUT = 15.0


def parse_repo(repo_input: str) -> tuple[str, str]:
    """
    Accepts:
      - "owner/repo"
      - "https://github.com/owner/repo"
      - "https://github.com/owner/repo.git"
      - "git@github.com:owner/repo.git"
    Returns (owner, repo)
    """
    s = (repo_input or "").strip().strip("/")
    if not s:
        raise ValueError("repo is empty")

    # SSH form
    m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(\.git)?$", s)
    if m:
        return m.group(1), m.group(2)

    # URL form
    m = re.match(r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?(?:[?#].*)?$", s)
    if m:
        return m.group(1), m.group(2)

    # short form
    m = re.match(r"([^/\s]+)/([^/\s]+?)(?:\.git)?$", s)
    if m:
        owner, repo = m.group(1), m.group(2)
        if owner in ("http:", "https:"):
            raise ValueError(f"Could not parse repo from '{repo_input}'. Use 'owner/repo' or full GitHub URL.")
        return owner, repo

    raise ValueError(f"Could not parse repo from '{repo_input}'. Use 'owner/repo' or full GitHub URL.")


def parse_username(profile_input: str) -> str:
    """
    Accepts:
      - "octocat"
      - "@octocat"
      - "https://github.com/octocat"
      - "https://github.com/octocat/"
    Returns bare username.
    """
    s = (profile_input or "").strip().strip("/")
    if not s:
        raise ValueError("github profile/username is empty")
    s = s.lstrip("@")

    m = re.match(r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/?.*$", s)
    if m:
        return m.group(1).lstrip("@")

    m = re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,37}[A-Za-z0-9])?(?:\[bot\])?$", s)
    if m:
        return s

    # Bot accounts like dependabot[bot], github-actions[bot]
    m = re.match(r"^[A-Za-z0-9\-_\[\]]+$", s)
    if m:
        return s

    raise ValueError(f"Could not parse github username from '{profile_input}'.")


def parse_day(day: Optional[str]) -> date_cls:
    """Accepts YYYY-MM-DD or None (= today UTC)."""
    if not day:
        return datetime.now(timezone.utc).date()
    try:
        return datetime.strptime(day.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date '{day}'. Use YYYY-MM-DD.")


def _headers(token: Optional[str] = None) -> dict:
    h = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "workIQ-ml-service",
    }
    tok = token or os.getenv("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


async def fetch_daily_commits(
    repo_input: str,
    profile_input: str,
    day: Optional[str] = None,
    token: Optional[str] = None,
    include_stats: bool = False,
    max_pages: int = 10,
) -> dict:
    """
    Core function. Returns dict:
    {
      owner, repo, username, date,
      commit_count,
      commits: [{sha, message, timestamp, url}],
      totals: {additions, deletions, total}  # only if include_stats=True
    }
    """
    owner, repo = parse_repo(repo_input)
    username = parse_username(profile_input)
    target = parse_day(day)

    since = f"{target.isoformat()}T00:00:00Z"
    until = f"{target.isoformat()}T23:59:59Z"

    commits: list[dict] = []
    total_add = total_del = total_ch = 0

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers(token)) as client:
        page = 1
        while page <= max_pages:
            url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
            params = {
                "author": username,
                "since": since,
                "until": until,
                "per_page": 100,
                "page": page,
            }
            r = await client.get(url, params=params)

            if r.status_code == 404:
                # Distinguish repo-not-found vs no-commits: probe repo endpoint
                repo_check = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}")
                if repo_check.status_code == 404:
                    raise LookupError(f"Repo '{owner}/{repo}' not found (404). Check owner/repo spelling or private repo needs GITHUB_TOKEN.")
                # Repo exists but no commits for this author/day -> return 0
                break
            if r.status_code == 409:
                # Empty repo (GitHub returns 409 Conflict)
                break
            if r.status_code == 403 and "rate limit" in r.text.lower():
                raise RuntimeError("GitHub API rate limit exceeded. Set GITHUB_TOKEN env var to raise limit, or retry later.")
            if r.status_code == 422:
                raise ValueError(f"GitHub rejected request (422): {r.text[:300]}. Check author username '{username}'.")
            if r.status_code != 200:
                raise RuntimeError(f"GitHub API error {r.status_code}: {r.text[:300]}")

            batch = r.json()
            if not batch:
                break

            for c in batch:
                sha = c.get("sha", "")[:7]
                full_sha = c.get("sha", "")
                commit_obj = c.get("commit", {})
                author_obj = commit_obj.get("author", {}) or {}
                commits.append({
                    "sha": sha,
                    "full_sha": full_sha,
                    "message": (commit_obj.get("message", "") or "").split("\n")[0][:200],
                    "timestamp": author_obj.get("date", ""),
                    "url": c.get("html_url", ""),
                })

            # Optional per-commit line stats (extra API calls, slower)
            if include_stats:
                for item in commits[len(commits) - len(batch):]:
                    try:
                        dr = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{item['full_sha']}")
                        if dr.status_code == 200:
                            st = (dr.json().get("stats") or {})
                            total_add += int(st.get("additions", 0))
                            total_del += int(st.get("deletions", 0))
                            total_ch += int(st.get("total", 0))
                    except Exception:
                        pass

            # Pagination: GitHub returns <=100 per page; if less, done.
            # Also respect Link header for "next".
            link = r.headers.get("Link", "")
            if len(batch) < 100 or 'rel="next"' not in link:
                # If exactly 100 but no Link header, be safe and try next page once
                if len(batch) < 100:
                    break
                if 'rel="next"' not in link and len(batch) == 100:
                    page += 1
                    if page > max_pages:
                        break
                    continue
                break
            page += 1

    out = {
        "owner": owner,
        "repo": repo,
        "username": username,
        "date": target.isoformat(),
        "since": since,
        "until": until,
        "commit_count": len(commits),
        "commits": commits,
    }
    if include_stats:
        out["totals"] = {"additions": total_add, "deletions": total_del, "total_changes": total_ch}
    return out
