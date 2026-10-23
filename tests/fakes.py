import threading
import time

from app.services.notify import Reminder
from app.services.telegram import TelegramError


class FakeNotifier:
    """Заглушка канала напоминаний: копит сообщения, умеет «падать» и работать медленно."""

    def __init__(self, configured: bool = True, fail: bool = False, delay: float = 0.0, name: str = "telegram") -> None:
        self.name = name
        self._configured = configured
        self.fail = fail
        self.delay = delay
        self.messages: list[str] = []
        self.buttons: list[int | None] = []
        self.reminders: list[Reminder] = []
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._configured

    def send(self, reminder: Reminder) -> None:
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise TelegramError(f"{self.name} недоступен")
        with self._lock:
            self.messages.append(reminder.text)
            self.buttons.append(reminder.occurrence_id)
            self.reminders.append(reminder)
