"""Supabase client memory — per-client conversation history and profile."""
import os
from datetime import datetime, timezone
from supabase import create_client, Client

_client: Client | None = None

def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


def get_or_create_client(phone: str) -> dict:
    db = get_db()
    res = db.table("clients").select("*").eq("phone", phone).single().execute()
    if res.data:
        db.table("clients").update({"last_contact": datetime.now(timezone.utc).isoformat()}).eq("phone", phone).execute()
        return res.data
    new = db.table("clients").insert({"phone": phone, "stage": "lead"}).execute()
    return new.data[0]


def update_client(phone: str, fields: dict) -> dict:
    db = get_db()
    res = db.table("clients").update(fields).eq("phone", phone).execute()
    return res.data[0] if res.data else {}


def get_history(client_id: str, limit: int = 20) -> list[dict]:
    db = get_db()
    res = (
        db.table("messages")
        .select("role, content, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data or []))


def save_message(client_id: str, role: str, content: str):
    get_db().table("messages").insert({
        "client_id": client_id,
        "role": role,
        "content": content,
    }).execute()


def is_bot_active() -> bool:
    db = get_db()
    res = db.table("bot_config").select("is_active").eq("id", 1).single().execute()
    return res.data.get("is_active", True) if res.data else True


def is_client_paused(phone: str) -> bool:
    db = get_db()
    res = db.table("clients").select("is_bot_paused").eq("phone", phone).single().execute()
    return res.data.get("is_bot_paused", False) if res.data else False


def get_all_clients() -> list[dict]:
    db = get_db()
    res = (
        db.table("clients")
        .select("*")
        .eq("is_archived", False)
        .order("last_contact", desc=True)
        .execute()
    )
    return res.data or []


def get_client_messages(client_id: str) -> list[dict]:
    db = get_db()
    res = (
        db.table("messages")
        .select("*")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return list(reversed(res.data or []))


def get_stats() -> dict:
    db = get_db()
    clients = db.table("clients").select("stage, created_at, last_contact").eq("is_archived", False).execute().data or []
    today = datetime.now(timezone.utc).date().isoformat()
    stages = {}
    active_today = 0
    for c in clients:
        s = c.get("stage", "lead")
        stages[s] = stages.get(s, 0) + 1
        if c.get("last_contact", "")[:10] == today:
            active_today += 1
    return {
        "total": len(clients),
        "active_today": active_today,
        "by_stage": stages,
    }
