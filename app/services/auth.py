import base64
import hashlib
import hmac
import secrets
import time

from app.core.config import settings

PASSWORD_ITERATIONS = 310_000
SESSION_COOKIE = "ventas_session"
SESSION_DURATION_SECONDS = 12 * 60 * 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived_key).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_key = password_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iteration_count = int(iterations)
        if not PASSWORD_ITERATIONS <= iteration_count <= 1_000_000:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected_key = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
        actual_key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iteration_count
        )
        return hmac.compare_digest(actual_key, expected_key)
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: int) -> str:
    expires_at = int(time.time()) + SESSION_DURATION_SECONDS
    payload = base64.urlsafe_b64encode(
        f"{user_id}:{expires_at}".encode("ascii")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.SESSION_SECRET_KEY.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def read_session_user_id(token: str) -> int | None:
    try:
        payload, provided_signature = token.split(".", 1)
        expected_signature = hmac.new(
            settings.SESSION_SECRET_KEY.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided_signature, expected_signature):
            return None

        padded_payload = payload + "=" * (-len(payload) % 4)
        user_id, expires_at = base64.urlsafe_b64decode(
            padded_payload.encode("ascii")
        ).decode("ascii").split(":", 1)
        if int(expires_at) <= int(time.time()):
            return None
        return int(user_id)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
