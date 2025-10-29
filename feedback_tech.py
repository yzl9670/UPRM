from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple


def _max_points_for_item(item: Dict[str, Any]) -> float:
    mx = 0.0
    # allow either explicit max_points or scoringCriteria array of {points}
    if isinstance(item.get("max_points"), (int, float)):
        return float(item.get("max_points"))
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
            "No report content provided. Please paste the technical report text or upload a file.",
            _build_scores_skeleton(rubric),
            "No content to evaluate.",
            []
        )

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        feedback_text = (
            "**Technical Report Feedback (offline mode)**\n"
            "- LLM disabled (no OPENAI_API_KEY). Returning structure-only scores.\n\n"
            "Focus areas:\n"
            "- Ensure Puerto Rico-specific constraints are addressed (infrastructure, regulations, climate).\n"
            "- Add units, flowrates, and assumptions; cite credible sources.\n"
            "- Provide economic assumptions and a brief sensitivity check.\n"
        )
        return feedback_text, _build_scores_skeleton(rubric), "Model offline; no rubric scoring.", []


    payload = {
        "report_excerpt": text[:8000],
        "rubrics": [{"name": r.get("name"), "max_points": _max_points_for_item(r)} for r in rubric],
        "instructions": [
            "Score each rubric 0..max based on clarity, specificity, credibility, and structure.",
            "Ground judgments strictly in the provided text; do not assume unstated facts.",
            "Keep rationales <= 25 words; suggestions <= 16 words; be concrete.",
            "Include 0-2 short evidence quotes when helpful.",
        ],
        "output_schema": {
            "writing": [
                {
                    "name": "string",
                    "score": "number (0..max for this rubric)",
                    "total": "number (the rubric max)",
                    "rationale": "string (<= 25 words)",
                    "suggestion": "string (<= 16 words)",
                    "evidence_quotes": ["string (0-2 quotes)"]
                }
            ],
            "overall": {
                "notes": "string (<= 120 words; action-oriented revision plan with 2–4 concrete steps)"
            }
        }
    }


    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        sys_text = (
            "You are a rigorous technical writing reviewer for chemical engineering. "
            "Read holistically; judge based on evidence in the text; avoid keyword scoring. "
            "Return ONLY a valid JSON object that matches the requested schema. Do not include any prose outside JSON."
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
        fb = f"**Technical Report Feedback (degraded)**\n- Error: {e}\nFalling back to structure-only scores.\n"
        return fb, _build_scores_skeleton(rubric), "Model error; no scores.", []

    writing_rows = data.get("writing") or []
    evidence_quotes: List[str] = []
    strict_env = os.getenv("EVIDENCE_STRICT", "1").strip().lower()
    strict_evidence = strict_env not in ("0", "false", "no")

    earned, max_total = 0.0, 0.0
    scores: Dict[str, Any] = {}

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
                s *= 0.8
                w["score"] = s

            earned += s
            scores[name] = {"score": s, "total": t}

            for q in quotes[:2]:
                q_clean = q.strip()
                if q_clean and q_clean not in evidence_quotes:
                    evidence_quotes.append(q_clean)
        except Exception:
            continue


    lines: List[str] = ["**Technical Report Feedback**"]
    if max_total > 0:
        lines.append(f"**Total Score**: {earned:.1f}/{max_total:.1f}")
    lines += ["", "**Overall Summary**"]

    # ---------- Overall Summary ----------
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
        f"Your draft scores **{earned:.1f}/{max_total:.1f}**. "
        "To make this grade-ready, tackle the items below **in order**."
    ]
    if top3:
        steps = []
        for (n, s, t, sug) in top3:
            action = (sug or f"Strengthen {n} with concrete data/figures").rstrip(".")
            steps.append(f"{n}: {action}")
        summary_lines.append("**Revise in this order:** " + " → ".join(steps))
    missing = [n for (n, s, t, _) in weak if s == 0]
    if missing:
        summary_lines.append("**Missing sections:** " + ", ".join(missing[:5]))
    if strong:
        summary_lines.append("**Highlights:** " + ", ".join(n for (n, _, _) in strong[:3]))

    lines += ["\n".join(summary_lines), ""]

    # ---------- Top Priorities + Per-Rubric Breakdown ----------
    priorities = sorted(
        (
            (
                (w.get("name") or "").strip(),
                float(w.get("score") or 0.0),
                float(w.get("total") or 0.0),
                (w.get("suggestion") or "").strip(),
            )
            for w in writing_rows
            if float(w.get("total") or 0.0) > 0.0
        ),
        key=lambda x: (x[1] / x[2]) if x[2] else 0.0
    )
    top = [p for p in priorities if p[2] > 0 and (p[1] / p[2]) < 0.8][:3]

    body: List[str] = []
    if top:
        body.append("**Top Priorities (next steps)**")
        for idx, (name, s, t, sug) in enumerate(top, start=1):
            body.append(f"{idx}. {name}: {s:.1f}/{t:.1f} — {sug}")
        body.append("")

    body.append("**Per-Rubric Breakdown**")
    
    for w in writing_rows:
        try:
            name = str(w.get("name") or "").strip()
            s = float(w.get("score") or 0.0)
            t = float(w.get("total") or 0.0)
            rationale = str(w.get("rationale") or "").strip()
            sug = str(w.get("suggestion") or "").strip()
            ratio = (s / t) if t else 0.0

            if ratio >= 0.8:

                body.append(f" **{name}**: {s:.1f}/{t:.1f}")
                continue

            #  Why / Improve / Evidence
            row = [f" **{name}**: {s:.1f}/{t:.1f}"]
            if rationale:
                row.append(f"  - **Why**: {rationale}")
            if sug and sug.lower() != "none":
                row.append(f"  - **Improve**: {sug}")
            quotes = [q for q in (w.get('evidence_quotes') or []) if isinstance(q, str)]
            if quotes:
                row.append("  - **Evidence**: " + " | ".join(f"“{q.strip()}”" for q in quotes[:2]))
            body += row
        except Exception:
            continue


    final_text = "\n".join(lines + [""] + body).strip()
    summary = str((data.get("overall") or {}).get("notes") or "").strip() or ""
    return final_text, (scores or _build_scores_skeleton(rubric)), summary, evidence_quotes
