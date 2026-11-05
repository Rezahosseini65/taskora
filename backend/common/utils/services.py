from django.conf import settings

from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken


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
