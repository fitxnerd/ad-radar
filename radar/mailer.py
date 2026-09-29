"""Send the Monday email over plain SMTP (a Gmail app password works, free)."""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def send(to: list[str], subject: str, html: str, attachment: Path | None = None) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    user = os.environ["SMTP_USER"].strip()
    # Gmail shows app passwords as "abcd efgh ijkl mnop"; the spaces are not part of it.
    password = re.sub(r"\s+", "", os.environ["SMTP_PASSWORD"])
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_FROM", f"Ad Radar <{user}>")
    msg["To"] = ", ".join(to)
    msg.set_content("Your weekly competitor creative radar is attached. Open the HTML file in a browser.")
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="text", subtype="html", filename=attachment.name)

    # Try implicit TLS on 465, then STARTTLS on 587: some cloud networks drop one of them.
    ports = [int(os.environ["SMTP_PORT"])] if os.environ.get("SMTP_PORT") else [465, 587]
    errors = []
    for port in ports:
        stage = "connect"
        try:
            ctx = ssl.create_default_context()
            s = smtplib.SMTP_SSL(host, port, timeout=60, context=ctx) if port == 465 else smtplib.SMTP(host, port, timeout=60)
            with s:
                if port != 465:
                    stage = "starttls"
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                stage = "login"
                s.login(user, password)
                stage = "send"
                s.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError as e:
            raise RuntimeError("Gmail rejected the login. Check SMTP_USER is the full Gmail address and "
                               "SMTP_PASSWORD is a 16-character app password (not your normal password).") from e
        except (smtplib.SMTPException, OSError) as e:
            errors.append(f"port {port} at {stage}: {type(e).__name__}: {e}")
    raise RuntimeError("Could not send email. " + " | ".join(errors))
