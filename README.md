# WorkIQ — GitHub Activity & AI Daily Summary Services

Python services for retrieving an employee's daily GitHub activity and generating a concise, manager-readable engineering summary with Groq-hosted Qwen. These modules can be integrated into a FastAPI backend or another async Python application.

> **Scope:** This README documents `github_service.py` and `summary_service.py`. It does not assume that these two modules are a complete standalone application or that API routes already exist.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [GitHub Service](#github-service)
  - [Supported Inputs](#supported-inputs)
  - [Basic Usage](#basic-github-usage)
  - [Include Line Statistics and File Changes](#include-line-statistics-and-file-changes)
  - [Example Response](#example-github-response)
- [AI Daily Summary Service](#ai-daily-summary-service)
  - [Basic Usage](#basic-summary-usage)
  - [Example Output](#example-summary-output)
  - [Fallback Behaviour](#fallback-behaviour)
- [End-to-End Example](#end-to-end-example)
- [FastAPI Integration Example](#fastapi-integration-example)
- [API and Data Reference](#api-and-data-reference)
- [Error Handling and Troubleshooting](#error-handling-and-troubleshooting)
- [Rate Limits and Performance](#rate-limits-and-performance)
- [Security Notes](#security-notes)
- [Limitations and Important Notes](#limitations-and-important-notes)
- [Testing Checklist](#testing-checklist)
- [License](#license)

---

## Overview

WorkIQ's daily activity-summary flow combines:

1. **GitHub activity retrieval** — finds commits authored by a specified GitHub username in a specified repository on a specified UTC calendar date.
2. **Optional code-change statistics** — retrieves additions, deletions, total changed lines, and changed-file details for each commit.
3. **AI-generated daily summary** — sends the retrieved activity to a Groq-compatible chat-completions endpoint using a configurable model, then returns a concise summary.
4. **Template fallback** — if `GROQ_API_KEY` is not configured, the summary service creates a basic summary without calling an LLM.

The services return Python dictionaries and strings. They do not create database records, authenticate application users, or expose HTTP routes by themselves.

## Features

### GitHub service

- Accepts repositories in `owner/repo`, HTTPS URL, `.git` URL, or SSH URL format.
- Accepts GitHub usernames with or without `@`, and profile URLs.
- Queries commits for a specified UTC date.
- Handles pagination, with a configurable maximum page count.
- Optionally retrieves per-commit line statistics.
- Optionally includes changed-file names and change counts.
- Supports `GITHUB_TOKEN` to authenticate requests and improve API rate limits.
- Distinguishes common conditions such as a missing repository, an empty repository, and no matching commits.

### AI summary service

- Combines GitHub commit messages, timestamps, file changes, and line counts into a prompt.
- Can accept task information, work hours, overtime, and a performance score from the calling application.
- Requests a concise summary with the sections `Overview`, `Commits`, `Tasks`, and `Productivity note`.
- Supports a configurable model through `GROQ_MODEL`.
- Uses a template summary when no Groq API key is available.
- Returns the summary, model used, and whether fallback mode was used.

---

## How It Works

```text
Calling application / API route
             |
             v
      github_service.py
             |
             | GitHub REST API
             v
  Commits + optional file/line statistics
             |
             v
      summary_service.py
             |
             | GROQ_API_KEY configured?
             |
       +-----+------+
       |            |
      Yes           No
       |            |
       v            v
  Groq chat API   Template summary
       |            |
       +-----+------+
             |
             v
     Summary dictionary
             |
             v
   Return to UI / save to DB
```

The caller is responsible for deciding which employee and repository to query, providing task and work-metric data, handling errors, and optionally storing or displaying the result.

---

## Project Structure

A possible project layout is:

```text
workIQ/
├── server/                     # Your application/backend, if applicable
│   ├── ...
│   └── services/
│       ├── github_service.py
│       └── summary_service.py
├── .env                        # Local secrets; do not commit
├── .env.example                # Safe environment-variable template
├── requirements.txt
└── README.md
```

The files may live in a different directory in your project. Adjust import paths accordingly.

---

## Requirements

- Python 3.10 or later is recommended because the code uses modern type annotations such as `list[dict]` and `tuple[str, str]`.
- `httpx` for asynchronous HTTP requests.
- A GitHub account and a repository accessible to the account/token used for API requests.
- A Groq API key only if you want LLM-generated summaries. Template summaries work without it.

Install the Python dependency:

```bash
python -m pip install httpx
```

If these modules are part of a FastAPI application, install the application's other dependencies separately. For example:

```bash
python -m pip install fastapi uvicorn httpx
```

### Recommended virtual environment

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install httpx
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install httpx
```

---

## Installation

1. Place `github_service.py` and `summary_service.py` in the same Python package or service directory.
2. Install the dependencies.
3. Configure the required environment variables.
4. Import the functions from your application.
5. Call the asynchronous functions using `await` from an async context.

If you use a package directory, adding an `__init__.py` file can make the package structure explicit:

```text
services/
├── __init__.py
├── github_service.py
└── summary_service.py
```

Example imports:

```python
from services.github_service import fetch_daily_commits
from services.summary_service import generate_daily_summary
```

Change `services` to match your actual package path.

---

## Environment Variables

Create a local `.env` file in the directory where your application loads environment variables:

```dotenv
# Optional but recommended for authenticated GitHub API requests
GITHUB_TOKEN=your_github_token

# Optional: required for AI-generated summaries; omit to use template mode
GROQ_API_KEY=your_groq_api_key

# Optional: model ID supported by your Groq account
GROQ_MODEL=qwen/qwen3.8-27b
```

### Variables

| Variable | Required? | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | Optional, recommended | Authenticates GitHub API requests and can raise rate limits. |
| `GROQ_API_KEY` | Optional | Enables AI-generated summaries. If absent, `generate_daily_summary()` uses a template. |
| `GROQ_MODEL` | Optional | Selects the model ID sent to the Groq chat-completions endpoint. The code's default is `qwen/qwen3.8-27b`. |

**Important:** Model availability and model IDs can change. Confirm that the configured model is currently supported by your Groq account. If Groq returns a model-not-found error, update `GROQ_MODEL`.

The modules read environment variables using `os.getenv()`. They do **not** automatically load a `.env` file. If you use `.env`, load it in your application startup (for example, with `python-dotenv`) or configure the variables in your shell, IDE, or deployment platform.

Install `python-dotenv` if you want your application to load `.env` files:

```bash
python -m pip install python-dotenv
```

Then load it early in your application's entry point:

```python
from dotenv import load_dotenv

load_dotenv()
```

Never commit real tokens or API keys to Git.

---

## GitHub Service

File: `github_service.py`

Main function:

```python
async def fetch_daily_commits(
    repo_input: str,
    profile_input: str,
    day: str | None = None,
    token: str | None = None,
    include_stats: bool = False,
    include_files: bool = False,
    max_pages: int = 10,
) -> dict:
    ...
```

### Supported Inputs

#### Repository

All of the following formats are supported:

```text
owner/repo
https://github.com/owner/repo
https://github.com/owner/repo.git
git@github.com:owner/repo.git
```

Example:

```python
repo_input = "legit-joy/Smartlearn_hackerearth"
```

#### GitHub profile

The following formats are supported:

```text
octocat
@octocat
https://github.com/octocat
```

Example:

```python
profile_input = "octocat"
```

#### Date

Use `YYYY-MM-DD`:

```python
day = "2026-10-15"
```

If omitted or set to `None`, the service uses **today's UTC date**, not necessarily the user's local date.

### Basic GitHub Usage

Run this from an async Python context:

```python
import asyncio
from services.github_service import fetch_daily_commits

async def main():
    result = await fetch_daily_commits(
        repo_input="owner/repo",
        profile_input="github-username",
        day="2026-10-15",
    )

    print("Repository:", f"{result['owner']}/{result['repo']}")
    print("Username:", result["username"])
    print("Date:", result["date"])
    print("Commit count:", result["commit_count"])

    for commit in result["commits"]:
        print(commit["sha"], commit["message"], commit["url"])

if __name__ == "__main__":
    asyncio.run(main())
```

Replace `owner/repo` and `github-username` with actual values.

### Include Line Statistics and File Changes

By default, the service returns commit metadata only. Set `include_stats=True` to retrieve additions, deletions, and total changed lines. Set `include_files=True` to include changed-file details.

```python
result = await fetch_daily_commits(
    repo_input="owner/repo",
    profile_input="github-username",
    day="2026-10-15",
    include_stats=True,
    include_files=True,
)
```

These options make additional GitHub API calls for individual commits. They provide richer information for a daily engineering summary but are slower and may consume more API quota.

You can provide a token directly:

```python
result = await fetch_daily_commits(
    repo_input="owner/repo",
    profile_input="github-username",
    day="2026-10-15",
    token="your_github_token",
)
```

Prefer setting `GITHUB_TOKEN` in the environment rather than placing secrets in source code.

### Example GitHub Response

The exact values depend on the repository and date. A response has this general structure:

```json
{
  "owner": "owner",
  "repo": "repo",
  "username": "github-username",
  "date": "2026-10-15",
  "since": "2026-10-15T00:00:00Z",
  "until": "2026-10-15T23:59:59Z",
  "commit_count": 1,
  "commits": [
    {
      "sha": "a1b2c3d",
      "full_sha": "a1b2c3d4e5f6...",
      "message": "Update API error handling",
      "timestamp": "2026-10-15T09:30:00Z",
      "url": "https://github.com/owner/repo/commit/a1b2c3d4e5f6..."
    }
  ]
}
```

When `include_stats=True`, the response also includes:

```json
{
  "totals": {
    "additions": 25,
    "deletions": 7,
    "total_changes": 32
  }
}
```

When `include_files=True`, each commit may include a `files` array. Each file object contains `filename`, `status`, `additions`, `deletions`, and `changes`.

The example values above are illustrative, not real repository results.

---

## AI Daily Summary Service

File: `summary_service.py`

Main function:

```python
async def generate_daily_summary(
    employee_id: str,
    date: str,
    commits: dict,
    tasks: list,
    work_hours: float = 8.0,
    overtime: float = 0.0,
    perf_score=None,
    groq_key: str | None = None,
    model: str | None = None,
) -> dict:
    ...
```

### What the service does

1. Receives the employee ID, date, commit data, task information, and work metrics.
2. Builds a prompt containing commit messages and, when available, file and line-change details.
3. Calls the Groq chat-completions endpoint if a Groq key is configured.
4. Returns the generated summary and model metadata.
5. Uses a deterministic template if no Groq API key is configured.

The current prompt asks the model to return exactly these Markdown sections:

```markdown
## Overview
## Commits
## Tasks
## Productivity note
```

### Basic Summary Usage

```python
from services.github_service import fetch_daily_commits
from services.summary_service import generate_daily_summary

async def create_summary():
    commits = await fetch_daily_commits(
        repo_input="owner/repo",
        profile_input="github-username",
        day="2026-10-15",
        include_stats=True,
        include_files=True,
    )

    result = await generate_daily_summary(
        employee_id="EMP001",
        date="2026-10-15",
        commits=commits,
        tasks=[],
        work_hours=7.5,
        overtime=0.5,
        perf_score=82,
    )

    print(result["summary"])
    print("Model:", result["model_used"])
    print("Fallback:", result["fallback"])
```

### Example Summary Output

The following is illustrative:

```markdown
## Overview
Worked on API error handling and updated related service logic.

## Commits
- a1b2c3d — Update API error handling; changed 25 lines added and 7 removed.
- Updated the service's error-response handling.

## Tasks
- Improved error handling for API requests.
- Updated the affected service implementation.

## Productivity note
The recorded activity focused on backend reliability. Conclusions are limited to the commits and files returned by GitHub.
```

The actual output depends on the commit data and the model. The service asks the LLM to infer tasks from code changes; those inferences should be reviewed rather than treated as verified task-tracker records.

### Fallback Behaviour

When `GROQ_API_KEY` is absent, the service does not make a Groq request. It returns a template-based summary:

```json
{
  "summary": "## Overview\n...",
  "model_used": "template (no GROQ_API_KEY)",
  "fallback": true
}
```

This is useful for local development or when AI summaries are not enabled.

When the Groq key is present, a successful response has this general shape:

```json
{
  "summary": "## Overview\n...",
  "model_used": "configured-model-id",
  "fallback": false,
  "usage": {}
}
```

The `usage` object is provided by the Groq API response and may contain token-usage details.

**Note:** The current `summary_service.py` accepts `tasks`, `work_hours`, `overtime`, and `perf_score`, but the generated LLM prompt does not actually include the work-hour, overtime, or performance-score values. Task data is also not included in the LLM user prompt, even though task details are accepted by the function and used in the template fallback. The LLM is instructed to infer tasks from code changes. If those metrics or provided tasks must influence the AI-generated summary, update `build_prompt()` to include them.

---

## End-to-End Example

This example retrieves a day's GitHub activity and then generates a summary:

```python
import asyncio
from services.github_service import fetch_daily_commits
from services.summary_service import generate_daily_summary

async def main():
    employee_id = "EMP001"
    target_date = "2026-10-15"

    commits = await fetch_daily_commits(
        repo_input="owner/repo",
        profile_input="github-username",
        day=target_date,
        include_stats=True,
        include_files=True,
    )

    summary_result = await generate_daily_summary(
        employee_id=employee_id,
        date=target_date,
        commits=commits,
        tasks=[],
        work_hours=8.0,
        overtime=0.0,
    )

    print(summary_result["summary"])
    print({
        "commit_count": commits["commit_count"],
        "model_used": summary_result["model_used"],
        "fallback": summary_result["fallback"],
    })

if __name__ == "__main__":
    asyncio.run(main())
```

Run the script from the project root, using the correct package imports:

```bash
python your_script.py
```

If you save this example in a file, replace `owner/repo` and `github-username` with valid values first.

---

## FastAPI Integration Example

The following is a minimal example of how an existing FastAPI backend could expose the services. This is an integration example; it is not included in the two service files.

```python
from datetime import date as date_type
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from services.github_service import fetch_daily_commits
from services.summary_service import generate_daily_summary

app = FastAPI(title="WorkIQ Daily Summary API")

class DailySummaryRequest(BaseModel):
    employee_id: str
    repo: str
    github_username: str
    date: date_type | None = None
    tasks: list = Field(default_factory=list)
    work_hours: float = 8.0
    overtime: float = 0.0
    perf_score: float | None = None

@app.post("/daily-summary")
async def daily_summary(request: DailySummaryRequest):
    target_date = (request.date or date_type.today()).isoformat()

    try:
        commits = await fetch_daily_commits(
            repo_input=request.repo,
            profile_input=request.github_username,
            day=target_date,
            include_stats=True,
            include_files=True,
        )

        summary = await generate_daily_summary(
            employee_id=request.employee_id,
            date=target_date,
            commits=commits,
            tasks=request.tasks,
            work_hours=request.work_hours,
            overtime=request.overtime,
            perf_score=request.perf_score,
        )

        return {
            "employee_id": request.employee_id,
            "date": target_date,
            "github": commits,
            "summary": summary,
        }
    except (ValueError, LookupError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Start the example application if it is saved as `main.py`:

```bash
uvicorn main:app --reload --port 8000
```

Open the interactive API documentation at:

```text
http://127.0.0.1:8000/docs
```

**Integration notes:**

- Install FastAPI, Uvicorn, and Pydantic if they are not already installed.
- Add authentication and authorization before exposing employee activity endpoints.
- Validate that the requesting user is allowed to access the requested employee's information.
- For a production application, map invalid input, missing repositories, upstream API errors, and rate limits to suitable HTTP status codes rather than returning every error as `400`.
- If your application uses a business date in IST, convert that date to the intended UTC interval before querying GitHub. The GitHub service currently treats the provided date as a **UTC calendar date**.

---

## API and Data Reference

### `parse_repo(repo_input)`

Parses a GitHub repository string and returns:

```python
(owner, repo)
```

Raises `ValueError` when the input cannot be parsed.

### `parse_username(profile_input)`

Parses a GitHub username or profile URL and returns the username string.

Raises `ValueError` when the input cannot be parsed.

### `parse_day(day)`

Returns a `datetime.date` from `YYYY-MM-DD`. If `day` is empty or `None`, it returns the current UTC date.

Raises `ValueError` for invalid date formats.

### `fetch_daily_commits(...)`

Returns a dictionary containing:

| Field | Description |
|---|---|
| `owner` | Repository owner. |
| `repo` | Repository name. |
| `username` | GitHub author username supplied to the query. |
| `date` | Target UTC date in `YYYY-MM-DD` format. |
| `since` | Start of the UTC date interval. |
| `until` | End of the UTC date interval. |
| `commit_count` | Number of commits returned. |
| `commits` | Commit metadata and optional details. |
| `totals` | Included when `include_stats=True`; aggregate additions, deletions, and changed lines. |

Each commit normally contains:

- `sha`: short commit SHA.
- `full_sha`: full commit SHA.
- `message`: first line of the commit message, truncated to 200 characters.
- `timestamp`: commit author timestamp from GitHub.
- `url`: GitHub commit page URL.

Optional per-commit fields:

- `additions`: added lines.
- `deletions`: removed lines.
- `total`: total changed lines reported by GitHub.
- `files`: up to 15 changed files, each with filename, status, additions, deletions, and changes.

### `generate_daily_summary(...)`

Returns a dictionary with:

| Field | Description |
|---|---|
| `summary` | Markdown summary text. |
| `model_used` | Model ID or a label indicating template mode. |
| `fallback` | `true` when template mode is used; otherwise `false`. |
| `usage` | Included after a successful Groq response, if returned by the API. |

### `build_prompt(...)`

Constructs the system and user prompts used for the Groq request.

### `template_summary(...)`

Creates a non-LLM summary from the available commit metadata. It is used when `GROQ_API_KEY` is absent.

---

## Error Handling and Troubleshooting

### 1. `Could not parse repo`

**Cause:** The repository input is not in a supported format.

**Fix:** Use `owner/repo` or a full GitHub repository URL.

```python
repo_input = "owner/repo"
```

### 2. Repository not found (404)

**Possible causes:**

- Owner or repository name is misspelled.
- Repository is private and the request is unauthenticated.
- The token does not have permission to access the repository.

**Fix:**

1. Confirm the repository URL.
2. Set `GITHUB_TOKEN` in the environment.
3. Ensure the token has the required repository access.

A 404 response can be used by GitHub to avoid revealing private repository existence to unauthorized callers.

### 3. No commits returned

This can be a valid result. Check:

- Whether the username authored commits in that repository.
- Whether the date is correct.
- Whether the date should be interpreted in UTC or IST.
- Whether the commit author identity on GitHub matches the requested account.

The GitHub API's `author` filter is based on GitHub's author association, so commits with unmatched author identities may not appear.

### 4. GitHub API rate limit exceeded (403)

**Fix:**

1. Configure `GITHUB_TOKEN`.
2. Avoid making repeated requests for the same employee, repository, and date.
3. Cache results where appropriate.
4. Avoid requesting file-level statistics unless required.

Other GitHub 403 responses may indicate permissions or organization policies rather than rate limits; inspect the returned error message.

### 5. GitHub returns 422

Check the requested username, repository, and query parameters. The service includes part of GitHub's response in the raised error to aid debugging.

### 6. Groq 401 Unauthorized

**Cause:** The Groq API key is missing, invalid, revoked, or incorrectly configured.

**Fix:** Check `GROQ_API_KEY`, restart the application after changing environment variables, and verify that the key is valid. Do not paste API keys into issue reports or logs.

### 7. Groq model not found (404)

**Cause:** The configured model ID is not available.

**Fix:** Set `GROQ_MODEL` to a model ID currently supported by your Groq account. The default in the current code is `qwen/qwen3.8-27b`, but availability may change.

### 8. Groq request fails or times out

The service uses a 60-second HTTP timeout. Check connectivity, provider status, account limits, model availability, and request size. The service raises a `RuntimeError` on request failures instead of silently switching to template mode when a Groq key is configured.

### 9. `ModuleNotFoundError: No module named 'httpx'`

Activate the correct virtual environment and run:

```bash
python -m pip install httpx
```

Confirm the IDE and terminal use the same Python interpreter.

### 10. `async` / `await` errors

These functions are asynchronous. Call them with `await` from an async function. For a simple standalone script, use `asyncio.run(main())`. Do not call `asyncio.run()` inside an already-running event loop, such as a typical async FastAPI endpoint.

---

## Rate Limits and Performance

- GitHub requests use a 15-second timeout.
- The GitHub commits endpoint returns up to 100 commits per page.
- `max_pages` defaults to 10, limiting the service to at most 1,000 commit records from pagination.
- Requesting `include_stats=True` and/or `include_files=True` makes an additional request for each commit in the fetched batch.
- The Groq request uses a 60-second timeout and a maximum of 800 output tokens.
- The summary prompt includes at most 20 commits and up to 10 file entries per included commit.
- The template summary includes at most 10 commits and up to 8 file entries per commit.

For larger deployments, consider caching daily GitHub results, limiting concurrent requests, retrying transient upstream errors with backoff, and recording rate-limit headers. Do not retry invalid credentials or invalid model IDs indefinitely.

---

## Security Notes

- Store `GITHUB_TOKEN` and `GROQ_API_KEY` in environment variables or a secrets manager.
- Never commit `.env` files containing real secrets.
- Use the minimum permissions needed for GitHub repository access.
- Do not expose tokens in API responses, frontend code, logs, screenshots, or error messages.
- Protect employee activity endpoints with authentication and authorization.
- Treat generated summaries as potentially sensitive employee information.
- Review AI-generated inferences before using them for formal performance decisions.
- Do not treat commit counts or lines changed as a complete or objective measure of employee productivity.

A safe `.gitignore` entry is:

```gitignore
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
```

If your project already has a `.gitignore`, merge these entries rather than replacing the entire file.

---

## Limitations and Important Notes

1. **UTC date boundaries:** `fetch_daily_commits()` queries `00:00:00Z` through `23:59:59Z`. If the application defines a workday in IST or another timezone, convert the business-day interval to UTC before querying.
2. **Author identity:** GitHub's author filter may not find commits whose author identity is not associated with the requested GitHub account.
3. **Private repositories:** Access depends on the token and its repository permissions.
4. **Commit statistics:** Line counts are not a reliable standalone productivity metric. Generated files, formatting, deletions, and refactoring can distort them.
5. **AI-generated tasks:** The model may infer tasks from commit messages and changed files, but those inferred tasks are not verified task-tracker records.
6. **Metrics passed to the summary function:** In the current implementation, `work_hours`, `overtime`, and `perf_score` are accepted but are not inserted into the LLM prompt. The LLM path also does not include the provided `tasks` list. The template path uses commit data and does not meaningfully evaluate those metrics.
7. **Fallback conditions:** Template fallback occurs when no Groq key is configured. A configured but invalid key or unsupported model causes an error rather than automatic fallback.
8. **No persistence:** These modules do not store results in MongoDB or another database.
9. **No scheduler:** They do not run automatically every day. Your backend or job scheduler must invoke them.
10. **No employee verification:** The services do not prove that a GitHub username belongs to a particular employee. Your application must maintain and validate that mapping.
11. **No complete repository audit:** The service queries a particular repository and date, not all repositories an employee may have contributed to.

---

## Testing Checklist

Before integrating this into a production application, verify:

- [ ] A valid `owner/repo` input parses correctly.
- [ ] A full HTTPS URL and `.git` URL parse correctly.
- [ ] A GitHub profile URL and bare username parse correctly.
- [ ] A valid date such as `2026-10-15` is accepted.
- [ ] Invalid dates produce a clear `ValueError`.
- [ ] A day with commits returns the expected author-filtered results.
- [ ] A day without matching commits returns a zero count.
- [ ] Private repository access works with a correctly permissioned token.
- [ ] Rate-limit and permission errors are handled appropriately.
- [ ] `include_stats=True` returns line totals.
- [ ] `include_files=True` returns file details.
- [ ] No `GROQ_API_KEY` produces a template summary.
- [ ] A valid Groq key and model produce an AI summary.
- [ ] Invalid Groq credentials and unsupported models produce clear errors.
- [ ] Employee authorization is enforced in the application/API layer.
- [ ] The application's date/timezone policy matches the UTC interval used by the GitHub query.

---

## License

Add the license that applies to your project before publishing or distributing this code. No license is inferred by this README.
