from apps.users.tasks import send_password_reset_email


def handle_password_reset_requested(user_id, payload):
    email = payload.get("email")
    reset_token = payload.get("reset_token")

    if not email or not reset_token:
        raise ValueError(
            "Password reset event requires email and reset_token."
        )

    send_password_reset_email.delay(
        email=email,
        reset_token=reset_token,
    )