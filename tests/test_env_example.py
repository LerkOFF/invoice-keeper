from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ключи с секретами: в примере они обязаны быть пустыми
SECRET_KEYS = {"ADMIN_TOTP_SECRET", "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "SMTP_PASSWORD", "WEBHOOK_URL", "WEBHOOK_SECRET"}
# Пароли-заглушки для первого запуска: известные значения, которые README просит сменить
PLACEHOLDERS = {"ADMIN_PASSWORD": "change-me", "SEED_USER_PASSWORD": "user-pass-123"}


def _example() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_env_example_has_no_secrets():
    values = _example()
    for key in SECRET_KEYS:
        assert values.get(key) == "", f"{key} в .env.example должен быть пустым"
    for key, placeholder in PLACEHOLDERS.items():
        assert values.get(key) == placeholder, f"{key} в .env.example должен быть заглушкой"


def test_env_is_not_committed():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [line.strip() for line in ignored]
