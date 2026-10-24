"""Одноразовые коды для двухфакторного входа администратора (TOTP, RFC 6238).

Совместимо с Google Authenticator, Яндекс Ключом, Aegis, 1Password и другими: 6 цифр, шаг 30 секунд, SHA-1.
Новый секрет и ссылка для приложения: `python -m app.services.totp` (в Docker: `docker compose exec app ...`).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import sys
import threading
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP = 30
# Принимаем код соседнего шага: часы телефона и сервера расходятся на десятки секунд
WINDOW = 1


class InvalidSecretError(ValueError):
    """Секрет не в Base32 или слишком короткий."""


def normalize_secret(secret: str) -> str:
    """Секрет без пробелов и дефисов в верхнем регистре. Пустая строка: 2FA выключена."""
    value = secret.replace(" ", "").replace("-", "").upper().rstrip("=")
    if value:
        _key(value)
    return value


def _key(secret: str) -> bytes:
    try:
        key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    except (ValueError, TypeError) as exc:
        raise InvalidSecretError("ADMIN_TOTP_SECRET должен быть в Base32 (буквы A-Z и цифры 2-7)") from exc
    if len(key) < 10:
        raise InvalidSecretError("ADMIN_TOTP_SECRET слишком короткий: нужно не меньше 16 символов Base32")
    return key


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def matching_counter(secret: str, code: str, now: float | None = None) -> int | None:
    """Шаг, которому соответствует код, или None. Сравнение за постоянное время."""
    code = code.replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int((time.time() if now is None else now) // STEP)
    found = None
    for counter in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, counter), code):
            found = counter
    return found


class ReplayGuard:
    """Каждый код принимается один раз: подсмотренный код нельзя ввести повторно, пока он ещё действует.

    Хранится в памяти процесса, как и защита входа: приложение работает одним процессом.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: int | None = None

    def verify(self, secret: str, code: str, now: float | None = None) -> bool:
        counter = matching_counter(secret, code, now)
        if counter is None:
            return False
        with self._lock:
            if self._last is not None and counter <= self._last:
                return False
            self._last = counter
        return True

    def reset(self) -> None:
        with self._lock:
            self._last = None


admin_otp = ReplayGuard()


def provisioning_uri(secret: str, account: str, issuer: str = "Invoice Keeper") -> str:
    """Ссылка otpauth:// для приложения-аутентификатора (её же можно превратить в QR-код)."""
    label = quote(f"{issuer}:{account}")
    query = urlencode({"secret": secret, "issuer": issuer, "digits": DIGITS, "period": STEP})
    return f"otpauth://totp/{label}?{query}"


def main(argv: list[str]) -> None:
    account = argv[0] if argv else "admin"
    secret = generate_secret()
    print("Добавьте в .env строку и перезапустите приложение:")
    print(f"ADMIN_TOTP_SECRET={secret}")
    print()
    print("В приложении-аутентификаторе: «Ввести ключ вручную», ключ выше, тип «по времени».")
    print("Или откройте на телефоне ссылку (или сделайте из неё QR-код):")
    print(provisioning_uri(secret, account))


if __name__ == "__main__":
    main(sys.argv[1:])
