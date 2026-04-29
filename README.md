# Mumzworld Return Triage — AI Engineering Intern

**Track A · Problem: Free-text return reason → structured triage decision in EN & AR**

---

## What it does

A mom contacts Mumzworld customer service with a free-text return reason in English or Arabic. This service reads that message and returns:

| Field | Description |
|---|---|
| `resolution` | `refund \| exchange \| store_credit \| escalate` |
| `category` | `defective \| wrong_item \| changed_mind \| damaged_shipping \| late_delivery \| other` |
| `confidence` | Float `[0, 1]` — model expresses uncertainty, not just picks a bucket |
| `reasoning` | 1-2 sentence explanation of the decision |
| `reply_en` | Empathetic customer-facing reply in English |
| `reply_ar` | Same reply written as natural Gulf Arabic (not a literal translation) |
| `language_detected` | `en \| ar \| other` |

Failures are explicit: Pydantic validates every field; the service returns a structured 422 if the model produces malformed output rather than silently accepting it.

---

## Setup & Run (under 5 minutes)

### Prerequisites
- Docker + Docker Compose **OR** Python 3.11+
- Free OpenRouter API key → [openrouter.ai](https://openrouter.ai) (takes 60 seconds)

### Option A — Docker (recommended)

```bash
git clone <your-repo>
cd mumzworld-return-triage

# 1. Set your key
cp .env.example .env
# Edit .env: OPENROUTER_API_KEY=sk-or-v1-...

# 2. Start
docker compose up --build

# 3. Open browser
open http://localhost:8000
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

### Run evals (server must be running)

```bash
python evals.py
# Optional: python evals.py --url http://localhost:8000
```

### API docs
Interactive docs at `http://localhost:8000/docs` (Swagger UI).

---

## Architecture

```
Browser / curl
    │  POST /triage  {"text": "..."}
    ▼
FastAPI (app.py)
    │  build_messages() → system prompt + one-shot example
    ▼
OpenRouter API  ──►  qwen/qwen-2.5-72b-instruct:free
    │  raw JSON string
    ▼
extract_json()   ← strips fences, finds {...}, handles preamble
    │  dict
    ▼
Pydantic TriageResult  ← validates schema, rejects bad output explicitly
    │  200 OK or 422
    ▼
Browser renders result with confidence bar + bilingual replies
```

**Why two stages of validation?** The LLM sometimes returns JSON wrapped in markdown fences or with preamble text. `extract_json()` is a three-attempt parser that handles all common output formats before handing off to Pydantic, which enforces the enum literals, float bounds, and non-empty string requirements. If either stage fails the service returns a structured 422 — never a silent bad result.

---

## Evals

### Rubric

| Dimension | How scored |
|---|---|
| Resolution | Exact match against expected value |
| Category | Exact match |
| Language detection | Exact match (`en`, `ar`, `other`) |
| Confidence (floor) | For clear cases, must be ≥ floor — catches overconfident wrong answers |
| Confidence (ceiling) | For vague/adversarial cases, must be ≤ ceiling — penalises false certainty |
| Bilingual replies | `reply_en` and `reply_ar` must both be non-empty |
| Reasoning | Must be non-empty |

### Test Cases (12 total)

| # | Type | Input (preview) | Expected |
|---|---|---|---|
| 1 | EN easy | Stroller arrived broken… | refund / defective / conf ≥ 0.80 |
| 2 | EN easy | Ordered size 3, got size 5… | exchange / wrong_item / conf ≥ 0.75 |
| 3 | EN easy | Changed my mind… | store_credit / changed_mind / conf ≥ 0.65 |
| 4 | EN easy | Box arrived crushed, car seat cracked | refund / damaged_shipping / conf ≥ 0.80 |
| 5 | EN easy | Arrived 3 weeks late, bought elsewhere | refund / late_delivery / conf ≥ 0.70 |
| 6 | AR clear | المنتج وصل مكسور تمامًا | refund / defective / conf ≥ 0.80 |
| 7 | AR clear | استلمت منتج مختلف | refund / wrong_item / conf ≥ 0.75 |
| 8 | AR clear | غيرت رأيي | store_credit / changed_mind / conf ≥ 0.65 |
| 9 | EN escalate | Baby got sick from bottle | escalate / defective / conf ≥ 0.70 |
| 10 | AR escalate | سأرفع قضية ضد شركتكم | escalate / other / conf ≥ 0.70 |
| 11 | Adversarial | `asdkjh 1234 !!! ???` | escalate / other / **conf ≤ 0.40** |
| 12 | Vague | I just don't like it | store_credit / changed_mind / **conf ≤ 0.70** |

Cases 11 and 12 specifically test **uncertainty handling**: a model that returns `refund` with 0.95 confidence on gibberish fails this eval. The ceiling constraint enforces expressed uncertainty.

### Known failure modes

- **Case 2 (exchange vs refund):** Some runs of Qwen classify "wrong size diapers" as `refund` rather than `exchange` because the customer phrased it as a question ("can I swap?") which the model interprets as a return intent. The system prompt now explicitly calls out "exchange = same product replaced" to reduce this.
- **Case 12 (vague input):** Occasionally the model returns 0.75 confidence on "I just don't like it," exceeding our ceiling. This is a known over-confidence failure. A production fix would be a calibration pass or a post-hoc confidence deflation for inputs under a token length threshold.
- **Arabic reply quality:** Reply quality degrades on adversarial case 11 (gibberish). The model still produces grammatically correct Arabic but the content is generic. Acceptable for escalate cases.

---

## Tradeoffs

### Problem selection
Return triage was chosen over alternatives (gift finder, review synthesizer) because:
1. **Immediate cost impact** — misclassified returns either cost money (unnecessary refunds) or damage trust (wrongly denied legitimate claims). High stakes = high leverage.
2. **Natural multilingual requirement** — GCC customers write in both Arabic and English, sometimes in the same message.
3. **Clean evals** — resolution and category are categorical; confidence has measurable bounds. Easy to write adversarial cases that catch real failures, unlike open-ended generation tasks.

### Model choice: Qwen 2.5 72B (free on OpenRouter)
- Best Arabic support among free-tier models. Gulf Arabic is a distinct dialect; Llama 3.3 70B produced more MSA-style Arabic replies in testing.
- 72B parameters is sufficient for structured JSON output with a strong system prompt + one-shot example.
- Temperature 0.1 keeps outputs near-deterministic across evals.

### Architecture decisions

**One-shot prompting over RAG**
The decision rules are simple enough to encode in a system prompt. RAG over a policy document would add latency and infra for no benefit here.

**Manual JSON extraction over `response_format: json_object`**
Not all free OpenRouter models support the `response_format` parameter. The three-attempt `extract_json()` function handles markdown fences and preamble text that models often emit, making the service model-agnostic.

**Pydantic v2 for validation**
`Literal` types on `resolution` and `category` mean the model cannot return an out-of-vocabulary value silently — it raises a 422. `field_validator` enforces non-empty replies. This is the "failures are explicit" requirement from the brief.

**Single FastAPI file + static HTML**
Keeps the repo navigable in under 5 minutes. A production version would split into routers and add auth middleware.

### What was cut
- **Order history context**: feeding past order details into the prompt would improve resolution accuracy (e.g. knowing if the item is under warranty). Cut because it requires a DB connection.
- **Fine-tuned model**: a fine-tuned classifier on historical resolution data would outperform prompting. Cut as out of scope for 5 hours.
- **Streaming response**: would improve perceived latency. The frontend currently waits for the full JSON.
- **Arabic RTL input in the UI**: the textarea doesn't auto-detect RTL. A production UI would use the `dir="auto"` attribute.

### What I'd build next
1. Confidence calibration layer (Platt scaling on a held-out validation set)
2. Webhook to push triage decisions to Zendesk/Freshdesk
3. Human-review queue for all `escalate` decisions + confidence < 0.50

---

## Tooling

| Tool | Role |
|---|---|
| **Claude Sonnet (claude.ai)** | Initial architecture design, README drafting, prompt iteration |
| **OpenRouter** | API gateway to Qwen 2.5 72B (free tier) for all inference |
| **Qwen 2.5 72B Instruct** | Primary model — best free-tier Arabic support in OpenRouter |
| **FastAPI + Pydantic v2** | API framework and output schema validation |
| **httpx** | Async HTTP client for OpenRouter calls |

**How Claude was used:**
- Pair-coding for the `extract_json()` robust parser and Pydantic validator setup
- Prompt iteration: tested 3 versions of the system prompt against adversarial cases; the current version uses a decision table format which significantly reduced hallucination on gibberish inputs vs paragraph-style instructions
- README and EVALS.md drafting

**What I overruled:**
- Claude initially suggested `response_format: json_object` in the API call. Overruled after testing showed several free models ignore this parameter and still return markdown-fenced JSON. Switched to the manual parser.
- Claude suggested Llama 3.3 70B as the default model. Overruled after comparing Arabic reply quality; Qwen 2.5 produced more natural Gulf Arabic.

**Prompts that materially shaped the output:**
The system prompt uses a markdown table for resolution rules (vs paragraph prose in v1). This alone raised eval pass rate from ~7/12 to ~11/12 in local testing by making the decision boundary unambiguous.

---

## Time log

| Phase | Time |
|---|---|
| Problem selection & architecture design | ~45 min |
| Core API (app.py, models.py, prompts.py) | ~90 min |
| Frontend (static/index.html) | ~45 min |
| Prompt iteration & Arabic quality testing | ~45 min |
| Eval harness (evals.py, 12 cases) | ~45 min |
| Docker, README, EVALS.md, TRADEOFFS.md | ~30 min |
| **Total** | **~5.5 hours** |

Went ~30 min over budget on prompt iteration — Arabic reply quality required more rounds of testing than anticipated.
