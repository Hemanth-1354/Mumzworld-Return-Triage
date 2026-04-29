# EVALS.md — Return Triage Evaluation

## Rubric

Each test case is scored on **7 dimensions**. A case passes only if all 7 pass.

| Dimension | Check | Rationale |
|---|---|---|
| Resolution | Exact match | Wrong resolution = wrong customer outcome |
| Category | Exact match | Used for routing and reporting |
| Language detection | Exact match (`en/ar/other`) | Drives reply-language selection |
| Confidence floor | ≥ threshold for clear cases | Catches under-confident correct answers |
| Confidence ceiling | ≤ threshold for vague/adversarial | Catches overconfident wrong answers |
| reply_en non-empty | String present | Agent must always draft a reply |
| reply_ar non-empty | String present | Arabic reply is a hard requirement |

## Test Suite

### Group 1 — English, clear-cut (cases 1–5)

These are the "should always pass" cases. Failure here = broken system.

**Case 1 — Defective product (EN)**
```
Input:  "The stroller arrived completely broken — one wheel is cracked and it won't fold."
Expect: resolution=refund, category=defective, lang=en, conf≥0.80
Why:    Physical damage on arrival → full refund. Unambiguous.
```

**Case 2 — Wrong size, wants exchange (EN)**
```
Input:  "I ordered size 3 diapers but got size 5. Can I swap them for the right size?"
Expect: resolution=exchange, category=wrong_item, lang=en, conf≥0.75
Why:    Customer explicitly wants same product in correct size = exchange, not refund.
        This is a known hard case: some models default to refund.
```

**Case 3 — Changed mind (EN)**
```
Input:  "I changed my mind and don't need this anymore."
Expect: resolution=store_credit, category=changed_mind, lang=en, conf≥0.65
Why:    No defect, no wrong item — buyer's remorse = store credit.
```

**Case 4 — Damaged in shipping (EN)**
```
Input:  "The box arrived completely crushed. The baby car seat inside has a visible crack."
Expect: resolution=refund, category=damaged_shipping, lang=en, conf≥0.80
Why:    Carrier damage → Mumzworld responsible → refund.
```

**Case 5 — Late delivery (EN)**
```
Input:  "My order arrived 3 weeks late. I already bought it from another store."
Expect: resolution=refund, category=late_delivery, lang=en, conf≥0.70
Why:    Fulfillment failure → customer has legitimate refund claim.
```

---

### Group 2 — Arabic (cases 6–8)

Tests language detection, Arabic parsing, and native Arabic reply generation.

**Case 6 — Defective (AR)**
```
Input:  "المنتج وصل مكسور تمامًا ولا يعمل على الإطلاق، أريد استرداد أموالي"
Expect: resolution=refund, category=defective, lang=ar, conf≥0.80
Why:    Clear Arabic statement of defect + explicit refund request.
```

**Case 7 — Wrong item (AR)**
```
Input:  "استلمت منتج مختلف تمامًا عن الذي طلبته، هذا ليس ما اشتريته"
Expect: resolution=refund, category=wrong_item, lang=ar, conf≥0.75
Why:    "Different product than ordered" = wrong_item.
```

**Case 8 — Changed mind (AR)**
```
Input:  "غيرت رأيي ولا أحتاج المنتج بعد الآن، أرجو الإلغاء"
Expect: resolution=store_credit, category=changed_mind, lang=ar, conf≥0.65
Why:    "Changed my mind" = store_credit.
```

---

### Group 3 — Escalation (cases 9–10)

High-stakes cases. A missed escalation is a customer service failure.

**Case 9 — Safety concern (EN)**
```
Input:  "My baby drank from this bottle and got sick. I think it might be contaminated."
Expect: resolution=escalate, category=defective, lang=en, conf≥0.70
Why:    Potential product safety issue. Must escalate to a human, never auto-resolve.
```

**Case 10 — Legal threat (AR)**
```
Input:  "سأرفع قضية ضد شركتكم أمام المحكمة إذا لم تردوا أموالي فورًا"
Expect: resolution=escalate, category=other, lang=ar, conf≥0.70
Why:    Legal threat → must escalate to legal/management team.
```

---

### Group 4 — Adversarial (cases 11–12)

Tests uncertainty handling. These are the hardest cases.

**Case 11 — Gibberish**
```
Input:  "asdkjh 1234 !!! ??? xyzzy"
Expect: resolution=escalate, category=other, lang=other, conf≤0.40
Why:    Model must NOT invent a plausible-sounding reason for nonsense input.
        Overconfident answer here = hallucination failure.
```

**Case 12 — Extremely vague**
```
Input:  "I just don't like it."
Expect: resolution=store_credit, category=changed_mind, lang=en, conf≤0.70
Why:    The resolution is guessable (changed_mind) but the vagueness must be
        reflected in a lower confidence. A model that returns conf=0.95 here
        is not expressing appropriate uncertainty.
```

---

## Running Evals

```bash
# Server must be running first
uvicorn app:app --reload   # or docker compose up

# Run evals
python evals.py
# → saves full results to eval_results.json
```

## Expected Score

With `qwen/qwen-2.5-72b-instruct:free` and default settings:
**Target: 10–12/12 (83–100%)**

Typical failure: Case 2 (exchange vs refund) and Case 12 (overconfidence). Both are documented and partially mitigated in the current prompt. A fine-tuned model or retrieval-augmented policy document would close the gap.
