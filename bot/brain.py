"""OpenRouter AI brain — generates Syli's responses."""
import os
import re
import json
import httpx
from .knowledge import build_system_prompt

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")

_UPDATE_RE = re.compile(r'<UPDATE>(.*?)</UPDATE>', re.DOTALL)

_FRENCH_WORDS = {"je", "tu", "il", "nous", "vous", "bonjour", "merci", "comment", "est", "pour", "que", "qui", "avec", "pas", "une", "des", "mon", "ma", "je", "suis", "oui", "non", "mais"}


def _detect_language(text: str) -> str:
    words = set(text.lower().split())
    return "fr" if len(words & _FRENCH_WORDS) >= 2 else "en"


def _parse_update_block(raw: str) -> tuple[str, dict]:
    """Extract <UPDATE>...</UPDATE> from raw response, return (clean_text, extracted_fields)."""
    match = _UPDATE_RE.search(raw)
    if not match:
        return raw.strip(), {}
    clean = _UPDATE_RE.sub("", raw).strip()
    try:
        extracted = json.loads(match.group(1))
    except Exception:
        return clean, {}

    allowed = {"name", "bac_level", "desired_programme", "stage", "ready_for_human"}
    valid_stages = {"lead", "interested", "qualified", "docs_submitted", "payment_pending", "visa_pending", "visa_approved", "arrived"}

    updates = {}
    for key in allowed:
        val = extracted.get(key)
        if val is None or val == "null":
            continue
        if key == "stage" and val not in valid_stages:
            continue
        if key == "ready_for_human" and val is True:
            updates["ready_for_human"] = True
            continue
        if isinstance(val, str) and val.strip():
            updates[key] = val.strip()

    return clean, updates


async def generate_response(client: dict, history: list[dict], user_message: str) -> tuple[str, dict]:
    """Returns (response_text, client_updates_dict)."""
    system_prompt = build_system_prompt(client)

    detected_lang = _detect_language(user_message)
    client_updates: dict = {"language": detected_lang}

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-18:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "HTTP-Referer": "https://sylystudy.com",
                "X-Title": "Syli Study Malaysia Bot",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": messages,
                "max_tokens": 600,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    raw_text = data["choices"][0]["message"]["content"]
    response_text, ai_updates = _parse_update_block(raw_text)

    # Merge AI-extracted fields (don't overwrite existing DB values with null)
    ready_for_human = ai_updates.pop("ready_for_human", False)
    for key, val in ai_updates.items():
        if val:
            client_updates[key] = val

    # Auto-advance lead → interested after 2+ messages of engagement
    if client.get("stage") == "lead" and len(history) >= 2:
        client_updates.setdefault("stage", "interested")

    # If all three qualification fields are now known, ensure stage = qualified
    final_name = client_updates.get("name") or client.get("name")
    final_bac = client_updates.get("bac_level") or client.get("bac_level")
    final_prog = client_updates.get("desired_programme") or client.get("desired_programme")
    if final_name and final_bac and final_prog and client.get("stage") in ("lead", "interested"):
        client_updates["stage"] = "qualified"

    # When ready for human: pause bot and note it in the record
    if ready_for_human:
        client_updates["is_bot_paused"] = True
        existing_notes = client.get("notes") or ""
        client_updates["notes"] = (existing_notes + "\n[BOT] Client demande à parler à l'équipe.").strip()

    # Mark guide as sent if response mentions sending it
    guide_keywords = ["guide complet", "complete guide", "je vous envoie", "voici notre guide"]
    if any(kw in response_text.lower() for kw in guide_keywords):
        client_updates["guide_sent"] = True

    return response_text, client_updates
