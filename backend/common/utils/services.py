from django.conf import settings

from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


def generate_access_refresh_tokens(user):
    """
    Generate access and refresh JWT tokens for a user.
    """
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token

    return str(access), str(refresh)


class TokenCookieManager:
    """
    Manage access and refresh JWT cookies.
    """

    @staticmethod
    def set_access_cookie(response: Response, access_token: str):
        """
        Set the access token cookie.
        """
        simple_jwt = settings.SIMPLE_JWT

        response.set_cookie(
            key=simple_jwt["AUTH_COOKIE"],
            value=access_token,
            max_age=int(simple_jwt["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            httponly=simple_jwt["AUTH_COOKIE_HTTP_ONLY"],
            secure=simple_jwt["AUTH_COOKIE_SECURE"],
            samesite=simple_jwt["AUTH_COOKIE_SAMESITE"],
            path=simple_jwt["AUTH_COOKIE_PATH"],
        )

    @staticmethod
    def set_refresh_cookie(response: Response, refresh_token: str):
        """
        Set the refresh token cookie.
        """
        simple_jwt = settings.SIMPLE_JWT

        response.set_cookie(
            key=simple_jwt["AUTH_COOKIE_REFRESH"],
            value=refresh_token,
            max_age=int(simple_jwt["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            httponly=simple_jwt["AUTH_COOKIE_HTTP_ONLY"],
            secure=simple_jwt["AUTH_COOKIE_SECURE"],
            samesite=simple_jwt["AUTH_COOKIE_SAMESITE"],
            path=simple_jwt["AUTH_COOKIE_PATH"],
        )

    @staticmethod
    def delete_tokens_cookies(response: Response):
        """
        Delete access and refresh token cookies.
        """
        simple_jwt = settings.SIMPLE_JWT

        cookie_options = {
            "path": simple_jwt["AUTH_COOKIE_PATH"],
        }

        response.delete_cookie(
            simple_jwt["AUTH_COOKIE"],
            **cookie_options,
        )

        response.delete_cookie(
            simple_jwt["AUTH_COOKIE_REFRESH"],
            **cookie_options,
        )

        return response

    @staticmethod
    def blacklist_refresh_token(refresh_token: str) -> bool:
        """
        Blacklist a refresh token to prevent further use.
        """
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return True
        except TokenError:
            return False

    @staticmethod
    def blacklist_user_refresh_tokens(user) -> int:
        """
        Blacklist all outstanding refresh tokens belonging to a user.
        """
        outstanding_tokens = OutstandingToken.objects.filter(
            user=user,
            blacklistedtoken__isnull=True,
        )

        tokens_to_blacklist = [
            BlacklistedToken(token=token)
            for token in outstanding_tokens
        ]

        BlacklistedToken.objects.bulk_create(
            tokens_to_blacklist,
            ignore_conflicts=True,
        )

        return len(tokens_to_blacklist)
