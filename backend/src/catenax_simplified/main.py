"""ASGI entry point: ``uvicorn catenax_simplified.main:app``."""

import logging

from .api import create_app
from .config import Settings
from .trust import install_extra_ca_certificates

logging.basicConfig(level=logging.INFO)

settings = Settings()
install_extra_ca_certificates(settings.extra_ca_dir)
app = create_app(settings)
