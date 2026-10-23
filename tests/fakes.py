import threading
import time

from app.services.telegram import TelegramError


class FakeNotifier:
    """Заглушка Telegram: копит сообщения, умеет «падать» и работать медленно."""

    def __init__(self, configured: bool = True, fail: bool = False, delay: float = 0.0) -> None:
        self._configured = configured
        self.fail = fail
        self.delay = delay
        self.messages: list[str] = []
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._configured

    def send(self, text: str) -> None:
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise TelegramError("Telegram недоступен")
        with self._lock:
            self.messages.append(text)
