"""Password reset token and email helpers."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Mapping
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, URLSafeTimedSerializer


RESET_TOKEN_SALT = "hotel-auth-password-reset-v1"
RESET_TOKEN_MAX_AGE = 900
SMTP_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=RESET_TOKEN_SALT)


def generate_password_reset_token(user, secret_key: str) -> str:
    """Sign a token containing only account identity and reset version."""

    return _serializer(secret_key).dumps(
        {
            "user_id": user.id,
            "reset_version": user.password_reset_version,
            "purpose": "password-reset",
        }
    )


def validate_password_reset_token(
    token: str, secret_key: str, user_loader
):
    """Return the matching User for a current token, otherwise None."""

    try:
        payload = _serializer(secret_key).loads(
            token, max_age=RESET_TOKEN_MAX_AGE
        )
    except (BadSignature, TypeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    reset_version = payload.get("reset_version")
    if (
        payload.get("purpose") != "password-reset"
        or not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or not isinstance(reset_version, int)
        or isinstance(reset_version, bool)
    ):
        return None

    try:
        user = user_loader(user_id)
    except (TypeError, ValueError):
        return None
    if user is None or user.password_reset_version != reset_version:
        return None
    return user


def _reset_url(token: str, base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
    ):
        raise ValueError("APP_BASE_URL must be an absolute HTTP(S) URL")
    base_path = parsed.path.rstrip("/")
    trusted_base = f"{parsed.scheme}://{parsed.netloc}{base_path}"
    return f"{trusted_base}/reset-password/{quote(token, safe='')}"


def send_password_reset_email(
    recipient: str,
    token: str,
    config: Mapping[str, object],
) -> bool:
    """Send a plain-text reset message; return False on safe delivery failure."""

    try:
        username = str(config.get("MAIL_USERNAME", "") or "")
        password = str(config.get("MAIL_PASSWORD", "") or "")
        sender = str(config.get("MAIL_FROM", "") or username)
        if not username or not password or not sender:
            raise ValueError("Mail credentials are not configured")

        reset_url = _reset_url(
            token,
            str(config.get("APP_BASE_URL", "http://127.0.0.1:5000")),
        )
        message = EmailMessage()
        message["Subject"] = "Đặt lại mật khẩu - Hotel Management"
        message["From"] = sender
        message["To"] = recipient
        message.set_content(
            "Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản của bạn.\n\n"
            f"Mở liên kết sau để đặt lại mật khẩu: {reset_url}\n\n"
            "Liên kết sẽ hết hạn sau 15 phút. Nếu bạn không yêu cầu đặt lại "
            "mật khẩu, hãy bỏ qua email này."
        )

        server_name = str(config.get("MAIL_SERVER", "smtp.gmail.com"))
        port = int(config.get("MAIL_PORT", 587))
        use_tls = bool(config.get("MAIL_USE_TLS", True))
        with smtplib.SMTP(
            server_name, port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(username, password)
            smtp.send_message(message)
        return True
    except Exception as error:  # SMTP, TLS, network, configuration, or message error.
        logger.warning(
            "Password reset email delivery failed (%s).",
            type(error).__name__,
        )
        return False
