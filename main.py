"""Syli Study Malaysia — WhatsApp chatbot + dashboard API."""
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from bot.memory import (
    get_or_create_client,
    update_client,
    get_history,
    save_message,
    is_bot_active,
    is_client_paused,
    get_all_clients,
    get_client_messages,
    get_stats,
    get_db,
)
from bot.brain import generate_response
from bot.cloudstation import parse_incoming, send_message, send_document, configure_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Syli] Bot started. Waiting for messages...")
    yield
    print("[Syli] Bot shutting down.")


app = FastAPI(title="Syli Study Malaysia Bot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# WhatsApp webhook
# ---------------------------------------------------------------------------

@app.get("/webhook")
async def webhook_verify(request: Request):
    """CloudStation webhook verification challenge."""
    params = dict(request.query_params)
    challenge = params.get("hub.challenge", params.get("challenge", ""))
    return HTMLResponse(content=str(challenge))


@app.post("/webhook")
async def webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages from CloudStation."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "ok"})

    parsed = parse_incoming(payload)
    if not parsed:
        return JSONResponse({"status": "ok"})

    # Fire-and-forget so CloudStation gets 200 immediately
    background_tasks.add_task(handle_message, parsed["phone"], parsed["message"])
    return JSONResponse({"status": "ok"})


async def handle_message(phone: str, user_message: str):
    """Full message processing pipeline."""
    try:
        # Guard: global bot switch
        if not is_bot_active():
            return

        # Guard: per-client pause
        if is_client_paused(phone):
            return

        # Get or create client record
        client = get_or_create_client(phone)
        client_id = client["id"]

        # Load conversation history
        history = get_history(client_id, limit=20)

        # Save user message
        save_message(client_id, "user", user_message)

        # Generate AI response
        response_text, client_updates = await generate_response(client, history, user_message)

        # Update client profile with inferred data
        if client_updates:
            update_client(phone, client_updates)

        # Save bot response
        save_message(client_id, "assistant", response_text)

        # Send reply via CloudStation
        await send_message(phone, response_text)

        # Auto-send guide PDF if newly qualified and guide not yet sent
        client_fresh = get_or_create_client(phone)
        guide_url = os.getenv("GUIDE_PDF_URL", "")
        if (
            guide_url
            and not client_fresh.get("guide_sent")
            and client_fresh.get("stage") in ("interested", "qualified")
            and len(history) >= 3
        ):
            sent = await send_document(
                phone,
                guide_url,
                "Syli Study Malaysia — Guide Complet.pdf",
                "Voici notre guide complet pour étudier en Malaisie",
            )
            if sent:
                update_client(phone, {"guide_sent": True})

    except Exception as e:
        print(f"[Syli] handle_message error for {phone}: {e}")


# ---------------------------------------------------------------------------
# Dashboard REST API
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats():
    return get_stats()


@app.get("/api/clients")
async def api_clients():
    return get_all_clients()


@app.get("/api/clients/{client_id}/messages")
async def api_client_messages(client_id: str):
    return get_client_messages(client_id)


class ClientUpdate(BaseModel):
    stage: str | None = None
    name: str | None = None
    notes: str | None = None
    is_bot_paused: bool | None = None
    is_archived: bool | None = None


@app.patch("/api/clients/{client_id}")
async def api_update_client(client_id: str, body: ClientUpdate):
    db = get_db()
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    res = db.table("clients").update(fields).eq("id", client_id).execute()
    if not res.data:
        raise HTTPException(404, "Client not found")
    return res.data[0]


class BotToggle(BaseModel):
    is_active: bool


@app.post("/api/bot/toggle")
async def api_bot_toggle(body: BotToggle):
    db = get_db()
    db.table("bot_config").upsert({"id": 1, "is_active": body.is_active}).execute()
    return {"is_active": body.is_active}


@app.get("/api/bot/status")
async def api_bot_status():
    return {"is_active": is_bot_active()}


class WebhookConfig(BaseModel):
    webhook_url: str


@app.post("/api/configure-webhook")
async def api_configure_webhook(body: WebhookConfig):
    result = await configure_webhook(body.webhook_url)
    return result


# ---------------------------------------------------------------------------
# Dashboard frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard", "index.html")
    with open(dashboard_path, encoding="utf-8") as f:
        return HTMLResponse(f.read())
