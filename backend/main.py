#!/usr/bin/env python3
"""
Invoice Tracker App - FastAPI Backend

Main application entry point with:
- REST API endpoints for invoices, clients, chat
- PDF generation with WeasyPrint
- Email sending via Gmail API
- AI chat with OpenRouter/Gemini Flash
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from models.database import init_db, SessionLocal, seed_default_clients
from routers import invoices_router, clients_router, chat_router, email_router
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

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Seed default clients
    db = SessionLocal()
    try:
        seed_default_clients(db)
        logger.info("Default clients seeded")
    finally:
        db.close()

    logger.info("Invoice Tracker App started!")
    logger.info("API docs: http://localhost:8000/docs")

    yield

    logger.info("Shutting down Invoice Tracker App...")
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Invoice Tracker App",
    description="AI-powered invoice creation and tracking",
    version="1.0.0",
    lifespan=lifespan
)

# CORS settings
ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "").split(",") if os.environ.get("CORS_ORIGINS") else []
DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
]

all_origins = list(set(DEFAULT_ORIGINS + [o.strip() for o in ALLOWED_ORIGINS if o.strip()]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=all_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(invoices_router)
app.include_router(clients_router)
app.include_router(chat_router)
app.include_router(email_router)

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
        "version": "1.0.0",
        "status": "running",
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


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "database": "connected",
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
