"""OpenRouter AI brain — generates Syli's responses."""
import os
import httpx
from .knowledge import build_system_prompt

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")


def _detect_language(text: str) -> str:
    """Simple language detection based on common French/English words."""
    french_words = {"je", "tu", "il", "nous", "vous", "bonjour", "merci", "comment", "est", "pour", "que", "qui", "avec", "pas", "une", "des"}
    words = set(text.lower().split())
    if len(words & french_words) >= 2:
        return "fr"
    return "en"


def _extract_client_updates(response_text: str, user_message: str) -> dict:
    """Heuristically detect if conversation reveals client info to update."""
    updates = {}
    lower = user_message.lower()

    # Detect programme interest
    programme_keywords = {
        "it": "IT / Cybersécurité",
        "informatique": "IT / Cybersécurité",
        "cybersécurité": "IT / Cybersécurité",
        "cybersecurite": "IT / Cybersécurité",
        "business": "Business",
        "gestion": "Business",
        "commerce": "Business",
        "ingénierie": "Ingénierie",
        "ingenierie": "Ingénierie",
        "mécanique": "Ingénierie",
        "aviation": "Aviation",
        "médecine": "Médecine",
        "pharmacie": "Médecine",
        "communication": "Communication / Médias",
        "design": "Communication / Médias",
    }
    for kw, prog in programme_keywords.items():
        if kw in lower:
            updates["desired_programme"] = prog
            break

    # Detect stage progression
    if any(w in lower for w in ["intéressé", "interessé", "je veux", "je voudrais", "comment faire", "comment s'inscrire"]):
        updates["stage"] = "interested"

    return updates


async def generate_response(client: dict, history: list[dict], user_message: str) -> tuple[str, dict]:
    """
    Returns (response_text, client_updates_dict).
    client_updates_dict contains fields to update in Supabase.
    """
    system_prompt = build_system_prompt(client)

    # Detect language from latest message
    detected_lang = _detect_language(user_message)
    client_updates = {"language": detected_lang}

    # Build message history for OpenRouter
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-18:]:  # Keep last 18 messages + new one = 19 total
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
                "max_tokens": 500,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    response_text = data["choices"][0]["message"]["content"].strip()

    # Detect client info updates from this exchange
    prog_updates = _extract_client_updates(response_text, user_message)
    client_updates.update(prog_updates)

    # Auto-advance stage: lead → interested if they're engaging
    if client.get("stage") == "lead" and len(history) >= 2:
        client_updates.setdefault("stage", "interested")

    # Mark guide as sent if response mentions sending it
    guide_keywords = ["guide complet", "complete guide", "je vous envoie", "voici notre guide"]
    if any(kw in response_text.lower() for kw in guide_keywords):
        client_updates["guide_sent"] = True

    return response_text, client_updates
