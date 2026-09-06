"""Reusable clients; importing this package needs no Arduino runtime."""
from .client import PresenceClient, PresenceError

__all__ = ['PresenceClient', 'PresenceError']
