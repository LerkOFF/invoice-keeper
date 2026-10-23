import os
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from tests.conftest import logged_in
from tests.helpers import ADMIN, B

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%fake receipt\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
RECEIPTS = Path(os.environ["RECEIPTS_DIR"])


@pytest.fixture(autouse=True)
def clean_receipts_dir():
    """Каждый тест начинает с пустой папки чеков: проверки «файла нет на диске» не зависят от порядка."""
    for path in RECEIPTS.glob("*"):
        path.unlink()
    yield


def make_occurrence(admin, name="Аренда", due="2026-10-25") -> int:
    admin.post(f"{B}/recurring-payments", json={"name": name, "amount": "100.00", "currency": "RUB", "first_due_date": due})
    return admin.get(f"{B}/payment-occurrences").json()[0]["id"]


def link(client, occ, url="https://bank.example/receipt/1", **extra):
    return client.post(f"{B}/payment-occurrences/{occ}/receipts/link", json={"url": url, **extra})


def upload(client, occ, content=PNG, name="check.png", mime="image/png", **data):
    return client.post(
        f"{B}/payment-occurrences/{occ}/receipts/file", files={"file": (name, content, mime)}, data=data
    )


def listing(client, occ):
    return client.get(f"{B}/payment-occurrences/{occ}/receipts").json()


# ---------- ссылки ----------


def test_user_attaches_link_and_everyone_sees_it(admin, user):
    occ = make_occurrence(admin)
    response = link(user, occ, title="  Чек из банка  ")
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "link" and body["title"] == "Чек из банка" and body["url"] == "https://bank.example/receipt/1"
    assert body["created_by"] == "ivan" and body["created_by_type"] == "user" and body["download_url"] is None

    assert [r["id"] for r in listing(admin, occ)] == [body["id"]]
    assert admin.get(f"{B}/payment-occurrences/{occ}").json()["receipts_count"] == 1
    assert admin.get(f"{B}/payment-occurrences").json()[0]["receipts_count"] == 1


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "ftp://host/file", "data:text/html,<b>x</b>", "bank.example/receipt", "https://", "http://a b.example", "", "   ", "https://x.example/" + "a" * 2000],
)
def test_bad_links_are_rejected(admin, url):
    occ = make_occurrence(admin)
    assert link(admin, occ, url=url).status_code == 422
    assert listing(admin, occ) == []


def test_link_rejects_unknown_fields_and_missing_url(admin):
    occ = make_occurrence(admin)
    assert link(admin, occ, kind="file").status_code == 422
    assert admin.post(f"{B}/payment-occurrences/{occ}/receipts/link", json={}).status_code == 422


def test_empty_title_is_stored_as_none(admin):
    occ = make_occurrence(admin)
    assert link(admin, occ, title="   ").json()["title"] is None


def test_receipts_need_login_and_existing_period(admin, anon):
    occ = make_occurrence(admin)
    assert anon.get(f"{B}/payment-occurrences/{occ}/receipts").status_code == 401
    assert anon.post(f"{B}/payment-occurrences/{occ}/receipts/link", json={"url": "https://a.example"}).status_code == 401
    assert admin.get(f"{B}/payment-occurrences/9999/receipts").status_code == 404
    assert link(admin, 9999).status_code == 404
    assert upload(admin, 9999).status_code == 404


def test_cannot_attach_to_deleted_payment_but_can_read_history(admin):
    occ = make_occurrence(admin)
    link(admin, occ)
    admin.delete(f"{B}/recurring-payments/{admin.get(f'{B}/recurring-payments').json()[0]['id']}")

    assert link(admin, occ).status_code == 409
    assert upload(admin, occ).status_code == 409
    assert len(listing(admin, occ)) == 1


def test_per_period_limit(app, admin):
    app.dependency_overrides[get_settings] = lambda: Settings(receipts_per_period=2, receipts_dir=str(RECEIPTS))
    occ = make_occurrence(admin)
    assert link(admin, occ).status_code == 201 and link(admin, occ).status_code == 201
    assert link(admin, occ).status_code == 409
    assert upload(admin, occ).status_code == 409


# ---------- файлы ----------


@pytest.mark.parametrize(
    ("content", "mime", "expected"),
    [(PNG, "image/png", "image/png"), (PDF, "application/pdf", "application/pdf"), (JPEG, "image/jpeg", "image/jpeg"), (WEBP, "image/webp", "image/webp")],
)
def test_allowed_files_are_stored_and_downloadable(admin, content, mime, expected):
    occ = make_occurrence(admin)
    response = upload(admin, occ, content, name="Чек Сбербанк.bin", mime="application/octet-stream", title="Квитанция")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "file" and body["content_type"] == expected  # тип по содержимому, а не по заголовку и имени
    assert body["size_bytes"] == len(content) and body["filename"] == "Чек Сбербанк.bin" and body["title"] == "Квитанция"
    assert body["download_url"] == f"/api/v1/receipts/{body['id']}/file"

    downloaded = admin.get(body["download_url"])
    assert downloaded.status_code == 200 and downloaded.content == content
    assert downloaded.headers["content-type"].startswith(expected)
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "private, no-store"


def test_stored_name_is_random_not_user_controlled(admin):
    occ = make_occurrence(admin)
    upload(admin, occ, PNG, name="../../etc/passwd.png")
    body = listing(admin, occ)[0]
    assert "/" not in body["filename"] and "\\" not in body["filename"]
    stored = list(RECEIPTS.glob("*.png"))
    assert stored and all(len(p.stem) == 32 and p.parent == RECEIPTS for p in stored)
    assert not any("passwd" in p.name for p in RECEIPTS.iterdir())


@pytest.mark.parametrize(
    ("content", "name", "mime"),
    [
        (b"<html><script>alert(1)</script></html>", "evil.png", "image/png"),
        (b"MZ\x90\x00 executable", "tool.pdf", "application/pdf"),
        (b"just text", "note.jpg", "image/jpeg"),
        (b"GIF89a....", "anim.gif", "image/gif"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "x.svg", "image/svg+xml"),
    ],
)
def test_other_formats_are_rejected_even_with_innocent_names(admin, content, name, mime):
    occ = make_occurrence(admin)
    response = upload(admin, occ, content, name=name, mime=mime)
    assert response.status_code == 422 and "PDF, PNG, JPEG и WebP" in response.json()["detail"]
    assert listing(admin, occ) == []


def test_empty_and_oversized_files(app, admin):
    app.dependency_overrides[get_settings] = lambda: Settings(receipt_max_mb=1, receipts_dir=str(RECEIPTS))
    occ = make_occurrence(admin)
    assert upload(admin, occ, b"").status_code == 422
    assert upload(admin, occ, PNG + b"0" * (1024 * 1024)).status_code == 413
    assert upload(admin, occ, PNG + b"0" * 1000).status_code == 201
    assert len(listing(admin, occ)) == 1


def test_upload_without_file_field_is_rejected(admin):
    occ = make_occurrence(admin)
    assert admin.post(f"{B}/payment-occurrences/{occ}/receipts/file", data={"title": "x"}).status_code == 422


def test_download_requires_login_and_existing_file(admin, user, anon):
    occ = make_occurrence(admin)
    file_id = upload(admin, occ).json()["id"]
    link_id = link(admin, occ).json()["id"]

    assert anon.get(f"{B}/receipts/{file_id}/file").status_code == 401
    assert user.get(f"{B}/receipts/{file_id}/file").status_code == 200  # общий список, значит и чеки общие
    assert admin.get(f"{B}/receipts/{link_id}/file").status_code == 404  # у ссылки файла нет
    assert admin.get(f"{B}/receipts/99999/file").status_code == 404


def test_missing_file_on_disk_gives_404_not_500(admin):
    occ = make_occurrence(admin)
    body = upload(admin, occ).json()
    for path in RECEIPTS.glob("*"):
        path.unlink()
    assert admin.get(body["download_url"]).status_code == 404


# ---------- удаление ----------


def test_author_and_admin_can_delete_others_cannot(app, admin, user):
    admin.post(f"{B}/users", json={"login": "olga", "password": "olga-pass-123"})
    olga = logged_in(app, {"login": "olga", "password": "olga-pass-123"})
    occ = make_occurrence(admin)

    mine = link(user, occ).json()["id"]
    theirs = link(admin, occ, url="https://a.example/1").json()["id"]

    assert olga.delete(f"{B}/receipts/{mine}").status_code == 403  # чужое
    assert user.delete(f"{B}/receipts/{theirs}").status_code == 403  # чужое, даже если вложил админ
    assert user.delete(f"{B}/receipts/{mine}").status_code == 204  # своё
    assert admin.delete(f"{B}/receipts/{theirs}").status_code == 204
    assert listing(admin, occ) == []
    assert admin.get(f"{B}/payment-occurrences/{occ}").json()["receipts_count"] == 0
    assert admin.delete(f"{B}/receipts/{mine}").status_code == 404
    olga.__exit__(None, None, None)


def test_delete_removes_file_from_disk(admin):
    occ = make_occurrence(admin)
    body = upload(admin, occ).json()
    assert list(RECEIPTS.glob("*.png"))

    assert admin.delete(f"{B}/receipts/{body['id']}").status_code == 204
    assert not list(RECEIPTS.glob("*.png"))
    assert admin.get(body["download_url"]).status_code == 404


def test_delete_requires_login(admin, anon):
    occ = make_occurrence(admin)
    rid = link(admin, occ).json()["id"]
    assert anon.delete(f"{B}/receipts/{rid}").status_code == 401


# ---------- журнал ----------


def test_receipt_actions_are_audited_without_file_content(admin, user):
    occ = make_occurrence(admin)
    rid = upload(user, occ, PNG, name="check.png", title="Чек").json()["id"]
    link(user, occ, url="https://bank.example/r/2")
    admin.delete(f"{B}/receipts/{rid}")

    entries = admin.get(f"{B}/audit-log", params={"action": "receipt."}).json()
    assert [e["action"] for e in entries] == ["receipt.delete", "receipt.add", "receipt.add"]
    added_file = entries[2]
    assert added_file["actor"] == "ivan" and added_file["details"]["kind"] == "file"
    assert added_file["details"]["filename"] == "check.png" and added_file["details"]["name"] == "Аренда"
    assert entries[0]["actor"] == "boss"
    assert "\x89PNG" not in str(entries)
