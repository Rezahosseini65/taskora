from django.conf import settings

from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


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

        return user, validated_token