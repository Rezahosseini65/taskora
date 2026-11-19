from django.conf import settings
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.users.models import User
from apps.users.services.sessions import create_session_tokens


class RefreshAccessTokenViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="refresh@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.url = reverse("users:token-refresh")

        self.access_token, refresh_token, self.session = (
            create_session_tokens(user=self.user)
        )
        self.refresh_token = RefreshToken(refresh_token)

    def set_refresh_cookie(self, refresh_token):
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = str(refresh_token)

    def test_refresh_token_successfully_issues_new_access_token(self):
        self.set_refresh_cookie(self.refresh_token)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(settings.SIMPLE_JWT["AUTH_COOKIE"], response.cookies)

    def test_refresh_token_rotation_issues_new_refresh_token(self):
        old_jti = self.refresh_token["jti"]
        self.set_refresh_cookie(self.refresh_token)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"],
            response.cookies,
        )

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=old_jti
            ).exists()
        )

        self.session.refresh_from_db()

        new_refresh = RefreshToken(
            response.cookies[
                settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
            ].value
        )

        self.assertNotEqual(new_refresh["jti"], old_jti)
        self.assertEqual(
            self.session.refresh_token_jti,
            new_refresh["jti"],
        )

    def test_blacklisted_refresh_token_is_rejected(self):
        self.refresh_token.blacklist()
        self.set_refresh_cookie(self.refresh_token)

        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_missing_refresh_token_is_rejected(self):
        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_invalid_refresh_token_is_rejected(self):
        self.set_refresh_cookie("invalid-refresh-token")

        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class RefreshAccessTokenCSRfTests(APITestCase):

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.refresh_url = reverse("users:token-refresh")
        self.csrf_url = reverse("users:csrf-token")

        self.user = User.objects.create_user(
            email="csrf-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
        )

        _, refresh_token, self.session = create_session_tokens(
            user=self.user,
        )
        self.refresh_token = str(refresh_token)

        self.refresh_cookie_name = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        self.access_cookie_name = settings.SIMPLE_JWT["AUTH_COOKIE"]

    def set_refresh_cookie(self):
        self.client.cookies[self.refresh_cookie_name] = self.refresh_token

    def test_refresh_without_csrf_token_returns_403(self):
        self.set_refresh_cookie()

        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn(self.access_cookie_name, response.cookies)

    def test_refresh_with_invalid_csrf_token_returns_403(self):
        self.set_refresh_cookie()

        response = self.client.post(
            self.refresh_url,
            HTTP_X_CSRFTOKEN="invalid-csrf-token",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn(self.access_cookie_name, response.cookies)

    def test_refresh_with_valid_csrf_token_succeeds(self):
        self.set_refresh_cookie()

        csrf_response = self.client.get(self.csrf_url)
        self.assertEqual(csrf_response.status_code, 200)

        csrf_token = self.client.cookies[settings.CSRF_COOKIE_NAME].value

        response = self.client.post(
            self.refresh_url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.access_cookie_name, response.cookies)

    def test_refresh_without_refresh_cookie_returns_401_without_csrf(self):
        response = self.client.post(self.refresh_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn(self.access_cookie_name, response.cookies)
        self.assertIn(self.refresh_cookie_name, response.cookies)

        self.assertEqual(
            response.cookies[self.access_cookie_name]["max-age"],
            0,
        )
        self.assertEqual(
            response.cookies[self.refresh_cookie_name]["max-age"],
            0,
        )


class RefreshAccountStatusTests(APITestCase):

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

        self.refresh_url = reverse("users:token-refresh")
        self.csrf_url = reverse("users:csrf-token")

        self.refresh_cookie_name = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        self.access_cookie_name = settings.SIMPLE_JWT["AUTH_COOKIE"]

    def create_refresh_token(self, user):
        _, refresh_token, session = create_session_tokens(user=user)
        self.client.cookies[self.refresh_cookie_name] = str(refresh_token)
        return session

    def prepare_csrf(self):
        response = self.client.get(self.csrf_url)

        self.assertEqual(response.status_code, 200)

        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def refresh(self, csrf_token):
        return self.client.post(
            self.refresh_url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

    def assert_tokens_cleared(self, response):
        self.assertIn(self.access_cookie_name, response.cookies)
        self.assertIn(self.refresh_cookie_name, response.cookies)

        self.assertEqual(
            response.cookies[self.access_cookie_name]["max-age"],
            0,
        )
        self.assertEqual(
            response.cookies[self.refresh_cookie_name]["max-age"],
            0,
        )

    def assert_refresh_rejected(self, user):
        self.create_refresh_token(user)
        csrf_token = self.prepare_csrf()

        response = self.refresh(csrf_token)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assert_tokens_cleared(response)

    def assert_refresh_succeeded(self, user):
        session = self.create_refresh_token(user)
        csrf_token = self.prepare_csrf()

        response = self.refresh(csrf_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.access_cookie_name, response.cookies)
        self.assertNotEqual(
            response.cookies[self.access_cookie_name].value,
            "",
        )

        session.refresh_from_db()

        self.assertNotEqual(
            session.refresh_token_jti,
            "",
        )

    def test_active_user_can_refresh(self):
        user = User.objects.create_user(
            email="active-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
        )

        self.assert_refresh_succeeded(user)

    def test_pending_verification_user_cannot_refresh(self):
        user = User.objects.create_user(
            email="pending-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.PENDING_VERIFICATION,
        )

        response = self.client.post(
            self.refresh_url,
            {},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_suspended_user_cannot_refresh(self):
        user = User.objects.create_user(
            email="suspended-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.SUSPENDED,
        )

        self.assert_refresh_rejected(user)

    def test_deactivated_user_cannot_refresh(self):
        user = User.objects.create_user(
            email="deactivated-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.DEACTIVATED,
        )

        self.assert_refresh_rejected(user)

    def test_soft_deleted_user_cannot_refresh(self):
        user = User.objects.create_user(
            email="deleted-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
        )

        self.create_refresh_token(user)
        user.soft_delete()

        csrf_token = self.prepare_csrf()
        response = self.refresh(csrf_token)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assert_tokens_cleared(response)

    def test_user_with_is_active_false_cannot_refresh(self):
        user = User.objects.create_user(
            email="inactive-refresh@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
            is_active=False,
        )

        self.assert_refresh_rejected(user)
