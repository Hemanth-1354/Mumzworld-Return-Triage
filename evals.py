"""
Mumzworld Return Triage — Eval Harness
=======================================
Run against a live server:
    python evals.py [--url http://localhost:8000]

Outputs a summary table and saves full results to eval_results.json.
Exit code: 0 if all cases pass, 1 otherwise.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: int
    desc: str
    text: str
    expect_resolution: Optional[str]       # None = any resolution acceptable
    expect_category: str
    expect_lang: str
    expect_min_confidence: Optional[float] = None   # must be >= this
    expect_max_confidence: Optional[float] = None   # must be <= this (for vague inputs)


TEST_CASES: list[TestCase] = [
    # ── Easy English ────────────────────────────────────────────────────────
    TestCase(
        id=1, desc="EN – clear defective product",
        text="The stroller arrived completely broken — one wheel is cracked and it won't fold.",
        expect_resolution="refund", expect_category="defective", expect_lang="en",
        expect_min_confidence=0.80,
    ),
    TestCase(
        id=2, desc="EN – wrong size, wants exchange",
        text="I ordered size 3 diapers but got size 5. Can I swap them for the right size?",
        expect_resolution="exchange", expect_category="wrong_item", expect_lang="en",
        expect_min_confidence=0.75,
    ),
    TestCase(
        id=3, desc="EN – changed mind (store credit)",
        text="I changed my mind and don't need this anymore. I'd like to return it.",
        expect_resolution="store_credit", expect_category="changed_mind", expect_lang="en",
        expect_min_confidence=0.65,
    ),
    TestCase(
        id=4, desc="EN – damaged in shipping",
        text="The box arrived completely crushed. The baby car seat inside has a visible crack on the side.",
        expect_resolution="refund", expect_category="damaged_shipping", expect_lang="en",
        expect_min_confidence=0.80,
    ),
    TestCase(
        id=5, desc="EN – late delivery, bought elsewhere",
        text="My order arrived 3 weeks late. I already bought it from another store and no longer need this.",
        expect_resolution="refund", expect_category="late_delivery", expect_lang="en",
        expect_min_confidence=0.70,
    ),
    # ── Arabic cases ─────────────────────────────────────────────────────────
    TestCase(
        id=6, desc="AR – defective product",
        text="المنتج وصل مكسور تمامًا ولا يعمل على الإطلاق، أريد استرداد أموالي.",
        expect_resolution="refund", expect_category="defective", expect_lang="ar",
        expect_min_confidence=0.80,
    ),
    TestCase(
        id=7, desc="AR – wrong item received",
        text="استلمت منتج مختلف تمامًا عن الذي طلبته، هذا ليس ما اشتريته.",
        expect_resolution="refund", expect_category="wrong_item", expect_lang="ar",
        expect_min_confidence=0.75,
    ),
    TestCase(
        id=8, desc="AR – changed mind",
        text="غيرت رأيي ولا أحتاج المنتج بعد الآن، أرجو الإلغاء.",
        expect_resolution="store_credit", expect_category="changed_mind", expect_lang="ar",
        expect_min_confidence=0.65,
    ),
    # ── Escalation cases ──────────────────────────────────────────────────────
    TestCase(
        id=9, desc="EN – safety concern → must escalate",
        text="My baby drank from this bottle and got sick. I think it might be contaminated.",
        expect_resolution="escalate", expect_category="defective", expect_lang="en",
        expect_min_confidence=0.70,
    ),
    TestCase(
        id=10, desc="AR – legal threat → must escalate",
        text="سأرفع قضية ضد شركتكم أمام المحكمة إذا لم تردوا أموالي فورًا.",
        expect_resolution="escalate", expect_category="other", expect_lang="ar",
        expect_min_confidence=0.70,
    ),
    # ── Adversarial / edge cases ───────────────────────────────────────────
    TestCase(
        id=11, desc="Gibberish – must not hallucinate, should escalate",
        text="asdkjh 1234 !!! ??? xyzzy",
        expect_resolution="escalate", expect_category="other", expect_lang="other",
        expect_max_confidence=0.40,   # must express uncertainty
    ),
    TestCase(
        id=12, desc="EN – very vague, confidence should be low",
        text="I just don't like it.",
        expect_resolution="store_credit", expect_category="changed_mind", expect_lang="en",
        expect_max_confidence=0.70,   # vague input → model must not be overconfident
    ),
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_case(case: TestCase, result: dict) -> tuple[bool, list[str]]:
    """Return (passed, list_of_issues)."""
    issues: list[str] = []

    if case.expect_resolution and result.get("resolution") != case.expect_resolution:
        issues.append(
            f"resolution '{result.get('resolution')}' ≠ expected '{case.expect_resolution}'"
        )

    if result.get("category") != case.expect_category:
        issues.append(
            f"category '{result.get('category')}' ≠ expected '{case.expect_category}'"
        )

    if result.get("language_detected") != case.expect_lang:
        issues.append(
            f"lang '{result.get('language_detected')}' ≠ expected '{case.expect_lang}'"
        )

    conf = result.get("confidence", 0.0)
    if case.expect_min_confidence is not None and conf < case.expect_min_confidence:
        issues.append(
            f"confidence {conf:.2f} below floor {case.expect_min_confidence} (under-confident)"
        )
    if case.expect_max_confidence is not None and conf > case.expect_max_confidence:
        issues.append(
            f"confidence {conf:.2f} above ceiling {case.expect_max_confidence} (overconfident)"
        )

    if not result.get("reply_ar", "").strip():
        issues.append("reply_ar is empty")
    if not result.get("reply_en", "").strip():
        issues.append("reply_en is empty")
    if not result.get("reasoning", "").strip():
        issues.append("reasoning is empty")

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_evals(base_url: str) -> int:
    print(f"\nMumzworld Return Triage — Eval Harness")
    print(f"Target: {base_url}")
    print("=" * 65)

    all_results = []
    passed_count = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        for case in TEST_CASES:
            try:
                resp = await client.post(
                    f"{base_url}/triage",
                    json={"text": case.text},
                )
                if resp.status_code == 200:
                    result = resp.json()
                    ok, issues = score_case(case, result)
                    if ok:
                        passed_count += 1

                    icon = "✅" if ok else "❌"
                    short = case.text[:55] + ("…" if len(case.text) > 55 else "")
                    print(f"{icon} [{case.id:02d}] {case.desc}")
                    print(f"     Input : {short!r}")
                    print(
                        f"     Result: resolution={result.get('resolution')}, "
                        f"cat={result.get('category')}, "
                        f"conf={result.get('confidence')}, "
                        f"lang={result.get('language_detected')}"
                    )
                    if not ok:
                        for iss in issues:
                            print(f"     ⚠  {iss}")
                    print()

                    all_results.append({
                        "id": case.id,
                        "desc": case.desc,
                        "input": case.text,
                        "passed": ok,
                        "issues": issues,
                        "result": result,
                    })
                else:
                    print(f"❌ [{case.id:02d}] {case.desc} — HTTP {resp.status_code}: {resp.text[:200]}\n")
                    all_results.append({
                        "id": case.id, "passed": False,
                        "issues": [f"HTTP {resp.status_code}"], "result": {},
                    })

            except Exception as exc:
                print(f"❌ [{case.id:02d}] {case.desc} — Exception: {exc}\n")
                all_results.append({
                    "id": case.id, "passed": False,
                    "issues": [str(exc)], "result": {},
                })

    total = len(TEST_CASES)
    pct = int(100 * passed_count / total)

    print("=" * 65)
    print(f"FINAL SCORE: {passed_count}/{total} cases passed ({pct}%)")
    print()

    # Save full results
    output = {
        "summary": {"passed": passed_count, "total": total, "pct": pct},
        "cases": all_results,
    }
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("Full results saved → eval_results.json")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run triage evals against a live server")
    parser.add_argument("--url", default="http://localhost:8000", help="Server base URL")
    args = parser.parse_args()
    sys.exit(asyncio.run(run_evals(args.url)))
