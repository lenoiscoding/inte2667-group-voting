import os
import smtplib
import ssl
from email.message import EmailMessage


def send_registration_change_email(
    recipient,
    changed_fields
):
    """Send an email notification about changed voter details."""

    mail_server = os.environ.get("MAIL_SERVER")
    mail_port = int(os.environ.get("MAIL_PORT", "587"))
    mail_username = os.environ.get("MAIL_USERNAME")
    mail_password = os.environ.get("MAIL_PASSWORD")
    sender = os.environ.get("MAIL_DEFAULT_SENDER")

    if not all([
        mail_server,
        mail_username,
        mail_password,
        sender,
    ]):
        raise RuntimeError(
            "Email service is not configured."
        )

    fields = ", ".join(changed_fields)

    message = EmailMessage()
    message["Subject"] = "Voter registration details changed"
    message["From"] = sender
    message["To"] = recipient

    message.set_content(
        "Hello,\n\n"
        "A change was made to your voter registration details.\n\n"
        f"Changed information: {fields}\n\n"
        "If you made this change, no action is required. "
        "If you did not make this change, contact the election "
        "system administrator promptly.\n\n"
        "For your security, this notification does not include "
        "your previous or updated personal details.\n"
    )

    tls_context = ssl.create_default_context()

    with smtplib.SMTP(
        mail_server,
        mail_port,
        timeout=10
    ) as smtp:
        smtp.starttls(context=tls_context)
        smtp.login(mail_username, mail_password)
        smtp.send_message(message)
