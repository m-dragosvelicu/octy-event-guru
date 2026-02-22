import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import events, health, ingest
from .core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)
logger.info("Starting FastAPI app")

app = FastAPI(title="event-guru")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(events.router)
