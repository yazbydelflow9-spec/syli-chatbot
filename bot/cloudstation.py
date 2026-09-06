"""CloudStation WhatsApp API client."""
import os
import httpx

# CloudStation base URL — token format: xxxxxx#hash
_BASE = "https://app.cloudstation.com.my/api"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['CLOUDSTATION_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def send_message(phone: str, text: str) -> bool:
    """Send a WhatsApp text message. Phone in international format e.g. +224XXXXXXXX"""
    client_id = os.environ["CLOUDSTATION_CLIENT_ID"]
    # Normalize phone: remove leading + or spaces
    to = phone.lstrip("+").replace(" ", "")

    payload = {
        "client_id": client_id,
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=15.0) as http:
        try:
            resp = await http.post(
                f"{_BASE}/messages/send",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            print(f"[CloudStation] send_message error {e.response.status_code}: {e.response.text}")
            return False
        except Exception as e:
            print(f"[CloudStation] send_message exception: {e}")
            return False


async def send_document(phone: str, url: str, filename: str, caption: str = "") -> bool:
    """Send a PDF document via URL."""
    client_id = os.environ["CLOUDSTATION_CLIENT_ID"]
    to = phone.lstrip("+").replace(" ", "")

    payload = {
        "client_id": client_id,
        "to": to,
        "type": "document",
        "document": {
            "link": url,
            "filename": filename,
            "caption": caption,
        },
    }

    async with httpx.AsyncClient(timeout=20.0) as http:
        try:
            resp = await http.post(
                f"{_BASE}/messages/send",
                headers=_headers(),
                json=payload,
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
    """Configure the CloudStation webhook URL for incoming messages."""
    client_id = os.environ["CLOUDSTATION_CLIENT_ID"]
    async with httpx.AsyncClient(timeout=15.0) as http:
        try:
            resp = await http.post(
                f"{_BASE}/webhooks/configure",
                headers=_headers(),
                json={
                    "client_id": client_id,
                    "webhook_url": webhook_url,
                    "events": ["message.received"],
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
    Parse incoming CloudStation webhook payload.
    Returns dict with {phone, message, message_id} or None if not a text message.
    """
    try:
        # CloudStation webhook structure — adapt if format differs
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        msg_type = msg.get("type")
        if msg_type != "text":
            return None

        phone = msg.get("from", "")
        text = msg.get("text", {}).get("body", "")
        message_id = msg.get("id", "")

        if not phone or not text:
            return None

        return {"phone": f"+{phone}", "message": text, "message_id": message_id}
    except Exception as e:
        print(f"[CloudStation] parse_incoming error: {e}")
        return None
