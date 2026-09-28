"""Studio package — refactored ePersona Studio backend.

Kept as a wrapper over the submodules so external entry points
(`from server import app`) keep working exactly as before.
"""
from .routes import app
from .studio import STUDIO, Studio

__all__ = ['app', 'Studio', 'STUDIO']