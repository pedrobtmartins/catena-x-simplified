"""ASGI entry point: ``uvicorn catenax_simplified.main:app``."""

import logging

from .api import create_app
from .config import Settings

logging.basicConfig(level=logging.INFO)

app = create_app(Settings())
