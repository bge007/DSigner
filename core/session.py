"""
Session persistence: remembers open files, page, zoom and signature
placement so the next launch restores where you left off.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

SESSION_DIR = os.path.join(
    os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "DSigner")
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")


def save_session(data):
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed to save session")


def load_session():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Failed to load session")
        return None
