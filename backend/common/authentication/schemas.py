from drf_spectacular.extensions import OpenApiAuthenticationExtension

from common.authentication.jwt import CookieJWTAuthentication


class CookieJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = CookieJWTAuthentication
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "access_token",
            "description": "JWT access token stored in an HTTP-only cookie.",
        }