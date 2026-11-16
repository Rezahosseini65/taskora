from uuid import UUID

from django.conf import settings
from django.utils import timezone

from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.users.models import UserSession
from apps.users.services.sessions import touch_session_activity


class CookieJWTAuthentication(JWTAuthentication):

    def enforce_csrf(self, request):
        check = CSRFCheck(lambda request: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})

        if reason:
            raise PermissionDenied(
                f"CSRF Failed: {reason}"
            )

    def authenticate(self, request):
        header = self.get_header(request)

        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            raw_token = request.COOKIES.get(
                settings.SIMPLE_JWT["AUTH_COOKIE"]
            )

            if raw_token is not None:
                self.enforce_csrf(request)

        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
        except (InvalidToken, TokenError) as exc:
            raise AuthenticationFailed(
                "Invalid or expired access token."
            ) from exc

        user = self.get_user(validated_token)

        if (
            user.deleted_at is not None
            or not user.is_active
            or user.status != user.AccountStatus.ACTIVE
        ):
            raise AuthenticationFailed("Your account is not active.")

        # Validate the session associated with this access token.
        try:
            session_id = UUID(str(validated_token["sid"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationFailed(
                "Invalid or missing session."
            ) from exc

        session_exists = UserSession.objects.filter(
            id=session_id,
            user=user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).exists()

        if not session_exists:
            raise AuthenticationFailed(
                "Session is invalid or expired."
            )

        request.session_id = session_id

        # Update session activity with the configured throttle interval.
        touch_session_activity(session_id, user.pk)

        return user, validated_token
