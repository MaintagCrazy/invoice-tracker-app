#!/usr/bin/env python3
"""
Invoice Tracker App - FastAPI Backend
Using Google Sheets as the database
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from routers import invoices_router, clients_router, chat_router, email_router, payments_router
from config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle hooks"""
    logger.info("Starting Invoice Tracker App...")
    logger.info("Using Google Sheets as database")
    logger.info("Invoice Tracker App started!")

    yield

    logger.info("Shutting down Invoice Tracker App...")


# Create FastAPI app
app = FastAPI(
    title="Invoice Tracker App",
    description="AI-powered invoice creation and tracking - Google Sheets backend",
    version="2.0.0",
    lifespan=lifespan
)

# CORS - allow all for simplicity
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(invoices_router)
app.include_router(clients_router)
app.include_router(chat_router)
app.include_router(email_router)
app.include_router(payments_router)

# Serve static files (frontend)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "static")), name="static")


@app.get("/")
async def root():
    """Serve frontend or show API info"""
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "app": "Invoice Tracker App",
        "version": "2.0.0",
        "database": "Google Sheets",
        "endpoints": {
            "invoices": "/api/invoices",
            "clients": "/api/clients",
            "chat": "/api/chat",
            "docs": "/docs"
        }
    }


@app.get("/chat")
async def chat_page():
    """Serve chat interface"""
    chat_path = os.path.join(frontend_path, "chat.html")
    if os.path.exists(chat_path):
        return FileResponse(chat_path)
    return {"error": "Chat page not found"}


@app.get("/client")
async def client_page():
    """Serve client detail page"""
    client_path = os.path.join(frontend_path, "client.html")
    if os.path.exists(client_path):
        return FileResponse(client_path)
    return {"error": "Client page not found"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Test sheets connection
    sheets_ok = False
    try:
        from services.sheets_database import get_sheets_db
        db = get_sheets_db()
        db.get_clients()  # Quick test
        sheets_ok = True
    except Exception as e:
        logger.error(f"Sheets connection error: {e}")

    return {
        "status": "healthy" if sheets_ok else "degraded",
        "database": "google_sheets",
        "sheets_connected": sheets_ok,
        "ai_configured": bool(config.OPENROUTER_API_KEY),
        "email_configured": bool(config.GMAIL_TOKEN_B64)
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True,
        log_level="info"
    )
