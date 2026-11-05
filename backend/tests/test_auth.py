import jwt

from app.config import get_settings
from app.security.auth import hash_password, verify_password
from tests.conftest import register_and_login


def test_password_hash_roundtrip():
    h = hash_password("Secret123")
    assert h.startswith("$argon2")
    assert verify_password("Secret123", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)


def test_register_login_me(client):
    r = client.post("/api/auth/register",
                    json={"email": "A@Example.com", "password": "Passw0rdA", "full_name": "Alice"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "a@example.com" and body["role"] == "employee"
    assert "password" not in body and "hashed_password" not in body
    headers = register_and_login(client, "a@example.com")
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["full_name"] == "Alice"


def test_duplicate_email_rejected(client):
    p = {"email": "dup@example.com", "password": "Passw0rdA", "full_name": "D"}
    assert client.post("/api/auth/register", json=p).status_code == 201
    assert client.post("/api/auth/register", json=p).status_code == 409


def test_weak_password_rejected(client):
    r = client.post("/api/auth/register",
                    json={"email": "w@example.com", "password": "allletters", "full_name": "W"})
    assert r.status_code == 422


def test_wrong_password_and_unknown_user(client):
    client.post("/api/auth/register",
                json={"email": "x@example.com", "password": "Passw0rdA", "full_name": "X"})
    assert client.post("/api/auth/login",
                       json={"email": "x@example.com", "password": "nope12345"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": "ghost@example.com", "password": "Passw0rdA"}).status_code == 401


def test_protected_endpoint_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_register_cannot_choose_admin_role(client):
    r = client.post("/api/auth/register", json={"email": "sneaky@example.com", "password": "Passw0rdA",
                                                "full_name": "S", "role": "admin"})
    assert r.status_code == 201 and r.json()["role"] == "employee"


def test_token_signed_with_other_key_rejected(client):
    bad = jwt.encode({"sub": "1", "role": "admin"}, "some-other-secret-key-0123456789abcdef", algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    assert get_settings().secret_key != "some-other-secret-key-0123456789abcdef"
