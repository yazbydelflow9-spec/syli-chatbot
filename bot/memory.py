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
    res = db.table("clients").select("*").eq("phone", phone).limit(1).execute()
    if res.data:
        db.table("clients").update({"last_contact": datetime.now(timezone.utc).isoformat()}).eq("phone", phone).execute()
        return res.data[0]
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
    res = db.table("bot_config").select("is_active").eq("id", 1).limit(1).execute()
    return res.data[0].get("is_active", True) if res.data else True


def is_client_paused(phone: str) -> bool:
    db = get_db()
    res = db.table("clients").select("is_bot_paused").eq("phone", phone).limit(1).execute()
    return res.data[0].get("is_bot_paused", False) if res.data else False


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
    clients = db.table("clients").select("stage, created_at, last_contact, guide_sent").eq("is_archived", False).execute().data or []
    today = datetime.now(timezone.utc).date().isoformat()
    week_start = (datetime.now(timezone.utc).date() - __import__('datetime').timedelta(days=7)).isoformat()
    stages = {}
    active_today = 0
    active_week = 0
    guide_sent = 0
    for c in clients:
        s = c.get("stage", "lead")
        stages[s] = stages.get(s, 0) + 1
        lc = c.get("last_contact", "")[:10]
        if lc == today:
            active_today += 1
        if lc >= week_start:
            active_week += 1
        if c.get("guide_sent"):
            guide_sent += 1
    # Revenue forecast: clients in qualified+ stages × 15M GNF
    revenue_stages = {"qualified", "docs_submitted", "payment_pending", "visa_pending", "visa_approved", "arrived"}
    pipeline_clients = sum(stages.get(s, 0) for s in revenue_stages)
    return {
        "total": len(clients),
        "active_today": active_today,
        "active_week": active_week,
        "guide_sent": guide_sent,
        "by_stage": stages,
        "revenue_forecast_gnf": pipeline_clients * 15_000_000,
        "pipeline_clients": pipeline_clients,
    }


def get_weekly_new_leads(weeks: int = 8) -> list[dict]:
    """Returns new leads per week for the last N weeks."""
    db = get_db()
    import datetime as dt
    result = []
    now = datetime.now(timezone.utc)
    for i in range(weeks - 1, -1, -1):
        week_start = (now - dt.timedelta(weeks=i + 1)).date()
        week_end = (now - dt.timedelta(weeks=i)).date()
        res = db.table("clients").select("id", count="exact").gte("created_at", week_start.isoformat()).lt("created_at", week_end.isoformat()).execute()
        label = f"S-{i}" if i > 0 else "Cette sem."
        result.append({"week": label, "count": res.count or 0, "start": week_start.isoformat()})
    return result


def get_response_time_stats(days: int = 7) -> list[dict]:
    """Average bot response time per day (seconds)."""
    db = get_db()
    import datetime as dt
    result = []
    now = datetime.now(timezone.utc)
    for i in range(days - 1, -1, -1):
        day = (now - dt.timedelta(days=i)).date()
        day_str = day.isoformat()
        msgs = db.table("messages").select("role, created_at").gte("created_at", day_str).lt("created_at", (day + dt.timedelta(days=1)).isoformat()).order("created_at").execute().data or []
        times = []
        for j in range(1, len(msgs)):
            if msgs[j]["role"] == "assistant" and msgs[j-1]["role"] == "user":
                try:
                    t1 = datetime.fromisoformat(msgs[j-1]["created_at"].replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(msgs[j]["created_at"].replace("Z", "+00:00"))
                    diff = (t2 - t1).total_seconds()
                    if 0 < diff < 60:
                        times.append(diff)
                except Exception:
                    pass
        avg = round(sum(times) / len(times), 1) if times else 0
        label = day.strftime("%d/%m") if i > 0 else "Auj."
        result.append({"day": label, "avg_seconds": avg, "count": len(times)})
    return result


def get_clients_by_stage(stage: str) -> list[dict]:
    """Get all active clients in a specific stage."""
    db = get_db()
    res = db.table("clients").select("*").eq("stage", stage).eq("is_archived", False).eq("is_bot_paused", False).execute()
    return res.data or []
