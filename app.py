"""
Mumzworld Return Triage API
===========================
FastAPI service that classifies customer return reasons into structured triage
decisions (resolution, category, confidence) with bilingual reply suggestions.
"""

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from models import ReturnRequest, TriageResult
from prompts import build_messages

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Mumzworld Return Triage API",
    description="AI triage for customer return reasons — English & Arabic",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Config (from environment)
# ---------------------------------------------------------------------------

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
MODEL: str = os.getenv("MODEL", "qwen/qwen-2.5-72b-instruct:free")
OPENROUTER_BASE: str = "https://openrouter.ai/api/v1"

# Load mock database
MOCK_DB_PATH = Path(__file__).parent / "mock_orders.json"
try:
    MOCK_ORDERS = json.loads(MOCK_DB_PATH.read_text(encoding="utf-8"))
except FileNotFoundError:
    MOCK_ORDERS = {}


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict[str, Any]:
    """
    Robustly extract a JSON object from model output.
    Handles: raw JSON, markdown fences (```json … ```), partial preambles.
    Raises ValueError if no valid JSON found.
    """
    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Find first {...} block (greedy, handles preamble text)
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in model output. Preview: {text[:300]!r}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> HTMLResponse:
    """Serve the single-page frontend."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post(
    "/triage",
    response_model=TriageResult,
    summary="Triage a return reason",
    responses={
        200: {"description": "Structured triage decision"},
        422: {"description": "Model returned unparseable or invalid output"},
        500: {"description": "Server misconfiguration"},
        502: {"description": "Upstream model API error"},
    },
)
async def triage_return(req: ReturnRequest) -> TriageResult:
    """
    Accepts a free-text return reason (English or Arabic) and returns:
    - resolution: refund | exchange | store_credit | escalate
    - category
    - reasoning + confidence score
    - bilingual customer reply (EN + AR)
    """
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY environment variable is not set. See README.",
        )

    # Lightweight RAG / Context Injection:
    # We fetch the order details from our mock DB based on order_id.
    # This allows the model to enforce business rules (e.g. denying refunds for out-of-policy items)
    # dynamically, rather than relying strictly on the customer's self-reported text.
    order_data = None
    if req.order_id and req.order_id in MOCK_ORDERS:
        order_data = MOCK_ORDERS[req.order_id]
        order_data["order_id"] = req.order_id

    # Build the conversation history (System Prompt + One-Shot Example + User Input + RAG Context)
    messages = build_messages(req.text, order_data)

    # Call OpenRouter
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            resp = await client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://mumzworld.com",
                    "X-Title": "Mumzworld Return Triage",
                },
                json={
                    "model": MODEL,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 900,
                },
            )
        except httpx.TimeoutException:
            raise HTTPException(502, detail="Upstream model timed out (45 s). Try again.")
        except httpx.RequestError as exc:
            raise HTTPException(502, detail=f"Network error reaching model API: {exc}")

    if resp.status_code != 200:
        raise HTTPException(
            502,
            detail=f"OpenRouter returned HTTP {resp.status_code}: {resp.text[:400]}",
        )

    resp_data = resp.json()
    choices = resp_data.get("choices", [])
    if not choices:
        raise HTTPException(502, detail=f"Model returned no choices. Response: {resp.text[:400]}")
    
    raw_content = choices[0].get("message", {}).get("content")
    if raw_content is None:
        raw_content = ""

    # Parse + validate
    try:
        data = extract_json(raw_content)
        result = TriageResult(**data, order_id=req.order_id)
        return result
    except ValidationError as exc:
        raise HTTPException(
            422,
            detail={
                "error": "Model output parsed but failed schema validation",
                "detail": str(exc.errors()),
                "raw_preview": raw_content[:400],
            },
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            422,
            detail={
                "error": "Model returned output that could not be parsed as valid JSON",
                "detail": str(exc),
                "raw_preview": raw_content[:400],
            },
        )
    except Exception as exc:
        raise HTTPException(
            422,
            detail={
                "error": "An unexpected error occurred during parsing",
                "detail": str(exc),
                "raw_preview": raw_content[:400],
            },
        )


@app.get("/health", summary="Health check")
async def health() -> dict:
    """Returns service status and active model."""
    return {
        "status": "ok",
        "model": MODEL,
        "api_key_configured": bool(OPENROUTER_API_KEY),
    }


# ---------------------------------------------------------------------------
# Global error handler — return JSON for all unhandled errors
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
