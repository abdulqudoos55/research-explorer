import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(recipient: str, subject: str, body: str):
    message = EmailMessage()
    message["From"] = os.environ["MAIL_FROM"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(
        os.environ["SMTP_HOST"],
        int(os.environ.get("SMTP_PORT", "587")),
        timeout=20,
    ) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(
            os.environ["SMTP_USER"],
            os.environ["SMTP_PASSWORD"],
        )
        smtp.send_message(message)
