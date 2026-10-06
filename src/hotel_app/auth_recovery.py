"""OTP generation, keyed verification, and Brevo delivery helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BREVO_EMAIL_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
BREVO_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


def generate_otp() -> str:
    """Return a cryptographically secure six-digit OTP string."""

    return f"{secrets.randbelow(1_000_000):06d}"


def otp_digest(
    secret_key: str,
    challenge_id: int,
    user_id: int,
    reset_version: int,
    otp: str,
) -> str:
    """Bind an OTP verifier to the challenge, account, and generation."""

    context = (
        f"password-reset-otp:v1:{challenge_id}:{user_id}:"
        f"{reset_version}:{otp}"
    ).encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), context, hashlib.sha256).hexdigest()


def otp_matches(
    stored_digest: str,
    secret_key: str,
    challenge_id: int,
    user_id: int,
    reset_version: int,
    otp: str,
) -> bool:
    candidate = otp_digest(secret_key, challenge_id, user_id, reset_version, otp)
    return hmac.compare_digest(stored_digest, candidate)


def send_password_reset_otp(
    recipient: str,
    otp: str,
    config: Mapping[str, object],
) -> bool:
    """Submit one transactional OTP message to Brevo; never expose details."""

    api_key = str(config.get("BREVO_API_KEY", "") or "").strip()
    sender = str(config.get("MAIL_FROM", "") or "").strip()
    sender_name = str(config.get("MAIL_FROM_NAME", "Hotel Management") or "").strip()
    if (
        str(config.get("EMAIL_PROVIDER", "brevo")).casefold() != "brevo"
        or not api_key
        or not sender
        or not recipient
        or len(otp) != 6
        or not otp.isascii()
        or not otp.isdecimal()
    ):
        logger.warning("Password reset email delivery failed (configuration).")
        return False

    payload = {
        "sender": {"name": sender_name, "email": sender},
        "to": [{"email": recipient}],
        "subject": "Mã xác nhận đặt lại mật khẩu - Hotel Management",
        "textContent": (
            "Hotel Management đã nhận được yêu cầu đặt lại mật khẩu.\n\n"
            f"Mã xác nhận của bạn là: {otp}\n\n"
            "Mã có hiệu lực trong 5 phút.\n\n"
            "Nếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email này."
        ),
    }
    request = Request(
        BREVO_EMAIL_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=BREVO_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except HTTPError as error:
        logger.warning(
            "Password reset email delivery failed (HTTP %s).", error.code
        )
    except (URLError, TimeoutError, OSError, ValueError, TypeError) as error:
        logger.warning(
            "Password reset email delivery failed (%s).", type(error).__name__
        )
    except Exception as error:  # Keep unexpected transport errors non-fatal.
        logger.warning(
            "Password reset email delivery failed (%s).", type(error).__name__
        )
    return False
