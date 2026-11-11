"""Django email backend that sends through Brevo's HTTPS API (port 443).

Why: Railway blocks outgoing SMTP ports (25/465/587), so Django's normal SMTP
backend just times out. HTTPS is never blocked. Uses only the standard library,
so nothing new has to be installed.
"""
import json
import logging
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoAPIEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        api_key = getattr(settings, "BREVO_API_KEY", "")
        if not api_key:
            logger.error("BREVO_API_KEY is not set - email not sent")
            if not self.fail_silently:
                raise ValueError("BREVO_API_KEY is not set")
            return 0

        sent = 0
        for message in email_messages:
            try:
                self._send(message, api_key)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Brevo API email error: %s", exc)
                if not self.fail_silently:
                    raise
        return sent

    def _send(self, message, api_key):
        name, address = parseaddr(message.from_email or settings.DEFAULT_FROM_EMAIL)
        payload = {
            "sender": {"email": address, **({"name": name} if name else {})},
            "to": [{"email": r} for r in message.to],
            "subject": message.subject,
        }
        if message.cc:
            payload["cc"] = [{"email": r} for r in message.cc]
        if message.bcc:
            payload["bcc"] = [{"email": r} for r in message.bcc]

        html = None
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                html = content
        if html:
            payload["htmlContent"] = html
            if message.body:
                payload["textContent"] = message.body
        elif message.content_subtype == "html":
            payload["htmlContent"] = message.body
        else:
            payload["textContent"] = message.body

        request = urllib.request.Request(
            getattr(settings, "BREVO_API_URL", BREVO_API_URL),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"Brevo returned {exc.code}: {detail}") from exc