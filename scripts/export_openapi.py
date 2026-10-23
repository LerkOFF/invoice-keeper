"""Выгружает OpenAPI-спецификацию приложения в openapi.yaml.

Запуск из корня репозитория:  .venv/bin/python scripts/export_openapi.py
Проверка актуальности без записи:  .venv/bin/python scripts/export_openapi.py --check
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "openapi.yaml"

# Приложению для сборки схемы нужна база, но данных оно не трогает: уводим её во временную папку
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/openapi.db")
sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402


def render() -> str:
    schema = create_app().openapi()
    # json -> yaml: порядок ключей сохраняется, типы приводятся к простым
    return yaml.safe_dump(json.loads(json.dumps(schema)), allow_unicode=True, sort_keys=False, width=100)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            sys.exit("openapi.yaml устарел: запустите scripts/export_openapi.py")
        print("openapi.yaml актуален")
    else:
        TARGET.write_text(text, encoding="utf-8")
        print(f"записано: {TARGET.relative_to(ROOT)}")
