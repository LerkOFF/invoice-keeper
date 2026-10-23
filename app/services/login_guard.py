import math
import threading
import time
from collections import deque
from collections.abc import Callable

# Во сколько раз общий лимит адреса больше лимита одного логина: перебор разных логинов с одного адреса
IP_FACTOR = 4


class LoginGuard:
    """Защита входа от перебора паролей. Хранится в памяти процесса: приложение работает одним процессом.

    Неудачные попытки считаются в скользящем окне по паре «адрес + логин» и отдельно по адресу.
    Блокируется только пара, поэтому чужой перебор не запирает настоящему пользователю вход с его адреса.
    Удачный вход обнуляет счётчик пары.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple, deque[float]] = {}

    @staticmethod
    def _keys(ip: str | None, login: str) -> tuple[tuple, tuple]:
        return ("pair", ip or "", login.strip().lower()), ("ip", ip or "")

    def _recent(self, key: tuple, window: float, now: float) -> deque[float]:
        stamps = self._failures.get(key, deque())
        while stamps and stamps[0] <= now - window:
            stamps.popleft()
        if not stamps:
            self._failures.pop(key, None)
        return stamps

    def retry_after(self, ip: str | None, login: str, max_failures: int, window: float) -> int:
        """Через сколько секунд можно снова пробовать, 0 если вход открыт."""
        now = self._clock()
        wait = 0.0
        with self._lock:
            for key, limit in zip(self._keys(ip, login), (max_failures, max_failures * IP_FACTOR)):
                stamps = self._recent(key, window, now)
                if len(stamps) >= limit:
                    wait = max(wait, stamps[-1] + window - now)  # закрыто на окно с последней неудачи
        return math.ceil(wait)

    def failure(self, ip: str | None, login: str, window: float) -> None:
        now = self._clock()
        with self._lock:
            if len(self._failures) > 10_000:  # перебор с множества адресов: выбрасываем устаревшие ключи
                for key in list(self._failures):
                    self._recent(key, window, now)
            for key in self._keys(ip, login):
                self._failures.setdefault(key, deque()).append(now)

    def success(self, ip: str | None, login: str) -> None:
        with self._lock:
            self._failures.pop(self._keys(ip, login)[0], None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_guard = LoginGuard()
