"""
WhatsApp messaging via Evolution API (used by CloudStation).

Evolution API webhook format for incoming messages:
  POST /webhook with body: { "event": "messages.upsert", "data": { "messages": [...] } }

To configure webhook in Evolution API:
  POST {EVOLUTION_API_URL}/webhook/set/{EVOLUTION_INSTANCE}
  Headers: apikey: {EVOLUTION_API_KEY}
  Body: {"webhook": {"url": "{your_railway_url}/webhook", "enabled": true, "events": ["MESSAGES_UPSERT"]}}
"""
import os
import httpx

def _get_evo_base() -> str:
    return os.environ.get("EVOLUTION_API_URL", "").rstrip("/")

def _get_evo_key() -> str:
    return os.environ.get("EVOLUTION_API_KEY", os.environ.get("CLOUDSTATION_TOKEN", ""))

def _get_instance() -> str:
    return os.environ.get("EVOLUTION_INSTANCE", os.environ.get("CLOUDSTATION_CLIENT_ID", ""))


async def send_message(phone: str, text: str) -> bool:
    """Send a WhatsApp text message via Evolution API."""
    base = _get_evo_base()
    if not base:
        print("[CloudStation] EVOLUTION_API_URL not set — cannot send message")
        return False

    instance = _get_instance()
    to = phone.lstrip("+").replace(" ", "")

    async with httpx.AsyncClient(timeout=15.0) as http:
        try:
            resp = await http.post(
                f"{base}/message/sendText/{instance}",
                headers={"apikey": _get_evo_key(), "Content-Type": "application/json"},
                json={"number": to, "text": text},
            )
            if resp.status_code >= 400:
                print(f"[CloudStation] send_message {resp.status_code}: {resp.text}")
                return False
            return True
        except httpx.HTTPStatusError as e:
            print(f"[CloudStation] send_message error {e.response.status_code}: {e.response.text}")
            return False
        except Exception as e:
            print(f"[CloudStation] send_message exception: {e}")
            return False


async def send_document(phone: str, url: str, filename: str, caption: str = "") -> bool:
    """Send a PDF document via Evolution API."""
    base = _get_evo_base()
    if not base:
        return False

    instance = _get_instance()
    to = phone.lstrip("+").replace(" ", "")

    async with httpx.AsyncClient(timeout=20.0) as http:
        try:
            resp = await http.post(
                f"{base}/message/sendMedia/{instance}",
                headers={"apikey": _get_evo_key(), "Content-Type": "application/json"},
                json={
                    "number": to,
                    "mediatype": "document",
                    "media": url,
                    "fileName": filename,
                    "caption": caption,
                },
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            print(f"[CloudStation] send_document error {e.response.status_code}: {e.response.text}")
            return False
        except Exception as e:
            print(f"[CloudStation] send_document exception: {e}")
            return False


async def configure_webhook(webhook_url: str) -> dict:
    """Configure the Evolution API webhook to point to our bot."""
    base = _get_evo_base()
    if not base:
        return {"success": False, "error": "EVOLUTION_API_URL not configured"}

    instance = _get_instance()
    async with httpx.AsyncClient(timeout=15.0) as http:
        try:
            resp = await http.post(
                f"{base}/webhook/set/{instance}",
                headers={"apikey": _get_evo_key(), "Content-Type": "application/json"},
                json={
                    "webhook": {
                        "url": webhook_url,
                        "enabled": True,
                        "webhookByEvents": True,
                        "events": ["MESSAGES_UPSERT"],
                    }
                },
            )
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": e.response.text}
        except Exception as e:
            return {"success": False, "error": str(e)}


def parse_incoming(payload: dict) -> dict | None:
    """
    Parse Evolution API webhook payload (event: MESSAGES_UPSERT).
    Returns {phone, message, message_id} or None.
    """
    try:
        event = payload.get("event", "")
        if event not in ("messages.upsert", "MESSAGES_UPSERT"):
            return None

        data = payload.get("data", {})
        # Evolution API v2 format
        messages = data.get("messages", [data]) if isinstance(data, dict) else [data]
        if not messages:
            return None

        msg = messages[0] if isinstance(messages, list) else messages

        # Skip messages sent by us (fromMe)
        key = msg.get("key", {})
        if key.get("fromMe", False):
            return None

        msg_type = msg.get("messageType", msg.get("type", ""))
        if msg_type not in ("conversation", "extendedTextMessage", "text"):
            return None

        phone = key.get("remoteJid", "").replace("@s.whatsapp.net", "").replace("@c.us", "")
        if not phone:
            return None

        message_obj = msg.get("message", {})
        text = (
            message_obj.get("conversation")
            or message_obj.get("extendedTextMessage", {}).get("text")
            or msg.get("body", "")
        )
        if not text:
            return None

        return {"phone": f"+{phone}", "message": text, "message_id": key.get("id", "")}
    except Exception as e:
        print(f"[CloudStation] parse_incoming error: {e}")
        return None
