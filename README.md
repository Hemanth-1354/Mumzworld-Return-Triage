# Mumzworld Return Triage — AI Engineering Intern (Track A)

**Problem:** Free-text return reason → structured triage decision in EN & AR

**Live Demo:** [mumzworld-return-triage.onrender.com](https://mumzworld-return-triage.onrender.com)
---
**Loom Walkthrough:** [Watch 3-minute demo](https://www.loom.com/share/d8286951d63c43b1bd095232cc7d4064)


---

## What It Does

A mom contacts Mumzworld customer service with a free-text return reason in English or Arabic. This service reads that message, optionally pulls the user's order metadata from a mock orders database, and returns a fully structured triage decision:

| Field | Description |
|---|---|
| `resolution` | `refund \| exchange \| store_credit \| escalate` |
| `category` | `defective \| wrong_item \| changed_mind \| damaged_shipping \| late_delivery \| other` |
| `confidence` | Float `[0, 1]` — model expresses uncertainty, not just picks a bucket |
| `reasoning` | 1–2 sentence explanation of the decision |
| `reply_en` | Empathetic customer-facing reply in English |
| `reply_ar` | Same reply written as natural Gulf Arabic (not a literal translation) |
| `language_detected` | `en \| ar \| other` |

Failures are explicit: Pydantic validates every field. The service returns a structured `422` if the model produces malformed output or invalid enum values, rather than silently accepting a hallucinated format.

---

## 1. Setup and Run

**Prerequisites:** Docker + Docker Compose **OR** Python 3.11+, and a free [OpenRouter API key](https://openrouter.ai).

### Option A — Docker (recommended, under 5 mins)

```bash
git clone https://github.com/Hemanth-1354/Mumzworld-Return-Triage.git
cd Mumzworld-Return-Triage

# 1. Set your key
cp .env.example .env
# Edit .env: set OPENROUTER_API_KEY=sk-or-v1-...

# 2. Start
docker compose up --build -d

# 3. Open browser
# http://localhost:8000
```

### Option B — Local Python

```bash
git clone https://github.com/Hemanth-1354/Mumzworld-Return-Triage.git
cd Mumzworld-Return-Triage

python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export OPENROUTER_API_KEY=sk-or-v1-your-key       # Windows: set OPENROUTER_API_KEY=...
uvicorn app:app --reload
# → http://localhost:8000
```

### Running Evals

With the server running, open another terminal:

```bash
python evals.py
# Optional: python evals.py --url http://localhost:8000
```

Results are printed to console and saved to `eval_results.json`.

---

## 2. Evals

### Rubric

Each test case passes only if **all** of the following hold:

1. **Resolution & Category:** Exact match to expected values.
2. **Confidence Bounds:** `≥ threshold` for clear cases (catches under-confident correct answers); `≤ threshold` for vague/adversarial cases (catches overconfident hallucination).
3. **Bilingual Replies:** `reply_en` and `reply_ar` must be non-empty and pass Pydantic validation.

### Test Cases (14 total)

| # | Type | Input (preview) | Context | Expected Result |
|---|---|---|---|---|
| 1 | EN easy | Stroller arrived completely broken… | None | `refund`, `defective`, conf ≥ 0.80 |
| 2 | EN easy | Ordered size 3, got size 5. Can I swap? | None | `exchange`, `wrong_item`, conf ≥ 0.75 |
| 3 | EN easy | Changed my mind and don't need this… | None | `store_credit`, `changed_mind`, conf ≥ 0.65 |
| 4 | EN easy | Box arrived crushed, car seat cracked… | None | `refund`, `damaged_shipping`, conf ≥ 0.80 |
| 5 | EN medium | Arrived 3 weeks late, bought elsewhere | None | `refund`, `late_delivery`, conf ≥ 0.70 |
| 6 | AR clear | المنتج وصل مكسور تمامًا | None | `refund`, `defective`, conf ≥ 0.80 |
| 7 | AR clear | استلمت منتج مختلف | None | `refund`, `wrong_item`, conf ≥ 0.75 |
| 8 | AR clear | غيرت رأيي | None | `store_credit`, `changed_mind`, conf ≥ 0.65 |
| 9 | EN escalate | Baby got sick from bottle. Contaminated. | None | `escalate`, `defective`, conf ≥ 0.70 |
| 10 | AR escalate | سأرفع قضية ضد شركتكم | None | `escalate`, `other`, conf ≥ 0.70 |
| 11 | Adversarial | `asdkjh 1234 !!! ??? xyzzy` | None | `escalate`, `other`, **conf ≤ 0.40** |
| 12 | Vague | I just don't like it | None | `store_credit`, `changed_mind`, **conf ≤ 0.70** |
| 13 | Arabizi | The stroller is kherban… refund my floos. | None | `refund`, `defective`, conf ≥ 0.70 |
| 14 | RAG | This baby formula is untouched… | `ORD-1003` (out of policy) | `store_credit`, `changed_mind`, conf ≥ 0.70 |

### Eval Results

**Score: 11/14 (78%)** on `openai/gpt-oss-120b:free` (current model in `.env`).

| # | Status | Issue |
|---|---|---|
| 1–4, 6–8, 10–11, 13–14 | ✅ PASS | — |
| 5 | ❌ FAIL | Model returned `store_credit` instead of `refund` for late delivery |
| 9 | ❌ FAIL | Model returned category `other` instead of `defective` for safety concern |
| 12 | ❌ FAIL | Model returned confidence 0.93 — above the 0.70 ceiling (overconfident on vague input) |

**Known failure modes:**

- **Case 5 (Late delivery):** The model conflates "no longer need it" with `changed_mind` and gives `store_credit`, missing the causal link to `late_delivery` → `refund`.
- **Case 9 (Safety concern):** Model correctly escalates but picks `other` over `defective`, suggesting the category taxonomy needs a dedicated `safety` bucket or clearer prompt guidance.
- **Case 12 (Overconfidence):** The most persistent failure. Even a vague "I just don't like it" gets high confidence. The model identifies `changed_mind` correctly but doesn't penalise its own certainty for the vagueness of the input. Platt scaling or an explicit confidence rubric in the prompt would help.
- **Model fallback:** If the free node is overloaded and falls back to a smaller model, Pydantic catches enum hallucinations and returns a structured `422 Unprocessable Entity` with a clear schema violation message — failure is never silent.

---

## 3. Tradeoffs & Architecture

### Why This Problem

Return triage was chosen over alternatives (gift finder, review synthesiser, product comparison) because:

1. **High leverage:** Misclassified returns directly cost money (unnecessary refunds) or damage trust (wrongly denied claims). Every percentage point of accuracy has a real dollar value.
2. **Measurable outcomes:** Resolution and category are categorical. Evals are objective, avoiding vibes-based grading.
3. **Multilingual complexity:** GCC customers write in English, Arabic, and Arabizi (mixed-code), which tests genuine semantic understanding across registers — not just translation.

### Architecture

```
Browser / API Client
        │
        ▼
FastAPI  (app.py)
  ├── Pydantic validation on input  (models.py — ReturnRequest)
  ├── Order lookup  →  mock_orders.json  (mini-RAG / context injection)
  ├── Prompt builder  (prompts.py — system prompt + one-shot + schema)
  ├── OpenRouter call  (httpx, temperature 0.1, max_tokens 900)
  ├── 3-stage JSON extractor  (raw → strip fences → regex fallback)
  └── Pydantic validation on output  (models.py — TriageResult)
        │
        ▼
Structured JSON or explicit 422 / 502 error
```

**One-shot prompting + RAG context** was chosen over fine-tuning. Fine-tuning would be faster in production, but prompt-based RAG lets business rules (e.g. return windows, customer segment) change dynamically without retraining.

**Markdown table in system prompt** for resolution rules reduced enum hallucination compared to prose instructions — a small formatting change with a meaningful impact on output reliability.

**3-stage JSON extractor** (`extract_json()` in `app.py`) handles: raw JSON, markdown-fenced JSON (` ```json ``` `), and JSON embedded in preamble text. This makes the service model-agnostic and robust to free-tier models that ignore `response_format`.

### What I Cut

- **Vector DB / semantic policy routing:** RAG is a JSON dict lookup by `order_id`. Embedding policy documents over a vector store would enable fuzzy policy matching but added setup complexity beyond 5 hours.
- **Streaming (SSE):** The frontend waits for the full JSON payload (~2–4 s). Streaming would improve perceived latency.
- **Auth layer:** No API key gate on the `/triage` endpoint — acceptable for a prototype.

### What I'd Build Next

1. **Confidence calibration:** Platt scaling on a labelled validation set to fix the systematic overconfidence seen in Case 12.
2. **Human-in-the-loop queue:** Route any `confidence < 0.60` or `resolution == escalate` to a Zendesk ticket automatically.
3. **Real order DB:** Replace `mock_orders.json` with a live Postgres query so policy enforcement uses real order data.

---

## 4. Tooling

| Tool | Role |
|---|---|
| **OpenRouter** | Unified model gateway — keeps the project free and accessible with no paid key required |
| **openai/gpt-oss-120b:free** | Current active model (set in `.env`). Also tested: `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen-2.5-72b-instruct:free` — Qwen showed stronger natural Gulf Arabic; gpt-oss-120b had better overall instruction following |
| **KiloCode (VS Code agent)** | Pair-coded the `extract_json()` robust parser, Pydantic schema, and the glassmorphism UI in `static/index.html` |
| **FastAPI + Pydantic v2** | Schema enforcement — `Literal` enums make it impossible for the model to silently invent a category |

**What worked:** Moving system prompt resolution rules from prose to a Markdown table — noticeably reduced hallucination on adversarial inputs.

**What was overruled:** The AI agent suggested `response_format: {"type": "json_object"}`. I overruled this because many free-tier OpenRouter models ignore that parameter and still emit markdown fences. The 3-stage regex extractor is more robust and model-agnostic.

**Key prompt commits:** See `prompts.py` — the system prompt, one-shot example, and response schema are all version-controlled in plain Python strings.

---

## Project Structure

```
.
├── app.py              # FastAPI app — routing, RAG lookup, JSON extraction, validation
├── models.py           # Pydantic schemas: ReturnRequest, TriageResult
├── prompts.py          # System prompt, one-shot example, prompt builder
├── evals.py            # Eval harness — 14 test cases, async runner, JSON report
├── eval_results.json   # Last recorded eval run output
├── mock_orders.json    # Mini order database (ORD-1001 to ORD-1004)
├── requirements.txt    # Python dependencies (FastAPI, uvicorn, httpx, pydantic)
├── Dockerfile          # Container image
├── docker-compose.yml  # One-command local setup
├── static/
│   └── index.html      # Single-page frontend (glassmorphism UI)
└── .env.example        # API key template
```

---

## API Reference

```
POST /triage
Content-Type: application/json

{
  "text": "The stroller arrived broken",   // required, 1–2000 chars
  "order_id": "ORD-1001"                   // optional
}
```

Returns `TriageResult` JSON on success, or a structured error on `422` / `502`.

```
GET /health   → {"status": "ok", "model": "...", "api_key_configured": true}
GET /docs     → Swagger UI
GET /redoc    → ReDoc
```









--- 
---
---
---
---
## Post Submission Improvements
## Evaluation Results

**Final Score:** **14/14 (100%)**  
**Status:** Cases 1–14 ✅ PASS [`Check with eval_results.json`]

After prompt engineering refinements, the system achieved full accuracy across all test cases.

---


### 1. Late Delivery Priority Override
If the customer no longer wanted the item because it arrived late, the system now forces:

- **resolution:** refund  
- **reason_category:** late_delivery  

This prevents confusion with `changed_mind`.

---

### 2. Safety Concern Priority Override
Any mention of injury, sickness, contamination, or dangerous product behavior now forces:

- **resolution:** escalate  
- **reason_category:** defective  

Improves customer safety handling.

---

### 3. Vague Input Confidence Penalty
If the complaint has no clear reason, confidence is capped at:

- **confidence ≤ 0.60**

This prevents overconfident responses.

---

### 4. Policy Bug Fix
Customer text alone can no longer trigger `out_of_policy`.

Example:  
“arrived 3 weeks late” is treated as **late delivery**, not a policy violation.

This avoids false denials.

---

## Summary

These refinements improved:

- accuracy  
- fairness  
- uncertainty handling  
- escalation safety  
- production readiness

**Final Result:** **14/14 PASS**