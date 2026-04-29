# Mumzworld Return Triage — AI Engineering Intern

**Track A · Problem: Free-text return reason → structured triage decision in EN & AR**

## What it does

A mom contacts Mumzworld customer service with a free-text return reason in English or Arabic. This service reads that message, optionally pulls the user's order metadata from a database, and returns:

| Field | Description |
|---|---|
| `resolution` | `refund | exchange | store_credit | escalate` |
| `category` | `defective | wrong_item | changed_mind | damaged_shipping | late_delivery | other` |
| `confidence` | Float `[0, 1]` — model expresses uncertainty, not just picks a bucket |
| `reasoning` | 1-2 sentence explanation of the decision |
| `reply_en` | Empathetic customer-facing reply in English |
| `reply_ar` | Same reply written as natural Gulf Arabic (not a literal translation) |
| `language_detected` | `en | ar | other` |

Failures are explicit: Pydantic validates every field. The service returns a structured 422 if the model produces malformed output or disobeys business rules, rather than silently accepting a hallucinated format.

---

## 1. Setup and run instructions

**Prerequisites:** Docker + Docker Compose **OR** Python 3.11+, and a free OpenRouter API key.

### Option A — Docker (recommended, under 5 mins)

```bash
git clone <your-repo>
cd mumzworld-return-triage

# 1. Set your key
cp .env.example .env
# Edit .env: OPENROUTER_API_KEY=sk-or-v1-...
# Ensure MODEL=qwen/qwen-2.5-72b-instruct:free is set in .env

# 2. Start
docker compose up --build -d

# 3. Open browser
# Go to http://localhost:8000
```

### Option B — Local Python

```bash
cd mumzworld-return-triage
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export OPENROUTER_API_KEY=sk-or-v1-your-key
uvicorn app:app --reload
# → http://localhost:8000
```

### Running Evals
With the server running, open another terminal and run:
```bash
python evals.py
```

---

## 2. Evals

### Rubric
Each test case is scored on dimensions. A case passes only if all apply:
1. **Resolution & Category**: Exact match.
2. **Confidence Bounds**: Must be ≥ threshold for clear cases (catches under-confident correct answers). Must be ≤ threshold for vague/adversarial cases (catches overconfident hallucination).
3. **Bilingual Replies**: `reply_en` and `reply_ar` must be non-empty and formatted.

### Test Cases (14 total)

| # | Type | Input (preview) | Context | Expected Result |
|---|---|---|---|---|
| 1 | EN easy | Stroller arrived completely broken... | None | `refund`, `defective`, conf ≥ 0.80 |
| 2 | EN easy | Ordered size 3, got size 5. Can I swap? | None | `exchange`, `wrong_item`, conf ≥ 0.75 |
| 3 | EN easy | Changed my mind and don't need this... | None | `store_credit`, `changed_mind`, conf ≥ 0.65 |
| 4 | EN easy | Box arrived crushed, car seat cracked... | None | `refund`, `damaged_shipping`, conf ≥ 0.80 |
| 5 | EN easy | Arrived 3 weeks late, bought elsewhere | None | `refund`, `late_delivery`, conf ≥ 0.70 |
| 6 | AR clear | المنتج وصل مكسور تمامًا | None | `refund`, `defective`, conf ≥ 0.80 |
| 7 | AR clear | استلمت منتج مختلف | None | `refund`, `wrong_item`, conf ≥ 0.75 |
| 8 | AR clear | غيرت رأيي | None | `store_credit`, `changed_mind`, conf ≥ 0.65 |
| 9 | EN escalate | Baby got sick from bottle. Contaminated. | None | `escalate`, `defective`, conf ≥ 0.70 |
| 10 | AR escalate | سأرفع قضية ضد شركتكم | None | `escalate`, `other`, conf ≥ 0.70 |
| 11 | Adversarial | `asdkjh 1234 !!! ??? xyzzy` | None | `escalate`, `other`, **conf ≤ 0.40** |
| 12 | Vague | I just don't like it | None | `store_credit`, `changed_mind`, **conf ≤ 0.70** |
| 13 | Arabizi | The stroller is kherban... refund my floos. | None | `refund`, `defective`, conf ≥ 0.70 |
| 14 | Data RAG | This baby formula is untouched... | `ORD-1003` (Out of policy) | `store_credit`, `changed_mind`, conf ≥ 0.70 |

### Eval Scores & Known Failures
- **Score:** ~13/14 (93%) passing rate on `qwen-2.5-72b-instruct:free`.
- **Known Failure Mode 1 (Overconfidence):** On Case 12 ("I just don't like it"), the model sometimes returns a confidence of 0.85, failing the ≤ 0.70 ceiling eval. It successfully identifies `changed_mind`, but it fails to express uncertainty about the vagueness of the prompt.
- **Known Failure Mode 2 (Model Node Fallback):** If OpenRouter's 72B free node is down and falls back to a tiny 1B model, the model hallucinates the Pydantic Enum (e.g. returning `defective | wrong_item`). Our system gracefully catches this with a `422 Unprocessable Entity` explicitly explaining the schema violation.

---

## 3. Tradeoffs & Architecture

### Why I picked this problem
Return triage was chosen over alternatives (e.g., gift finder, review synthesizer) because:
1. **High Leverage:** Misclassified returns directly cost money (unnecessary refunds) or damage trust (wrongly denied claims).
2. **Measurable Outcomes:** Resolution and category are categorical. Evals are clean, avoiding the "vibes-based" grading of blog post generators.
3. **Multilingual Complexity:** GCC customers write in English, Arabic, and "Arabizi" (mixed language), which tests the model's true semantic understanding.

### Architecture Choice: Lightweight RAG + Pydantic
Instead of just wrapping a prompt, the FastAPI backend intercepts `order_id` (if provided) and fetches metadata from a `mock_orders.json` database. This metadata (e.g., return window policy) is injected into the prompt. 
- **Tradeoff:** I chose *One-Shot Prompting + RAG Context* over *Fine-Tuning*. Fine-tuning a classifier on historical data would be faster and cheaper in production, but prompt-based RAG allows dynamic business rules (e.g., dynamically changing return windows) without retraining.

### Handling Uncertainty
Uncertainty is handled via the strict validation of the `confidence` score. The system prompt instructs the model to return low confidence (<0.50) on vague or adversarial inputs. We enforce this in our evals: if the model is overly confident on gibberish, the eval fails.

### What I cut
- **Vector DB / Semantic Routing:** RAG is currently done via a simple JSON lookup by Order ID. I cut vector embeddings for policy documents to keep the setup under 5 minutes.
- **Streaming Response (SSE):** The frontend waits for the full JSON payload (takes ~2-4s). Streaming chunks would improve perceived latency.

### What I would build next
1. **Confidence Calibration Layer:** Add Platt scaling on a validation set to mathematically adjust the model's confidence outputs.
2. **Human-in-the-loop Dashboard:** Route any classification with `confidence < 0.60` or `resolution == escalate` directly to a Zendesk queue.

---

## 4. Tooling

| Harness / Model | Role / Usage |
|---|---|
| **OpenRouter** | Gateway used for all model inference to keep the project free and accessible. |
| **Qwen 2.5 72B Instruct** | The primary model. **Why?** After testing Llama 3.3 70B, Qwen proved significantly better at generating natural *Gulf Arabic* (contractions, local tone) rather than rigid Modern Standard Arabic. |
| **KiloCode / Agent** | Used for pair-coding the `extract_json()` robust parser, setting up the Pydantic schema validation, and iteratively designing the premium Glassmorphism UI. |
| **FastAPI + Pydantic v2** | Enforces "Failures are explicit." The `Literal` enums ensure the model cannot silently invent a category. |

**What worked & what was overruled:**
- The AI agent initially suggested using `response_format: {"type": "json_object"}`. I **overruled** this because many free-tier models on OpenRouter ignore that parameter and still output markdown fences. We built a robust 3-stage RegEx/JSON extractor instead, making the service model-agnostic.
- The system prompt iteration: We moved from paragraph instructions to a **Markdown Table** for resolution rules. This simple formatting change heavily reduced model hallucination on adversarial edge-cases.
