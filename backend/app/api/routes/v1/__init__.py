"""API v1 router aggregation."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from fastapi import APIRouter

from app.api.routes.v1 import health
from app.api.routes.v1 import auth, users
from app.api.routes.v1 import sessions
from app.api.routes.v1 import items
from app.api.routes.v1 import conversations
from app.api.routes.v1 import webhooks
from app.api.routes.v1 import ws
from app.api.routes.v1 import agent
from app.api.routes.v1 import files
from app.api.routes.v1 import admin_settings
from app.api.routes.v1 import storage_proxy
from app.api.routes.v1 import plans

v1_router = APIRouter()

# Health check routes (no auth required)
v1_router.include_router(health.router, tags=["health"])

# Authentication routes
v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# User routes
v1_router.include_router(users.router, prefix="/users", tags=["users"])

# Session management routes
v1_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])

# Example CRUD routes (items)
v1_router.include_router(items.router, prefix="/items", tags=["items"])

# Conversation routes (AI chat persistence)
v1_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])

# Webhook routes
v1_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])

# WebSocket routes
v1_router.include_router(ws.router, tags=["websocket"])

# AI Agent routes
v1_router.include_router(agent.router, tags=["agent"])

# File storage routes
v1_router.include_router(files.router, prefix="/files", tags=["files"])

# Admin settings routes
v1_router.include_router(admin_settings.router, prefix="/admin/settings", tags=["admin"])

# Plan routes
v1_router.include_router(plans.router, prefix="/plans", tags=["plans"])

# Storage proxy for sandbox containers (uses sandbox tokens, not user auth)
v1_router.include_router(storage_proxy.router, prefix="/storage", tags=["storage"])
