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
        self.buttons: list[int | None] = []
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._configured

    def send(self, text: str, *, pay_button_for: int | None = None) -> None:
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise TelegramError("Telegram недоступен")
        with self._lock:
            self.messages.append(text)
            self.buttons.append(pay_button_for)
