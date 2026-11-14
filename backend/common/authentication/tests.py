from datetime import timedelta

from django.middleware.csrf import get_token
from django.test import TestCase, override_settings
from django.utils import timezone
from django.conf import settings

from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User
from common.authentication.jwt import CookieJWTAuthentication


@override_settings(
    SIMPLE_JWT={
        "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
        "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
        "AUTH_COOKIE": "access_token",
        "ALGORITHM": "HS256",
        "SIGNING_KEY": "test-signing-key",
        "VERIFYING_KEY": "",
        "AUDIENCE": None,
        "ISSUER": None,
        "JWK_URL": None,
        "LEEWAY": 0,
        "AUTH_HEADER_TYPES": ("Bearer",),
        "USER_ID_FIELD": "id",
        "USER_ID_CLAIM": "user_id",
        "TOKEN_TYPE_CLAIM": "token_type",
        "JTI_CLAIM": "jti",
        "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
        "CHECK_REVOKE_TOKEN": False,
    }
)
class CookieJWTAuthenticationTests(TestCase):

    def setUp(self):
        self.factory = APIRequestFactory(enforce_csrf_checks=True)
        self.authentication = CookieJWTAuthentication()
        self.user = User.objects.create_user(
            email="auth@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
        )

    def get_access_token(self):
        return str(RefreshToken.for_user(self.user).access_token)

    def authenticate_with_cookie(self, token):
        request = self.factory.get("/")
        request.COOKIES["access_token"] = token
        return self.authentication.authenticate(request)

    def test_inactive_user_cannot_authenticate(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(self.get_access_token())

    def test_active_user_can_authenticate(self):
        result = self.authenticate_with_cookie(self.get_access_token())

        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.user)

    def test_pending_verification_user_cannot_authenticate(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.save(update_fields=["status"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(self.get_access_token())

    def test_suspended_user_cannot_authenticate(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(self.get_access_token())

    def test_deactivated_user_cannot_authenticate(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(self.get_access_token())

    def test_soft_deleted_user_cannot_authenticate(self):
        self.user.deleted_at = timezone.now()
        self.user.save(update_fields=["deleted_at"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(self.get_access_token())

    def test_invalid_token_raises_authentication_failed(self):
        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie("invalid-token")

    def test_expired_token_raises_authentication_failed(self):
        token = RefreshToken.for_user(self.user).access_token
        token.set_exp(lifetime=timedelta(seconds=-1))

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(str(token))

    def test_get_request_does_not_require_csrf(self):
        request = self.factory.get("/")
        self.authentication.enforce_csrf(request)


    def test_post_request_without_csrf_is_rejected(self):
        request = self.factory.post("/")

        with self.assertRaises(PermissionDenied):
            self.authentication.enforce_csrf(request)


    def test_post_request_with_valid_csrf_is_accepted(self):
        request = self.factory.post("/")
        csrf_token = get_token(request)

        request.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_token
        request.META["HTTP_X_CSRFTOKEN"] = csrf_token

        self.authentication.enforce_csrf(request)

    def test_post_with_jwt_cookie_without_csrf_is_rejected(self):
        request = self.factory.post("/")
        request.COOKIES["access_token"] = self.get_access_token()

        with self.assertRaises(PermissionDenied):
            self.authentication.authenticate(request)


    def test_post_with_jwt_cookie_and_valid_csrf_is_authenticated(self):
        request = self.factory.post("/")
        csrf_token = get_token(request)

        request.COOKIES["access_token"] = self.get_access_token()
        request.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_token
        request.META[settings.CSRF_HEADER_NAME] = csrf_token

        result = self.authentication.authenticate(request)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.user)
