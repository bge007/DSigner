"""
Application-wide logging configuration
"""
import logging
import os
import sys


def _log_file():
    if getattr(sys, "frozen", False):
        # packaged exe: __file__ lives in a temp extraction dir,
        # so log next to the session file instead
        base = os.path.join(
            os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "DSigner")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "error.log")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "error.log")


LOG_FILE = _log_file()


def setup_logging():
    """Configure root logger to write errors (with traceback) to error.log"""
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    def log_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("unhandled").critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = log_unhandled_exception
