import base64
import hashlib
import hmac
import time

from app.core.config import settings


SESSION_COOKIE = "ventas_session"
SESSION_DURATION_SECONDS = 12 * 60 * 60


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
