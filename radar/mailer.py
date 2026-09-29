"""Send the Monday email over plain SMTP (a Gmail app password works, free)."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send(to: list[str], subject: str, html: str, attachment: Path | None = None) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_FROM", f"Ad Radar <{user}>")
    msg["To"] = ", ".join(to)
    msg.set_content("Your weekly competitor creative radar is attached. Open the HTML file in a browser.")
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="text", subtype="html", filename=attachment.name)
    if port == 465:
        with smtplib.SMTP_SSL(host, port) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
