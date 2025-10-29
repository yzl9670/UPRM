from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List


def _normalize_item(name: str, criteria: List[Dict[str, Any]]) -> Dict[str, Any]:
    name = (name or "").strip()
    # Ensure points are numeric
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in criteria or []:
        try:
            pts = float(c.get("points"))
        except Exception:
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(c.get("points") or ""))
            pts = float(m.group(1)) if m else 0.0
        desc = str(c.get("description") or "").strip()
        key = (pts, desc)
        if key in seen:
            continue
        seen.add(key)
        out.append({"points": pts, "description": desc})
    if not out:
        out = [
            {"points": 4, "description": "Excellent."},
            {"points": 3, "description": "Good."},
            {"points": 2, "description": "Fair."},
            {"points": 1, "description": "Poor."},
            {"points": 0, "description": "Insufficient."},
        ]
    return {"name": name or "Untitled", "scoringCriteria": out}


def _heuristic_extract(text: str) -> List[Dict[str, Any]]:
    """Lightweight heuristic extraction when LLM is not available.
    Attempts to find rubric-like sections and build items with 0..max levels.
    """
    lines = [re.sub(r"\s+", " ", ln.strip()) for ln in text.splitlines()]
    # Narrow to a window after the word "rubric" if present
    joined = "\n".join(lines)
    idx = re.search(r"rubric", joined, re.I)
    if idx:
        start = max(0, idx.start() - 200)
        joined = joined[start:start + 8000]
        lines = joined.splitlines()

    items: List[Dict[str, Any]] = []
    current_name: str | None = None
    current_criteria: List[Dict[str, Any]] = []

    def push():
        nonlocal current_name, current_criteria
        if current_name:
            items.append(_normalize_item(current_name, current_criteria))
        current_name, current_criteria = None, []

    cat_re = re.compile(r"^([A-Z][A-Za-z0-9 ,/&()\-]{3,})\s*(?:\([^)]+\))?\s*[:\-]?$")
    crit_re1 = re.compile(r"^(?:-\s*)?(\d{1,2})\s*(?:points?|pts?)\s*[:\-]\s*(.+)$", re.I)
    crit_re2 = re.compile(r"^(?:-\s*)?(\d{1,2})\s*[:\-]\s*(.+)$")

    for ln in lines:
        if not ln:
            continue
        m = cat_re.match(ln)
        if m and len(ln.split()) <= 8:
            # Treat as a new category heading
            push()
            current_name = m.group(1).strip()
            continue

        m1 = crit_re1.match(ln)
        if m1 and current_name:
            pts = float(m1.group(1))
            desc = m1.group(2).strip()
            current_criteria.append({"points": pts, "description": desc})
            continue

        m2 = crit_re2.match(ln)
        if m2 and current_name:
            pts = float(m2.group(1))
            desc = m2.group(2).strip()
            # Only keep if description is long enough to be meaningful
            if len(desc) >= 6:
                current_criteria.append({"points": pts, "description": desc})
            continue

    push()

    # Fallback skeleton if nothing found
    if not items:
        defaults = [
            ("Executive Summary", [4,3,2,1,0]),
            ("Context: Puerto Rico", [4,3,2,1,0]),
            ("Process Description & Flows", [5,4,3,2,0]),
            ("Safety & Environmental", [4,3,2,1,0]),
            ("Economic Analysis", [4,3,2,1,0]),
            ("Data, Methods, and Rigor", [5,4,3,2,0]),
            ("Figures, Tables, and Formatting", [3,2,1,0]),
            ("Writing Quality", [3,2,1,0]),
        ]
        for nm, pts in defaults:
            items.append(_normalize_item(nm, [{"points": p, "description": ""} for p in pts]))
    return items


def _llm_extract(text: str) -> List[Dict[str, Any]] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        sys = (
            "You extract grading rubrics for technical report writing from syllabi. "
            "Return ONLY a JSON array. Each item: {name, scoringCriteria:[{points:number, description:string}]}. "
            "Prefer 3-6 clear items; keep descriptions short and concrete."
        )
        user = json.dumps({
            "syllabus_excerpt": text[:12000],
            "format": [
                {"name": "Executive Summary", "scoringCriteria": [
                    {"points": 4, "description": "Clear problem, approach, key results, and recommendation."},
                    {"points": 3, "description": "Mostly clear; minor missing elements."}
                ]}
            ]
        }, ensure_ascii=False)
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
        data = json.loads(content)
        arr = data if isinstance(data, list) else data.get("rubric") if isinstance(data, dict) else None
        if isinstance(arr, list) and arr:
            cleaned = [_normalize_item(str(x.get("name") or ""), x.get("scoringCriteria") or []) for x in arr]
            return cleaned
        return None
    except Exception:
        return None


def extract_rubric_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract rubric items from syllabus text.
    Uses LLM when available, else a lightweight heuristic.
    """
    text = (text or "").strip()
    if not text:
        return []
    llm = _llm_extract(text)
    if llm:
        return llm
    return _heuristic_extract(text)

