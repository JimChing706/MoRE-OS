"""Optional FastAPI server.

Requires ``pip install more-core[api]``.
"""

from .server import create_app

__all__ = ["create_app"]
