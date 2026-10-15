"""
Daily work summary via Groq (Qwen) LLM.

Combines:
  - GitHub commits of the day (from github_service)
  - Tasks completed (passed in by caller / dashboard)
  - Work metrics (workHours, overtime, performance score)

Calls Groq OpenAI-compatible endpoint:
  POST https://api.groq.com/openai/v1/chat/completions
  model default: qwen/qwen3-32b  (Groq's Qwen3 32B - closest to "qwen 3.x".
  Override with env GROQ_MODEL if your account has another id, e.g. qwen3.8 variant.)

Auth: env GROQ_API_KEY (never hardcode). Falls back to template summary if no key.
"""

import os
import json
from typing import Optional
import httpx

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
_TIMEOUT = 60.0


def _groq_key(explicit: Optional[str] = None) -> str:
    return (explicit or os.getenv("GROQ_API_KEY", "") or "").strip()


def build_prompt(employee_id: str, date: str, commits: dict, tasks: list,
                 work_hours: float, overtime: float, perf_score=None) -> tuple[str, str]:
    commit_lines = []
    for c in commits.get("commits", [])[:20]:
        commit_lines.append(f"- {c.get('sha','')} | {c.get('message','')} ({c.get('timestamp','')})")
    commits_txt = "\n".join(commit_lines) if commit_lines else "(no commits that day)"

    task_lines = []
    for t in (tasks or [])[:20]:
        if isinstance(t, str):
            task_lines.append(f"- {t}")
        elif isinstance(t, dict):
            title = t.get("title") or t.get("name") or t.get("task") or str(t)
            status = t.get("status", "done")
            desc = t.get("description", "")
            task_lines.append(f"- [{status}] {title}" + (f": {desc}" if desc else ""))
    tasks_txt = "\n".join(task_lines) if task_lines else "(no task details provided)"

    system = (
        "You are a concise engineering manager assistant. "
        "Summarize an employee's day from GitHub commits + completed tasks. "
        "Be factual, no hallucination. If no commits/tasks, say so plainly. "
        "Keep it short, bullet points, manager-readable."
    )
    user = f"""Employee: {employee_id}
Date: {date}
Repo: {commits.get('owner','')}/{commits.get('repo','')} (user: {commits.get('username','')})
Work hours: {work_hours}h, Overtime: {overtime}h, Commits: {commits.get('commit_count',0)}, Tasks done: {len(tasks or [])}, Performance score: {perf_score if perf_score is not None else 'n/a'}

COMMITS THAT DAY:
{commits_txt}

TASKS COMPLETED:
{tasks_txt}

Write a daily summary with EXACTLY these markdown sections:
## Overview (2-3 lines)
## Commits (what code changed, 1 line per commit, group if many)
## Tasks (what tasks were completed)
## Productivity note (1-2 lines: pace, overtime, focus)
"""
    return system, user


def template_summary(employee_id: str, date: str, commits: dict, tasks: list,
                     work_hours: float, overtime: float, perf_score=None) -> str:
    n_c = commits.get("commit_count", 0)
    n_t = len(tasks or [])
    lines = [f"## Overview", f"{employee_id} did {n_c} commit(s) and completed {n_t} task(s) on {date} "
             f"({work_hours}h + {overtime}h overtime). " +
             (f"Performance score {perf_score}." if perf_score is not None else "")]
    lines.append("## Commits")
    if n_c == 0:
        lines.append("- No commits in this repo that day.")
    else:
        for c in commits.get("commits", [])[:10]:
            lines.append(f"- {c.get('sha','')} {c.get('message','')}")
    lines.append("## Tasks")
    if n_t == 0:
        lines.append("- No task details provided.")
    else:
        for t in tasks[:10]:
            lines.append(f"- {t if isinstance(t, str) else t.get('title', str(t))}")
    lines.append("## Productivity note")
    lines.append(f"- {'Overtime logged' if overtime and overtime > 0 else 'No overtime'}; "
                 f"{'active day' if n_c + n_t > 0 else 'no recorded output'}.")
    return "\n".join(lines)


async def generate_daily_summary(employee_id: str, date: str, commits: dict, tasks: list,
                                 work_hours: float = 8.0, overtime: float = 0.0,
                                 perf_score=None, groq_key: Optional[str] = None,
                                 model: Optional[str] = None) -> dict:
    """
    Returns {summary, model_used, fallback: bool}
    Uses Groq if GROQ_API_KEY present, else template fallback.
    """
    key = _groq_key(groq_key)
    model_id = (model or DEFAULT_MODEL).strip()
    if not key:
        return {
            "summary": template_summary(employee_id, date, commits, tasks, work_hours, overtime, perf_score),
            "model_used": "template (no GROQ_API_KEY)",
            "fallback": True,
        }

    system, user = build_prompt(employee_id, date, commits, tasks, work_hours, overtime, perf_score)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 800,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(GROQ_API_URL, headers=headers, json=payload)
        if r.status_code == 401:
            raise RuntimeError("Groq 401 Unauthorized - invalid GROQ_API_KEY.")
        if r.status_code == 404 and "model" in r.text.lower():
            raise RuntimeError(f"Groq 404 model not found '{model_id}'. Set GROQ_MODEL env to a valid id (e.g. qwen/qwen3-32b). Raw: {r.text[:300]}")
        if r.status_code != 200:
            raise RuntimeError(f"Groq error {r.status_code}: {r.text[:400]}")
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        return {"summary": text, "model_used": model_id, "fallback": False, "usage": data.get("usage", {})}
    except (RuntimeError, KeyError, json.JSONDecodeError) as e:
        # Return error clearly instead of silently falling back, so caller knows key/model issue
        raise RuntimeError(str(e))
    except Exception as e:
        raise RuntimeError(f"Groq call failed: {e}")
