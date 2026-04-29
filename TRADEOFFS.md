# TRADEOFFS.md — Architecture & Decision Log

## Why this problem

I evaluated six candidate problems from the brief before picking return triage:

| Candidate | Why rejected |
|---|---|
| "Moms Verdict" review synthesizer | Output quality is subjective; evals reduce to vibes. Hard to write adversarial cases that catch real failures. |
| Gift finder | Fun but the failure mode (a bad suggestion) has low stakes. |
| Product image → PDP content | Multimodal is compelling, but the eval rubric is harder to make precise. |
| Review → PDP | Similar eval problem. |
| Customer service email triage | Return triage is a more constrained version of this with clearer decision rules. |
| **Return reason triage** | **✓ High stakes (wrong decision = financial loss or customer churn). Clean categorical output. Measurable confidence. Natural bilingual requirement.** |

The brief explicitly grades problem selection at 20%. A boring but important problem beats an interesting but low-leverage one.

---

## Model

**Chosen: `qwen/qwen-2.5-72b-instruct:free`**

Alternatives tested:
- `meta-llama/llama-3.3-70b-instruct:free`: Good English, weaker Arabic. Gulf-dialect replies felt like MSA (Modern Standard Arabic) translations rather than native text.
- `google/gemma-3-27b-it:free`: 27B is a bit small for reliable structured JSON on every run.

Qwen 2.5 was pre-trained on a large Arabic corpus including Gulf dialect text. Its Arabic replies passed a native-speaker spot-check: contractions, tone, and phrasing felt natural rather than translated.

---

## Prompt design

**v1 (paragraph style):**
```
Resolution: choose refund for defective items, wrong items sent, or safety concerns...
```
Result: ~7/12 eval pass rate. Model conflated exchange and refund frequently.

**v2 (table style, current):**
```
| Value      | When to use                          |
|------------|--------------------------------------|
| refund     | Defective, wrong item, never arrived |
| exchange   | Same product replacement              |
```
Result: ~11/12 eval pass rate. The table format makes the decision boundary between `refund` and `exchange` explicit.

**One-shot example:** Adding a single complete example with both bilingual replies significantly improved Arabic reply quality and anchored the JSON schema. Zero-shot produced more varied JSON structures (sometimes wrapping in an outer `result` key).

---

## JSON extraction strategy

Three-attempt pipeline in `extract_json()`:
1. Direct `json.loads()` — works when model is well-behaved
2. Strip markdown fences (```` ```json ... ``` ````) — most common deviation
3. Regex `{...}` extraction — handles preamble text before the JSON

This is intentionally defensive. The alternative (`response_format: json_object`) isn't supported by all free OpenRouter models and silently fails on some, making the system model-dependent. The manual parser works across models.

---

## Pydantic validation

`TriageResult` enforces:
- `resolution` and `category` as `Literal` types — model cannot return an out-of-vocabulary value silently
- `confidence` as `float` with `ge=0.0, le=1.0` — invalid ranges raise before the result reaches the caller
- `reply_ar` and `reply_en` as non-empty strings — Arabic reply cannot be omitted
- `field_validator` rounds confidence to 2 decimal places — prevents floating-point noise in responses

A 422 from Pydantic is better than a 200 with a quietly wrong result.

---

## What was cut and why

| Feature | Why cut |
|---|---|
| DB / order history context | Requires infra beyond scope |
| Fine-tuned classifier | Would outperform prompting; out of 5-hour scope |
| Streaming response | Adds ~30 lines of SSE handling; latency is acceptable at ~2–4 s |
| RTL-aware text input | `dir="auto"` on textarea is a 1-line fix; cut only for time |
| Auth middleware | Not needed for a demo; would add FastAPI `Depends()` in prod |
| Confidence calibration | Platt scaling on a validation set would improve scores; post-scope |

---

## Production path

If this shipped:
1. **Week 1**: Connect to Zendesk/Freshdesk webhook. Auto-route `store_credit` and `exchange` decisions with conf > 0.85. Human review for `escalate` and low-confidence decisions.
2. **Month 1**: Collect human corrections as labelled data. Fine-tune a smaller model (Qwen 7B or Llama 8B) on resolution classification. This reduces inference cost and latency.
3. **Quarter 1**: Add order history context, SKU-level return policy rules, and confidence calibration on the held-out validation set.
