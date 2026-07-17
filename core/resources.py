"""
Locate bundled asset files both from source and from a frozen exe.
"""
import os
import sys


def resource_path(relative):
    """Absolute path to a bundled resource (e.g. 'assets/logo.png')."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # PyInstaller extraction dir
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)
