
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.middleware.csrf import get_token
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.users.models import User, UserSession
from apps.users.services.sessions import create_session_tokens
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

        self.access_token, self.refresh_token, self.session = (
            create_session_tokens(self.user)
        )

    def create_session_for_user(self, user=None):
        user = user or self.user
        return create_session_tokens(user)

    def authenticate_with_cookie(self, token=None):
        request = self.factory.get("/")
        request.COOKIES["access_token"] = token or self.access_token
        return self.authentication.authenticate(request)

    def authenticate_with_header(self, token=None):
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {token or self.access_token}",
        )
        return self.authentication.authenticate(request)

    # ---------------------------------------------------------
    # Account status
    # ---------------------------------------------------------

    def test_active_user_can_authenticate(self):
        result = self.authenticate_with_cookie()

        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.user)

    def test_inactive_user_cannot_authenticate(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    def test_pending_verification_user_cannot_authenticate(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.save(update_fields=["status"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    def test_suspended_user_cannot_authenticate(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    def test_deactivated_user_cannot_authenticate(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    def test_soft_deleted_user_cannot_authenticate(self):
        self.user.deleted_at = timezone.now()
        self.user.save(update_fields=["deleted_at"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    # ---------------------------------------------------------
    # Token validation
    # ---------------------------------------------------------

    def test_invalid_token_raises_authentication_failed(self):
        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie("invalid-token")

    def test_expired_token_raises_authentication_failed(self):
        token = AccessToken(self.access_token)
        token.set_exp(lifetime=timedelta(seconds=-1))

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(str(token))

    def test_token_without_session_id_is_rejected(self):
        token = RefreshToken.for_user(self.user).access_token

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(str(token))

    def test_token_with_unknown_session_id_is_rejected(self):
        token = AccessToken(self.access_token)
        token["sid"] = str(uuid4())

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(str(token))

    # ---------------------------------------------------------
    # Session validation
    # ---------------------------------------------------------

    def test_revoked_session_cannot_authenticate(self):
        self.session.revoked_at = timezone.now()
        self.session.save(update_fields=["revoked_at"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    def test_expired_session_cannot_authenticate(self):
        self.session.expires_at = timezone.now() - timedelta(seconds=1)
        self.session.save(update_fields=["expires_at"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie()

    def test_session_belonging_to_another_user_cannot_authenticate(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
        )

        other_session = UserSession.objects.create(
            user=other_user,
            refresh_token_jti=str(uuid4()),
            expires_at=timezone.now() + timedelta(days=7),
        )

        token = AccessToken(self.access_token)
        token["sid"] = str(other_session.id)

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_cookie(str(token))

    # ---------------------------------------------------------
    # Authorization header
    # ---------------------------------------------------------

    def test_active_session_can_authenticate_with_authorization_header(self):
        result = self.authenticate_with_header()

        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.user)

    def test_revoked_session_is_rejected_with_authorization_header(self):
        self.session.revoked_at = timezone.now()
        self.session.save(update_fields=["revoked_at"])

        with self.assertRaises(AuthenticationFailed):
            self.authenticate_with_header()

    # ---------------------------------------------------------
    # Session activity
    # ---------------------------------------------------------

    def test_authentication_updates_old_session_activity(self):
        old_activity = timezone.now() - timedelta(minutes=10)

        self.session.last_activity_at = old_activity
        self.session.save(update_fields=["last_activity_at"])

        self.authenticate_with_cookie()

        self.session.refresh_from_db()

        self.assertGreater(self.session.last_activity_at, old_activity)

    def test_authentication_does_not_update_recent_session_activity(self):
        recent_activity = timezone.now() - timedelta(minutes=1)

        self.session.last_activity_at = recent_activity
        self.session.save(update_fields=["last_activity_at"])

        self.authenticate_with_cookie()

        self.session.refresh_from_db()

        self.assertEqual(self.session.last_activity_at, recent_activity)

    # ---------------------------------------------------------
    # CSRF
    # ---------------------------------------------------------

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
        request.COOKIES["access_token"] = self.access_token

        with self.assertRaises(PermissionDenied):
            self.authentication.authenticate(request)

    def test_post_with_jwt_cookie_and_valid_csrf_is_authenticated(self):
        request = self.factory.post("/")
        csrf_token = get_token(request)

        request.COOKIES["access_token"] = self.access_token
        request.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_token
        request.META[settings.CSRF_HEADER_NAME] = csrf_token

        result = self.authentication.authenticate(request)

        self.assertIsNotNone(result)
        self.assertEqual(result[0], self.user)
