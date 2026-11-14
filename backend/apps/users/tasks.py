import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from apps.users.services import otp

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_verification_email(
    self,
    email: str,
    verification_code: str,
    user_id: str,
    generation: int,
):
    """
    Send an email verification code asynchronously.

    Skip the task if its OTP is no longer current.
    """

    try:
        is_current = otp.is_verification_code_current(
            user_id=user_id,
            code=verification_code,
            generation=generation,
        )

        if not is_current:
            logger.info(
                "Skipping outdated verification email for %s. "
                "Generation: %s.",
                email,
                generation,
            )
            return False

        subject = "Verify your Taskora email address"

        message = (
            "Hello,\n\n"
            "Thank you for registering with Taskora.\n\n"
            f"Your email verification code is: {verification_code}\n\n"
            "This code expires in 2 minutes.\n\n"
            "If you did not create this account, you can ignore this email."
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

        logger.info(
            "Verification email sent successfully to %s",
            email,
        )

        return True

    except Exception as exc:
        logger.exception(
            "Failed to send verification email to %s",
            email,
        )

        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_password_changed_email(
    self,
    email: str,
):
    """
    Notify the user that their password has been changed.
    """

    try:
        subject = "Your Taskora password has been changed"

        message = (
            "Hello,\n\n"
            "Your Taskora account password has been changed successfully.\n\n"
            "If you made this change, no further action is required.\n\n"
            "If you did not change your password, "
            "please contact our support team immediately.\n\n"
            "Taskora Security Team"
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )

        logger.info(
            "Password change notification email sent successfully to %s",
            email,
        )

        return True

    except Exception as exc:
        logger.exception(
            "Failed to send password change notification email to %s",
            email,
        )

        raise self.retry(exc=exc)