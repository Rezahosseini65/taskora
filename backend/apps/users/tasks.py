import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_verification_email(self, email: str, verification_code: str):
    """
    Send an email verification code asynchronously.
    """

    subject = "Verify your Taskora email address"

    message = (
        "Hello,\n\n"
        "Thank you for registering with Taskora.\n\n"
        f"Your email verification code is: {verification_code}\n\n"
        "This code expires in 10 minutes.\n\n"
        "If you did not create this account, you can ignore this email."
    )

    try:
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