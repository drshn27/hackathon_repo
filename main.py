"""
NexusAI ML Service - Performance Prediction using trained PyTorch model

Loads the trained EmployeeNN model and scaler from disk.
Accepts DailyMetrics values and returns predicted performance score.
"""

import os
import sys
import joblib
import numpy as np
import torch
import torch.nn as nn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
import pandas as pd
from typing import Optional
from github_service import fetch_daily_commits
from summary_service import generate_daily_summary, DEFAULT_MODEL

# ─── Paths ───────────────────────────────────────────────────────────────────
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(MODEL_DIR, "best_model.pth")
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.pkl")

# ─── Exact PyTorch architecture from employee_nn_notebook_finall.py ──────────
# IMPORTANT: This must EXACTLY match the training architecture.
# Changes to layer sizes, activations, dropout, or BatchNorm will break
# torch.load(state_dict) because weight shapes won't match.
class EmployeeNN(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.3),

            nn.Linear(128, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.2),

            nn.Linear(64, 32),
            nn.ReLU(),

            nn.Linear(32, 1)
        )

    def forward(self, x):
        return self.network(x)


# ─── Feature configuration ──────────────────────────────────────────────────
# Order MUST match the training data columns (after dropping emp_name/emp_email):
#   daily_work_hours, overtime_hours, daily_commits, tasks_completed
FEATURE_NAMES = ["daily_work_hours", "overtime_hours", "daily_commits", "tasks_completed"]
INPUT_DIM = len(FEATURE_NAMES)  # 4

# ─── Load model and scaler at startup ────────────────────────────────────────
device = torch.device("cpu")

model = EmployeeNN(INPUT_DIM)
try:
    state_dict = torch.load(MODEL_PATH, map_location=device, weights_only=True)
    model.load_state_dict(state_dict)
    model.eval()
    print(f"[ML Service] Loaded best_model.pth with {sum(p.numel() for p in model.parameters())} parameters")
except Exception as e:
    print(f"[ML Service] FATAL: Could not load model from {MODEL_PATH}: {e}", file=sys.stderr)
    model = None

scaler = None
try:
    scaler = joblib.load(SCALER_PATH)
    print(f"[ML Service] Loaded scaler.pkl")
except Exception as e:
    print(f"[ML Service] FATAL: Could not load scaler from {SCALER_PATH}: {e}", file=sys.stderr)


# ─── FastAPI app ─────────────────────────────────────────────────────────────
app = FastAPI(title="NexusAI PyTorch Performance Prediction Service")


class EmployeeMetrics(BaseModel):
    workHours: float
    overtimeHours: float
    commits: int
    tasksCompleted: int


class PredictionRequest(BaseModel):
    employeeId: str
    metrics: EmployeeMetrics


class PredictionResponse(BaseModel):
    employeeId: str
    score: float
    raw_score: float
    factors: dict
    timestamp: str


@app.get("/")
def read_root():
    return {
        "message": "NexusAI PyTorch ML Service",
        "version": "2.0.0",
        "model_loaded": model is not None,
        "scaler_loaded": scaler is not None,
        "input_features": FEATURE_NAMES,
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy" if model is not None and scaler is not None else "degraded",
        "model_loaded": model is not None,
        "scaler_loaded": scaler is not None,
    }


@app.post("/predict", response_model=PredictionResponse)
async def predict_single(request: PredictionRequest):
    """
    Predict performance score using the trained PyTorch model.
    Maps DailyMetrics field names → exact feature order + scaler → model.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    if scaler is None:
        raise HTTPException(status_code=503, detail="Scaler not loaded")

    try:
        # Build feature array in EXACT order the model was trained on
        raw = np.array([[
            request.metrics.workHours,       # daily_work_hours
            request.metrics.overtimeHours,   # overtime_hours
            request.metrics.commits,         # daily_commits
            request.metrics.tasksCompleted,  # tasks_completed
        ]], dtype=np.float32)

        # Apply the same scaler used during training
        scaled = scaler.transform(raw)

        # Convert to tensor and predict
        with torch.no_grad():
            tensor = torch.tensor(scaled, dtype=torch.float32)
            prediction = model(tensor)
            raw_score = prediction.item()

        # Clamp / round to 0–100
        score = round(raw_score)
        if score > 100:
            score = 100
        if score < 0:
            score = 0

        # Provide factor breakdown (how each metric contributes)
        factors = {
            "workHours": request.metrics.workHours,
            "overtimeHours": request.metrics.overtimeHours,
            "commits": request.metrics.commits,
            "tasksCompleted": request.metrics.tasksCompleted,
        }

        return PredictionResponse(
            employeeId=request.employeeId,
            score=score,
            raw_score=round(raw_score, 4),
            factors=factors,
            timestamp=pd.Timestamp.now().isoformat(),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@app.post("/predict/batch")
async def predict_batch(requests: list[PredictionRequest]):
    """Predict scores for multiple employees at once."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    if scaler is None:
        raise HTTPException(status_code=503, detail="Scaler not loaded")

    results = []
    for req in requests:
        try:
            raw = np.array([[
                req.metrics.workHours,
                req.metrics.overtimeHours,
                req.metrics.commits,
                req.metrics.tasksCompleted,
            ]], dtype=np.float32)

            scaled = scaler.transform(raw)

            with torch.no_grad():
                tensor = torch.tensor(scaled, dtype=torch.float32)
                prediction = model(tensor)

            raw_score = prediction.item()
            score = round(raw_score)
            if score > 100:
                score = 100
            if score < 0:
                score = 0

            results.append({
                "employeeId": req.employeeId,
                "score": score,
                "raw_score": round(raw_score, 4),
                "factors": {
                    "workHours": req.metrics.workHours,
                    "overtimeHours": req.metrics.overtimeHours,
                    "commits": req.metrics.commits,
                    "tasksCompleted": req.metrics.tasksCompleted,
                },
                "timestamp": pd.Timestamp.now().isoformat(),
            })
        except Exception as e:
            results.append({
                "employeeId": req.employeeId,
                "score": None,
                "error": str(e),
            })

    return {"predictions": results, "count": len(results)}


# ─── GitHub daily commits ────────────────────────────────────────────────────

class GitHubDailyRequest(BaseModel):
    repo: str = Field(..., description="owner/repo or full https://github.com/owner/repo URL")
    github_profile: Optional[str] = Field(None, description="username or https://github.com/username URL")
    username: Optional[str] = Field(None, description="alias for github_profile")
    date: Optional[str] = Field(None, description="YYYY-MM-DD, defaults to today UTC")
    include_stats: bool = False


class GitHubBatchRequest(BaseModel):
    repo: str
    date: Optional[str] = None
    include_stats: bool = False
    employees: list[dict]  # [{employeeId, github_profile|username}]


class PredictWithGitHubRequest(BaseModel):
    employeeId: str
    repo: str
    github_profile: Optional[str] = None
    username: Optional[str] = None
    date: Optional[str] = None
    workHours: float = 8.0
    overtimeHours: float = 0.0
    tasksCompleted: int = 1


def _resolve_user(data) -> str:
    u = (getattr(data, "github_profile", None) or getattr(data, "username", None) or "").strip()
    if not u:
        raise HTTPException(status_code=422, detail="Provide github_profile (username or https://github.com/username URL)")
    return u


@app.get("/github/daily-commits")
async def github_daily_commits_get(
    repo: str = Query(..., description="owner/repo or GitHub repo URL"),
    github_profile: Optional[str] = Query(None, description="username or GitHub profile URL"),
    username: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="YYYY-MM-DD, default today UTC"),
    include_stats: bool = Query(False),
):
    user = (github_profile or username or "").strip()
    if not user:
        raise HTTPException(status_code=422, detail="Provide github_profile or username")
    try:
        return await fetch_daily_commits(repo, user, date, include_stats=include_stats)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        msg = str(e)
        code = 429 if "rate limit" in msg.lower() else 502
        raise HTTPException(status_code=code, detail=msg)


@app.post("/github/daily-commits")
async def github_daily_commits_post(req: GitHubDailyRequest):
    try:
        return await fetch_daily_commits(req.repo, _resolve_user(req), req.date, include_stats=req.include_stats)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        msg = str(e)
        raise HTTPException(status_code=429 if "rate limit" in msg.lower() else 502, detail=msg)


@app.post("/github/batch-daily-commits")
async def github_batch_daily_commits(req: GitHubBatchRequest):
    """For a whole team: one repo + N github profiles -> commits each on that day."""
    results = []
    for emp in req.employees:
        eid = emp.get("employeeId", emp.get("id", "unknown"))
        user = emp.get("github_profile") or emp.get("username") or emp.get("github") or ""
        if not user:
            results.append({"employeeId": eid, "commit_count": None, "error": "missing github_profile/username"})
            continue
        try:
            data = await fetch_daily_commits(req.repo, user, req.date, include_stats=req.include_stats)
            data["employeeId"] = eid
            results.append(data)
        except Exception as e:
            results.append({"employeeId": eid, "username": user, "commit_count": None, "error": str(e)})
    total = sum(r.get("commit_count", 0) or 0 for r in results if r.get("commit_count") is not None)
    return {"repo": req.repo, "date": req.date, "total_commits": total, "count": len(results), "results": results}


@app.post("/predict/with-github")
async def predict_with_github(req: PredictWithGitHubRequest):
    """
    Auto-fills `commits` from GitHub, then runs the performance model.
    This links daily GitHub activity -> performance score in one call.
    """
    if model is None or scaler is None:
        raise HTTPException(status_code=503, detail="Model/scaler not loaded")
    user = (req.github_profile or req.username or "").strip()
    if not user:
        raise HTTPException(status_code=422, detail="Provide github_profile or username")
    try:
        gh = await fetch_daily_commits(req.repo, user, req.date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    commits = gh["commit_count"]
    raw = np.array([[req.workHours, req.overtimeHours, commits, req.tasksCompleted]], dtype=np.float32)
    scaled = scaler.transform(raw)
    with torch.no_grad():
        raw_score = model(torch.tensor(scaled, dtype=torch.float32)).item()
    score = max(0, min(100, round(raw_score)))
    return {
        "employeeId": req.employeeId,
        "score": score,
        "raw_score": round(raw_score, 4),
        "github": gh,
        "inputs_used": {
            "workHours": req.workHours,
            "overtimeHours": req.overtimeHours,
            "commits": commits,
            "tasksCompleted": req.tasksCompleted,
        },
        "timestamp": pd.Timestamp.now().isoformat(),
    }


# ─── Daily work summary (GitHub + tasks -> Groq Qwen) ─────────────────────────

class DailySummaryRequest(BaseModel):
    employeeId: str = "EMP001"
    repo: str = Field(..., description="owner/repo or full GitHub URL")
    github_profile: Optional[str] = None
    username: Optional[str] = None
    date: Optional[str] = Field(None, description="YYYY-MM-DD, default today UTC")
    workHours: float = 8.0
    overtimeHours: float = 0.0
    tasks: list = Field(default_factory=list, description="e.g. ['Fixed login bug', {'title':'API docs','status':'done'}]")
    tasksCompleted: Optional[int] = None  # if omitted, len(tasks) is used
    include_stats: bool = False
    model: Optional[str] = Field(None, description="Groq model id, default qwen/qwen3.8-27b")


@app.post("/daily-summary")
async def daily_summary(req: DailySummaryRequest):
    """
    Full pipeline: GitHub commits of the day + tasks + performance score -> Groq Qwen summary.
    Needs GROQ_API_KEY env var. Key is never stored, only read at request time.
    """
    user = (req.github_profile or req.username or "").strip()
    if not user:
        raise HTTPException(status_code=422, detail="Provide github_profile or username")
    try:
        gh = await fetch_daily_commits(req.repo, user, req.date, include_stats=req.include_stats)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    n_tasks = req.tasksCompleted if req.tasksCompleted is not None else len(req.tasks or [])
    perf = None
    if model is not None and scaler is not None:
        try:
            raw = np.array([[req.workHours, req.overtimeHours, gh["commit_count"], n_tasks]], dtype=np.float32)
            with torch.no_grad():
                perf = round(float(model(torch.tensor(scaler.transform(raw), dtype=torch.float32)).item()), 2)
        except Exception:
            perf = None

    try:
        llm = await generate_daily_summary(
            employee_id=req.employeeId, date=gh["date"], commits=gh, tasks=req.tasks or [],
            work_hours=req.workHours, overtime=req.overtimeHours, perf_score=perf,
            model=req.model or DEFAULT_MODEL,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "employeeId": req.employeeId,
        "date": gh["date"],
        "commit_count": gh["commit_count"],
        "tasks_completed": n_tasks,
        "performance_score": perf,
        "github": gh,
        "tasks": req.tasks,
        "summary": llm["summary"],
        "model_used": llm["model_used"],
        "timestamp": pd.Timestamp.now().isoformat(),
    }


@app.get("/daily-summary/models")
def daily_summary_models():
    return {"default": DEFAULT_MODEL, "hint": "Pass any Groq model id in POST /daily-summary {model}. Qwen on Groq: qwen/qwen3.8-27b"}