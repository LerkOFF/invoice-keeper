import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.main import WEB_DIR
from tests.helpers import B

STATIC = Path(WEB_DIR) / "static"


def test_panel_page_is_served_with_security_headers(anon):
    response = anon.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Invoice Keeper" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "'unsafe-inline'" not in csp


def test_static_assets_are_served(anon):
    css = anon.get("/static/app.css")
    js = anon.get("/static/app.js")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert anon.get("/static/nope.js").status_code == 404


def test_swagger_is_not_restricted_by_panel_csp(anon):
    response = anon.get(f"{B}/docs")
    assert response.status_code == 200 and "content-security-policy" not in response.headers


def test_panel_shell_does_not_leak_data_without_login(anon):
    # страница входа открыта всем, но данных в ней нет: всё приходит из API, которое требует сессию
    page = anon.get("/").text
    assert "Аренда" not in page
    assert anon.get(f"{B}/payment-occurrences").status_code == 401
    assert anon.get(f"{B}/users").status_code == 401


def test_html_is_csp_compatible():
    html = (Path(WEB_DIR) / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "инлайновый скрипт нарушит CSP"
    assert "style=" not in html and "<style" not in html
    assert not re.search(r"https?://(?!www\.w3\.org)", html.replace("data:image/svg+xml", ""))


def test_js_never_writes_untrusted_markup():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for dangerous in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert dangerous not in js, f"{dangerous} открывает дорогу XSS через названия платежей"
    assert "style=" not in js and ".style." not in js, "инлайновые стили нарушат CSP"


@pytest.mark.skipif(shutil.which("node") is None, reason="node не установлен")
def test_js_has_valid_syntax():
    result = subprocess.run(["node", "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
