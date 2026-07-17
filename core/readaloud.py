"""
Text-to-speech read-aloud using the built-in Windows speech engine
(System.Speech via PowerShell) — no extra Python dependencies.
"""
import logging
import subprocess

logger = logging.getLogger(__name__)

_PS_SPEAK = (
    "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.Rate = 0; "
    "$text = [Console]::In.ReadToEnd(); "
    "$s.Speak($text)")


class ReadAloud:
    """Speaks text asynchronously; only one utterance at a time."""

    def __init__(self):
        self._proc = None

    def is_speaking(self):
        return self._proc is not None and self._proc.poll() is None

    def speak(self, text):
        """Start speaking `text`; returns False if there is nothing to say."""
        self.stop()
        text = (text or "").strip()
        if not text:
            return False
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-Command", _PS_SPEAK],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
            self._proc.stdin.write(text.encode("utf-8"))
            self._proc.stdin.close()
            return True
        except Exception:
            logger.exception("Failed to start read-aloud")
            self._proc = None
            return False

    def stop(self):
        if self.is_speaking():
            try:
                self._proc.kill()
            except Exception:
                logger.debug("Could not kill speech process", exc_info=True)
        self._proc = None
