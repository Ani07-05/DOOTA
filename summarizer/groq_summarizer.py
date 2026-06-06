import json
import logging

from groq import Groq

from config import settings

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"


def _build_prompt(title: str, content: str, ministry_name: str) -> str:
    return f"""You are summarizing an official Indian government circular.

Ministry: {ministry_name}
Title: {title}

Circular content:
{content[:12000]}

Return ONLY valid JSON with these keys:
- title: string
- published_date: string or null
- summary: 2-3 sentence plain-language summary
- key_points: array of 3-6 bullet strings describing obligations, deadlines, and who is affected
- impact: one sentence on practical impact

Focus only on the circular. Ignore press releases or unrelated content."""


def _parse_response(text: str) -> dict:
    import re as _re

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    # Try standard JSON parse first
    try:
        data = json.loads(cleaned)
        key_points = data.get("key_points", [])
        if isinstance(key_points, list):
            key_points = json.dumps(key_points)
        return {
            "title": data.get("title"),
            "published_date": data.get("published_date"),
            "summary": data.get("summary") or data.get("impact"),
            "key_points": key_points,
            "impact": data.get("impact"),
        }
    except json.JSONDecodeError:
        pass

    # Groq returned key: value prose — extract fields via regex
    def _field(pattern: str) -> str | None:
        m = _re.search(pattern, cleaned, _re.I | _re.DOTALL)
        return m.group(1).strip()[:1000] if m else None

    title = _field(r'"?title"?\s*[:\-]\s*"?([^\n"}{]{5,})"?')
    published_date = _field(r'"?published_date"?\s*[:\-]\s*"?([^\n"}{,]{3,50})"?')
    summary = _field(r'"?summary"?\s*[:\-]\s*"?(.{30,}?)(?:\n"?\w|$)')

    return {
        "title": title,
        "published_date": published_date,
        "summary": summary or cleaned[:500],
        "key_points": json.dumps([]),
        "impact": None,
    }


def summarize_circular(title: str, content: str, ministry_name: str) -> dict:
    if not settings.groq_api_key:
        return {
            "title": title,
            "published_date": None,
            "summary": content[:500],
            "key_points": json.dumps([]),
        }

    client = Groq(api_key=settings.groq_api_key)
    prompt = _build_prompt(title, content, ministry_name)

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You summarize Indian government circulars accurately and concisely.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            text = response.choices[0].message.content or ""
            return _parse_response(text)
        except Exception as exc:
            logger.warning("Groq summarization failed with %s: %s", model, exc)

    return {
        "title": title,
        "published_date": None,
        "summary": content[:500],
        "key_points": json.dumps([]),
    }
