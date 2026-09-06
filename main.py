"""Syli Study Malaysia — WhatsApp chatbot + dashboard API."""
import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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
    get_weekly_new_leads,
    get_response_time_stats,
    get_clients_by_stage,
    get_db,
)
from bot.brain import generate_response
from bot.cloudstation import parse_incoming, send_message, send_document, configure_webhook

STAGE_NOTIFICATIONS = {
    "interested": "Bonjour ! Merci de votre intérêt pour Syli Study Malaysia. Je suis là pour répondre à toutes vos questions !",
    "qualified": "Parfait ! Votre profil a été enregistré. Notre équipe va préparer votre dossier d'admission. Des questions ?",
    "docs_submitted": "Vos documents ont été reçus et sont en cours de traitement. Nous vous tiendrons informé des prochaines étapes.",
    "payment_pending": "Votre dossier est prêt. Notre équipe vous contactera bientôt pour les modalités de paiement.",
    "visa_pending": "Votre demande de visa a été soumise à l'EMGS. Le traitement prend généralement 6-10 semaines. Nous vous tiendrons informé !",
    "visa_approved": "FÉLICITATIONS ! Votre visa malaisien est approuvé ! Nous allons maintenant préparer votre départ. Quand souhaitez-vous partir ?",
    "arrived": "Bienvenue en Malaisie ! Aliou de notre équipe va vous contacter pour l'accueil. Bon courage pour cette nouvelle aventure !",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Syli] Bot started.")
    yield


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
    params = dict(request.query_params)
    challenge = params.get("hub.challenge", params.get("challenge", ""))
    return HTMLResponse(content=str(challenge))


@app.post("/webhook")
async def webhook_receive(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "ok"})
    parsed = parse_incoming(payload)
    if not parsed:
        return JSONResponse({"status": "ok"})
    background_tasks.add_task(handle_message, parsed["phone"], parsed["message"])
    return JSONResponse({"status": "ok"})


async def handle_message(phone: str, user_message: str):
    try:
        if not is_bot_active():
            return
        if is_client_paused(phone):
            return

        client = get_or_create_client(phone)
        client_id = client["id"]
        history = get_history(client_id, limit=20)
        save_message(client_id, "user", user_message)

        response_text, client_updates = await generate_response(client, history, user_message)

        if client_updates:
            update_client(phone, client_updates)
        save_message(client_id, "assistant", response_text)
        await send_message(phone, response_text)

        client_fresh = get_or_create_client(phone)
        guide_url = os.getenv("GUIDE_PDF_URL", "")
        if (
            guide_url
            and not client_fresh.get("guide_sent")
            and client_fresh.get("stage") in ("interested", "qualified")
            and len(history) >= 3
        ):
            sent = await send_document(
                phone, guide_url,
                "Syli Study Malaysia — Guide Complet.pdf",
                "Voici notre guide complet pour étudier en Malaisie",
            )
            if sent:
                update_client(phone, {"guide_sent": True})

    except Exception as e:
        print(f"[Syli] handle_message error for {phone}: {e}")


# ---------------------------------------------------------------------------
# Dashboard REST API — Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def api_stats():
    return get_stats()


@app.get("/api/stats/weekly")
async def api_weekly():
    return get_weekly_new_leads(8)


@app.get("/api/stats/response-time")
async def api_response_time():
    return get_response_time_stats(7)


@app.get("/api/stats/funnel")
async def api_funnel():
    stats = get_stats()
    stages = ["lead", "interested", "qualified", "docs_submitted", "visa_pending", "visa_approved", "arrived"]
    labels = ["Lead", "Intéressé", "Qualifié", "Docs soumis", "Visa en cours", "Visa approuvé", "Arrivé"]
    by_stage = stats.get("by_stage", {})
    return [{"stage": s, "label": l, "count": by_stage.get(s, 0)} for s, l in zip(stages, labels)]


# ---------------------------------------------------------------------------
# Dashboard REST API — Clients
# ---------------------------------------------------------------------------

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
    notify: bool = False  # if True, send stage notification message


@app.patch("/api/clients/{client_id}")
async def api_update_client(client_id: str, body: ClientUpdate, background_tasks: BackgroundTasks):
    db = get_db()
    fields = {k: v for k, v in body.model_dump(exclude={"notify"}).items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    res = db.table("clients").update(fields).eq("id", client_id).execute()
    if not res.data:
        raise HTTPException(404, "Client not found")
    client = res.data[0]
    if body.notify and body.stage and body.stage in STAGE_NOTIFICATIONS:
        background_tasks.add_task(send_message, client["phone"], STAGE_NOTIFICATIONS[body.stage])
        save_message(client_id, "assistant", STAGE_NOTIFICATIONS[body.stage])
    return client


class DirectMessage(BaseModel):
    message: str


@app.post("/api/clients/{client_id}/send")
async def api_send_direct(client_id: str, body: DirectMessage, background_tasks: BackgroundTasks):
    db = get_db()
    res = db.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(404, "Client not found")
    client = res.data
    background_tasks.add_task(send_message, client["phone"], body.message)
    save_message(client_id, "assistant", body.message)
    return {"sent": True}


# ---------------------------------------------------------------------------
# Dashboard REST API — Broadcast
# ---------------------------------------------------------------------------

class Broadcast(BaseModel):
    stage: str
    message: str


@app.post("/api/broadcast")
async def api_broadcast(body: Broadcast, background_tasks: BackgroundTasks):
    clients = get_clients_by_stage(body.stage)
    if not clients:
        return {"sent": 0, "stage": body.stage}

    async def do_broadcast():
        for c in clients:
            await send_message(c["phone"], body.message)
            save_message(c["id"], "assistant", body.message)
            await asyncio.sleep(0.5)

    background_tasks.add_task(do_broadcast)
    return {"sent": len(clients), "stage": body.stage, "message": body.message}


# ---------------------------------------------------------------------------
# Dashboard REST API — Bot control
# ---------------------------------------------------------------------------

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
    return await configure_webhook(body.webhook_url)


# ---------------------------------------------------------------------------
# Dashboard frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    path = os.path.join(os.path.dirname(__file__), "dashboard", "index.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())
