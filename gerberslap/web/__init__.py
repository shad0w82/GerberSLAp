"""The web app: a thin API over the services, and the page that uses it."""
from .app import create_app

__all__ = ["create_app"]
