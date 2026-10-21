from unittest.mock import MagicMock, patch

from app.email_service import send_registration_change_email


@patch("app.email_service.smtplib.SMTP")
def test_registration_change_email_uses_smtp(mock_smtp):
    smtp_connection = MagicMock()
    mock_smtp.return_value.__enter__.return_value = smtp_connection

    with patch.dict(
        "os.environ",
        {
            "MAIL_SERVER": "smtp.example.com",
            "MAIL_PORT": "587",
            "MAIL_USERNAME": "test@example.com",
            "MAIL_PASSWORD": "test-password",
            "MAIL_DEFAULT_SENDER": "notifications@example.com",
        },
    ):
        send_registration_change_email(
            "voter@example.com",
            ["full_name", "address"],
        )

    mock_smtp.assert_called_once_with(
        "smtp.example.com",
        587,
        timeout=10,
    )
    smtp_connection.starttls.assert_called_once()
    smtp_connection.login.assert_called_once_with(
        "test@example.com",
        "test-password",
    )
    smtp_connection.send_message.assert_called_once()

    message = smtp_connection.send_message.call_args.args[0]

    assert message["To"] == "voter@example.com"
    assert message["From"] == "notifications@example.com"
    assert message["Subject"] == "Voter registration details changed"

    body = message.get_content()
    assert "full_name, address" in body
    assert "old address" not in body.lower()
    assert "new address" not in body.lower()


def test_registration_change_email_requires_configuration():
    with patch.dict("os.environ", {}, clear=True):
        try:
            send_registration_change_email(
                "voter@example.com",
                ["address"],
            )
        except RuntimeError as error:
            assert "not configured" in str(error)
        else:
            raise AssertionError(
                "Expected an error when email settings are missing"
            )