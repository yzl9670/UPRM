from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple


def _max_points_for_item(item: Dict[str, Any]) -> float:
    if isinstance(item.get("max_points"), (int, float)):
        try:
            return float(item.get("max_points"))
        except Exception:
            return 0.0
    mx = 0.0
    sc = item.get("scoringCriteria")
    if isinstance(sc, list):
        for entry in sc:
            try:
                mx = max(mx, float(entry.get("points") or 0))
            except Exception:
                pass
    return mx


def _build_scores_skeleton(rubric: List[Dict[str, Any]]) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    for r in rubric or []:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        d[name] = {"score": 0.0, "total": _max_points_for_item(r)}
    return d


def generate_feedback(
    message: str,
    rubric: List[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any], str, List[str]]:
    text = (message or "").strip()
    if not text:
        return (
            "No report content provided. Paste your final report text or upload a file.",
            _build_scores_skeleton(rubric),
            "No content to evaluate.",
            []
        )

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        feedback_text = (
            "**Final Report Feedback (offline mode)**\n"
            "- LLM disabled (no OPENAI_API_KEY). Returning structure-only scores.\n\n"
            "Master rubric emphasis:\n"
            "- Apply gates: missing PFD/streams/NPW/IRR/P&ID/HAZOP/DCF caps scores.\n"
            "- Check one-to-one PFD↔simulation numbering.\n"
            "- Respect page limits; >10% over caps at Proficient.\n"
        )
        return feedback_text, _build_scores_skeleton(rubric), "Model offline; no rubric scoring.", []

    # Global rules and section details (compressed to fit prompt)
    global_rules = [
        "Bands: Exemplary/Proficient/Developing/Insufficient.",
        "Round decimals to nearest integer before band mapping.",
        "Page limits: if >10% over, cap section at Proficient.",
        "Numbering consistency: enforce one-to-one PFD↔simulation where required.",
    ]

    section_gates = {
        "Justification (Intro & Baseline)": [
            "Missing PFD or full stream table → cap 7",
            "Missing one-to-one PFD↔simulation numbering → cap 7",
        ],
        "Summary (Improved Process & Results)": [
            "Missing improved PFD or missing NPW/IRR → cap 5",
            "Main equipment replaced without strong justification → cap 7",
        ],
        "6a) Designed Equipment": [
            "No one-to-one PFD↔simulation mapping, or missing full process stream table, or missing capital-cost method → cap 12",
            "Missing Aspen backups (base & improved) → cap 12",
        ],
        "6b) Safety, Health & Environment": [
            "Missing P&ID or HAZOP → cap 4",
        ],
        "6c) Economic Analysis": [
            "Missing DCF or NPW/IRR → cap 4",
        ],
    }

    # Derive simple page limits for sections that state them explicitly
    page_limits = {
        "Executive Summary": 1,
        "Justification (Intro & Baseline)": 6,
        "Summary (Improved Process & Results)": 6,
    }

    payload = {
        "report_excerpt": text[:16000],
        "rubrics": [{"name": r.get("name"), "max_points": _max_points_for_item(r)} for r in rubric],
        "global_rules": global_rules,
        "gates": section_gates,
        "page_limits": page_limits,
        "instructions": [
            "For each rubric, compute a raw score 0..max based on the provided text and rubric intent.",
            "Apply gates and page caps: final_score = min(rounded_raw, caps).",
            "Rounding: round raw to nearest integer before capping.",
            "If you cap, note which gate triggered in 'applied_caps'.",
            "Ground judgments strictly in the provided text; include 0-2 short evidence quotes when helpful.",
            "Keep rationales <= 25 words; suggestions <= 16 words; be concrete.",
        ],
        "output_schema": {
            "writing": [
                {
                    "name": "string",
                    "score": "integer (0..max after caps)",
                    "total": "integer (the rubric max)",
                    "rationale": "string (<= 25 words)",
                    "suggestion": "string (<= 16 words)",
                    "evidence_quotes": ["string (0-2 quotes)"],
                    "applied_caps": ["string (optional; gates or page caps applied)"]
                }
            ],
            "overall": {
                "notes": "string (<= 120 words; 2–4 concrete actions to reach Exemplary in capped/weak areas)"
            }
        }
    }

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        sys_text = (
            "You are a rigorous grader for a final chemical engineering design report. "
            "Enforce gates and caps, rounding rules, and page limits as specified. "
            "Return ONLY a valid JSON object that matches the requested schema."
        )
        user_text = (
            "Return a JSON object that strictly matches the output_schema. "
            "The word json here indicates your output must be JSON.\n\nPayload:\n" + json.dumps(payload, ensure_ascii=False)
        )
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_text},
                {"role": "user", "content": user_text},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as e:
        fb = f"**Final Report Feedback (degraded)**\n- Error: {e}\nFalling back to structure-only scores.\n"
        return fb, _build_scores_skeleton(rubric), "Model error; no scores.", []

    writing_rows = data.get("writing") or []
    evidence_quotes: List[str] = []
    strict_env = os.getenv("EVIDENCE_STRICT", "1").strip().lower()
    strict_evidence = strict_env not in ("0", "false", "no")

    earned, max_total = 0.0, 0.0
    scores: Dict[str, Any] = {}
    cap_notes: List[str] = []

    for w in writing_rows:
        try:
            name = str(w.get("name") or "").strip()
            if not name:
                continue
            s = float(w.get("score") or 0.0)
            t = float(w.get("total") or 0.0)
            max_total += t

            quotes = [q for q in (w.get("evidence_quotes") or []) if isinstance(q, str)]
            if strict_evidence and s > 0 and not quotes:
                s *= 0.9  # slightly penalize missing evidence in master rubric
                w["score"] = s

            earned += s
            scores[name] = {"score": s, "total": t}

            for q in quotes[:2]:
                q_clean = q.strip()
                if q_clean and q_clean not in evidence_quotes:
                    evidence_quotes.append(q_clean)

            caps = [c for c in (w.get("applied_caps") or []) if isinstance(c, str)]
            for c in caps:
                c2 = c.strip()
                if c2:
                    cap_notes.append(f"{name}: {c2}")
        except Exception:
            continue

    # Build feedback text (master rubric flavor)
    lines: List[str] = ["**Final Report Feedback**"]
    if max_total > 0:
        lines.append(f"**Total Score**: {earned:.0f}/{max_total:.0f}")
    if cap_notes:
        lines += ["", "**Applied Caps/Gates**", *cap_notes[:8]]
    lines += ["", "**Overall Summary**"]

    # Overall summary and priorities
    weak: List[Tuple[str, float, float, str]] = []
    strong: List[Tuple[str, float, float]] = []
    for w in writing_rows:
        try:
            n = (w.get("name") or "").strip()
            s = float(w.get("score") or 0.0)
            t = float(w.get("total") or 0.0)
            if not t:
                continue
            if (s / t) < 0.8:
                weak.append((n, s, t, (w.get("suggestion") or "").strip()))
            else:
                strong.append((n, s, t))
        except Exception:
            pass

    weak.sort(key=lambda x: (x[1] / x[2]) if x[2] else 0.0)
    top3 = weak[:3]

    summary_lines: List[str] = [
        f"Draft scores **{earned:.0f}/{max_total:.0f}**. To reach Exemplary, fix gated items first, then raise weakest sections.",
    ]
    if top3:
        steps = []
        for (n, s, t, sug) in top3:
            action = (sug or f"Strengthen {n} with quantitative evidence").rstrip(".")
            steps.append(f"{n}: {action}")
        summary_lines.append("**Revise in this order:** " + " → ".join(steps))
    missing = [n for (n, s, t, _) in weak if s == 0]
    if missing:
        summary_lines.append("**Missing sections:** " + ", ".join(missing[:5]))
    if strong:
        summary_lines.append("**Highlights:** " + ", ".join(n for (n, _, _) in strong[:3]))

    lines += ["\n".join(summary_lines), ""]

    body: List[str] = ["**Per-Rubric Breakdown**"]
    for w in writing_rows:
        try:
            name = str(w.get("name") or "").strip()
            s = float(w.get("score") or 0.0)
            t = float(w.get("total") or 0.0)
            rationale = str(w.get("rationale") or "").strip()
            sug = str(w.get("suggestion") or "").strip()
            quotes = [q for q in (w.get('evidence_quotes') or []) if isinstance(q, str)]

            row = [f" **{name}**: {s:.0f}/{t:.0f}"]
            if rationale:
                row.append(f"  - **Why**: {rationale}")
            if sug and sug.lower() != "none":
                row.append(f"  - **Improve**: {sug}")
            if quotes:
                row.append("  - **Evidence**: " + " | ".join(f"“{q.strip()}”" for q in quotes[:2]))
            body += row
        except Exception:
            continue

    final_text = "\n".join(lines + [""] + body).strip()
    summary = str((data.get("overall") or {}).get("notes") or "").strip() or ""
    return final_text, (scores or _build_scores_skeleton(rubric)), summary, evidence_quotes

