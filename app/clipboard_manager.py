import time


class ClipboardError(RuntimeError):
    pass


class ClipboardManager:
    """Explicit clipboard operations only; no clipboard contents are logged."""
    def copy(self, text, timeout=1.0):
        import pyperclip
        try:
            pyperclip.copy(text)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if pyperclip.paste() == text:
                    return
                time.sleep(0.02)
            raise ClipboardError('Истекло время проверки Clipboard.')
        except ClipboardError:
            raise
        except Exception:
            raise ClipboardError('Clipboard недоступен.') from None

    def read(self):
        import pyperclip
        try:
            return pyperclip.paste()
        except Exception:
            raise ClipboardError('Clipboard недоступен.') from None
