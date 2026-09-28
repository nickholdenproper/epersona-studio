"""ePersona Studio — FastAPI backend.

Thin compatibility shim over the `studio` package. All application logic now
lives in `studio/`; this file exists so `main.py` (which does
`from server import app`) and any other legacy import keep working unchanged.
"""
from studio.routes import app
from studio.studio import STUDIO, Studio

__all__ = ['app', 'Studio', 'STUDIO']