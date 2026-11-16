from uuid import uuid4, UUID
from unittest.mock import ANY, patch
from datetime import timedelta

from django.urls import reverse
from django.conf import settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.users.models import User, UserSession
from apps.outbox.models import OutboxEvent
from apps.users.services.verification import verify_verification_token
from apps.users.services import block
from apps.users.services.sessions import create_session_tokens
from apps.users.services.password_reset import (
    generate_password_reset_token,
    get_password_reset_user_id,
    _get_password_reset_key,
    _get_redis_client,
)


class UserRegisterViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:user-register")

        self.valid_data = {
            "email": "newuser@example.com",
            "password": "StrongPassword123",
            "confirm_password": "StrongPassword123",
        }

    def test_successful_registration(self):
        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["detail"],
            "Registration successful. Please verify your email address.",
        )
        self.assertIn("verification_token", response.data)

        user = User.objects.get(email="newuser@example.com")

        self.assertTrue(user.check_password("StrongPassword123"))
        self.assertEqual(user.status, User.AccountStatus.PENDING_VERIFICATION)

        verification_token = response.data["verification_token"]

        self.assertIsInstance(verification_token, str)
        self.assertEqual(verify_verification_token(verification_token), user.id)

        event = OutboxEvent.objects.get(
            event_type="users.email_verification_requested",
            aggregate_type="user",
            aggregate_id=user.id,
        )

        self.assertEqual(
            event.payload,
            {"email": user.email, "generation": 1},
        )
        self.assertEqual(
            block._get_redis_client().get(block._get_generation_key(user.id)),
            b"1",
        )
        self.assertEqual(event.status, OutboxEvent.Status.PENDING)

        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_registration_with_duplicate_email(self):
        User.objects.create_user(
            email="newuser@example.com",
            password="AnotherStrong123",
        )

        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_registration_with_invalid_email(self):
        data = {**self.valid_data, "email": "invalid-email"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_registration_with_password_mismatch(self):
        data = {
            **self.valid_data,
            "confirm_password": "DifferentPassword123",
        }

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_registration_with_weak_password(self):
        data = {
            **self.valid_data,
            "password": "weakpassword",
            "confirm_password": "weakpassword",
        }

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    @patch(
        "apps.users.views.create_outbox_event",
        side_effect=RuntimeError("Outbox event creation failed"),
    )
    def test_user_creation_is_rolled_back_if_outbox_event_creation_fails(
        self,
        mocked_create_outbox_event,
    ):
        with self.assertRaises(RuntimeError):
            self.client.post(self.url, self.valid_data, format="json")

        self.assertFalse(
            User.objects.filter(email="newuser@example.com").exists()
        )
        self.assertEqual(OutboxEvent.objects.count(), 0)
        mocked_create_outbox_event.assert_called_once()


class EmailVerificationViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:email-verify")

        self.user = User.objects.create_user(
            email="newuser@example.com",
            password="StrongPassword123",
        )

        self.valid_data = {
            "verification_token": "valid-verification-token",
            "verification_code": "123456",
        }

    @patch(
        "apps.users.views.create_session_tokens",
        return_value=("access-token", "refresh-token", None),
    )
    @patch(
        "apps.users.views.otp.verify_and_consume_verification_code",
        return_value=True,
    )
    @patch("apps.users.views.verify_verification_token")
    def test_successful_email_verification(
        self,
        mocked_verify_token,
        mocked_verify_code,
        mocked_create_session,
    ):
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {"detail": "Email verified successfully."},
        )

        self.user.refresh_from_db()

        self.assertEqual(self.user.status, User.AccountStatus.ACTIVE)
        self.assertIsNotNone(self.user.email_verified_at)

        mocked_verify_token.assert_called_once_with(
            self.valid_data["verification_token"]
        )
        mocked_verify_code.assert_called_once_with(
            user_id=self.user.id,
            code="123456",
        )
        mocked_create_session.assert_called_once_with(
            user=self.user,
            request=ANY,
        )

        access_cookie = settings.SIMPLE_JWT["AUTH_COOKIE"]
        refresh_cookie = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]

        self.assertIn(access_cookie, response.cookies)
        self.assertIn(refresh_cookie, response.cookies)

        self.assertEqual(response.cookies[access_cookie].value, "access-token")
        self.assertEqual(response.cookies[refresh_cookie].value, "refresh-token")

        self.assertTrue(response.cookies[access_cookie]["httponly"])
        self.assertTrue(response.cookies[refresh_cookie]["httponly"])

    @patch("apps.users.views.verify_verification_token", return_value=None)
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_invalid_verification_token(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_token", response.data)
        mocked_verify_code.assert_not_called()

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.status,
            User.AccountStatus.PENDING_VERIFICATION,
        )
        self.assertNotIn(
            settings.SIMPLE_JWT["AUTH_COOKIE"],
            response.cookies,
        )

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_verification_with_nonexistent_user(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        mocked_verify_token.return_value = uuid4()

        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_token", response.data)
        mocked_verify_code.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_verification_with_deleted_user(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        self.user.soft_delete()
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_token", response.data)
        mocked_verify_code.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_verification_for_already_active_user(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        self.user.status = User.AccountStatus.ACTIVE
        self.user.save(update_fields=["status"])
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)
        mocked_verify_code.assert_not_called()

    @patch(
        "apps.users.views.otp.verify_and_consume_verification_code",
        return_value=0,
    )
    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_session_tokens")
    def test_verification_with_invalid_or_expired_code(
        self,
        mocked_create_session,
        mocked_verify_token,
        mocked_verify_code,
    ):
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_code", response.data)

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.status,
            User.AccountStatus.PENDING_VERIFICATION,
        )
        self.assertIsNone(self.user.email_verified_at)

        mocked_create_session.assert_not_called()
        self.assertNotIn(
            settings.SIMPLE_JWT["AUTH_COOKIE"],
            response.cookies,
        )

    @patch(
        "apps.users.views.otp.verify_and_consume_verification_code",
        return_value=-1,
    )
    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_session_tokens")
    def test_verification_when_account_is_temporarily_locked(
        self,
        mocked_create_session,
        mocked_verify_token,
        mocked_verify_code,
    ):
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(self.url, self.valid_data, format="json")

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.status,
            User.AccountStatus.PENDING_VERIFICATION,
        )

        mocked_create_session.assert_not_called()
        self.assertNotIn(
            settings.SIMPLE_JWT["AUTH_COOKIE"],
            response.cookies,
        )

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_verification_with_invalid_code_format(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        data = {**self.valid_data, "verification_code": "12AB56"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_code", response.data)
        mocked_verify_token.assert_not_called()
        mocked_verify_code.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_verification_with_short_code(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        data = {**self.valid_data, "verification_code": "12345"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mocked_verify_token.assert_not_called()
        mocked_verify_code.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.otp.verify_and_consume_verification_code")
    def test_verification_without_token(
        self,
        mocked_verify_code,
        mocked_verify_token,
    ):
        data = {"verification_code": "123456"}

        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_token", response.data)
        mocked_verify_token.assert_not_called()
        mocked_verify_code.assert_not_called()


class UserLoginViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:user-login")
        self.password = "StrongPassword123"

        self.user = User.objects.create_user(
            email="user@example.com",
            password=self.password,
            status=User.AccountStatus.ACTIVE,
        )

    def _login(self, email="user@example.com", password=None):
        return self.client.post(
            self.url,
            {
                "email": email,
                "password": password or self.password,
            },
            format="json",
        )

    def test_successful_login(self):
        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Login successful")

        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        self.assertTrue(response.cookies["access_token"]["httponly"])
        self.assertTrue(response.cookies["refresh_token"]["httponly"])

        # Login must create a persistent session.
        session = UserSession.objects.get(user=self.user)

        access_token = AccessToken(
            response.cookies["access_token"].value
        )
        refresh_token = RefreshToken(
            response.cookies["refresh_token"].value
        )

        self.assertEqual(access_token["sid"], str(session.id))
        self.assertEqual(refresh_token["sid"], str(session.id))
        self.assertEqual(
            session.refresh_token_jti,
            refresh_token["jti"],
        )

    def test_login_with_incorrect_password(self):
        response = self._login(password="WrongPassword123")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)
        self.assertEqual(UserSession.objects.count(), 0)

    def test_login_with_pending_verification_account(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.save(update_fields=["status"])

        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(str(response.data["code"][0]), "email_not_verified")
        self.assertTrue(response.data["verification_required"][0])

        verification_token = response.data["verification_token"][0]
        self.assertIsNotNone(verification_token)

        token_user_id = verify_verification_token(str(verification_token))
        self.assertEqual(token_user_id, self.user.id)

        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_login_with_suspended_account(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_login_with_deactivated_account(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_login_with_inactive_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self._login()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_login_with_nonexistent_email(self):
        response = self._login(email="unknown@example.com")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)


class CSRFTokenViewTests(APITestCase):

    def test_csrf_endpoint_returns_success_and_sets_cookie(self):
        response = self.client.get(reverse("users:csrf-token"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("csrftoken", response.cookies)
        self.assertTrue(response.cookies["csrftoken"].value)


class UserLogoutViewTests(APITestCase):

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.url = reverse("users:user-logout")

        self.user = User.objects.create_user(
            email="logout@example.com",
            password="StrongPassword123",
            status=User.AccountStatus.ACTIVE,
        )

        access_token, refresh_token, self.session = create_session_tokens(
            user=self.user,
        )

        self.access_token = access_token
        self.refresh_token = RefreshToken(refresh_token)

    def authenticate_client(self):
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

    def set_refresh_cookie(self, token):
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = str(token)

    def get_csrf_token(self):
        response = self.client.get(reverse("users:csrf-token"))
        return response.cookies[settings.CSRF_COOKIE_NAME].value

    def test_successful_logout_revokes_session_and_blacklists_refresh_token(self):
        self.authenticate_client()
        self.set_refresh_cookie(self.refresh_token)
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.revoked_at)

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=self.refresh_token["jti"]
            ).exists()
        )

        self.assertEqual(
            response.cookies[settings.SIMPLE_JWT["AUTH_COOKIE"]].value,
            "",
        )
        self.assertEqual(
            response.cookies[
                settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
            ].value,
            "",
        )

    def test_logout_without_refresh_token_still_revokes_session(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.revoked_at)

        self.assertEqual(
            response.cookies[settings.SIMPLE_JWT["AUTH_COOKIE"]].value,
            "",
        )
        self.assertEqual(
            response.cookies[
                settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
            ].value,
            "",
        )

    def test_logout_with_invalid_refresh_cookie_still_succeeds(self):
        self.authenticate_client()
        self.set_refresh_cookie("invalid-refresh-token")
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.revoked_at)

        self.assertEqual(
            response.cookies[
                settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
            ].value,
            "",
        )

    def test_access_token_is_rejected_immediately_after_logout(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        logout_response = self.client.post(
            self.url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(
            logout_response.status_code,
            status.HTTP_200_OK,
        )

        # Reuse the original access token after logout.
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

        response = self.client.post(
            self.url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_logout_without_access_token_is_rejected(self):
        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_logout_without_csrf_token_is_rejected(self):
        self.authenticate_client()

        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )


class ResendVerificationEmailViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:email-resend")

        self.user = User.objects.create_user(
            email="newuser@example.com",
            password="StrongPassword123",
        )

        self.valid_data = {
            "verification_token": "valid-verification-token",
        }

        self.generation = 2

        self.generic_response_data = {
            "detail": (
                "If the account is eligible, "
                "a verification email will be sent."
            )
        }

        self.throttle_patcher = patch(
            "apps.users.throttles.EmailVerificationResendThrottle.allow_request",
            return_value=True,
        )
        self.throttle_patcher.start()
        self.addCleanup(self.throttle_patcher.stop)

    def assert_generic_response(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.generic_response_data)

    @patch("apps.users.views.create_outbox_event")
    @patch("apps.users.views.block.start_resend_cooldown")
    @patch("apps.users.views.verify_verification_token")
    def test_successful_resend_request(
        self,
        mocked_verify_token,
        mocked_start_cooldown,
        mocked_create_event,
    ):
        request_id = "test-resend-request-123"

        mocked_verify_token.return_value = self.user.id
        mocked_start_cooldown.return_value = request_id

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)

        mocked_verify_token.assert_called_once_with(
            self.valid_data["verification_token"]
        )
        mocked_start_cooldown.assert_called_once_with(self.user.id)

        mocked_create_event.assert_called_once_with(
            event_type="users.email_verification_requested",
            aggregate_type="user",
            aggregate_id=self.user.id,
            payload={
                "email": self.user.email,
                "request_id": request_id,
            },
        )

    @patch("apps.users.views.verify_verification_token", return_value=None)
    @patch("apps.users.views.create_outbox_event")
    @patch("apps.users.views.block.start_resend_cooldown")
    def test_resend_with_invalid_verification_token(
        self,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_verify_token,
    ):
        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)
        mocked_start_cooldown.assert_not_called()
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_outbox_event")
    @patch("apps.users.views.block.start_resend_cooldown")
    def test_resend_with_nonexistent_user(
        self,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_verify_token,
    ):
        mocked_verify_token.return_value = uuid4()

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)
        mocked_start_cooldown.assert_not_called()
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_outbox_event")
    @patch("apps.users.views.block.start_resend_cooldown")
    def test_resend_for_deleted_user(
        self,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_verify_token,
    ):
        self.user.soft_delete()
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)
        mocked_start_cooldown.assert_not_called()
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_outbox_event")
    @patch("apps.users.views.block.start_resend_cooldown")
    def test_resend_for_already_active_user(
        self,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_verify_token,
    ):
        self.user.status = User.AccountStatus.ACTIVE
        self.user.save(update_fields=["status"])
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)
        mocked_start_cooldown.assert_not_called()
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_outbox_event")
    @patch(
        "apps.users.views.block.start_resend_cooldown",
        return_value=None,
    )
    def test_resend_during_cooldown(
        self,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_verify_token,
    ):
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)
        mocked_start_cooldown.assert_called_once_with(self.user.id)
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.create_outbox_event")
    @patch(
        "apps.users.views.block.start_resend_cooldown",
        return_value=None,
    )
    def test_resend_for_temporarily_locked_account(
        self,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_verify_token,
    ):
        mocked_verify_token.return_value = self.user.id

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assert_generic_response(response)
        mocked_start_cooldown.assert_called_once_with(self.user.id)
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.block.clear_resend_cooldown")
    @patch(
        "apps.users.views.create_outbox_event",
        side_effect=RuntimeError("Outbox event creation failed"),
    )
    @patch("apps.users.views.block.start_resend_cooldown")
    @patch("apps.users.views.verify_verification_token")
    def test_cooldown_is_cleared_if_outbox_creation_fails(
        self,
        mocked_verify_token,
        mocked_start_cooldown,
        mocked_create_event,
        mocked_clear_cooldown,
    ):
        request_id = "test-resend-request-123"

        mocked_verify_token.return_value = self.user.id
        mocked_start_cooldown.return_value = request_id

        with self.assertRaises(RuntimeError):
            self.client.post(self.url, self.valid_data, format="json")

        mocked_start_cooldown.assert_called_once_with(self.user.id)
        mocked_create_event.assert_called_once()
        mocked_clear_cooldown.assert_called_once_with(
            self.user.id,
            request_id,
        )

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.block.start_resend_cooldown")
    @patch("apps.users.views.create_outbox_event")
    def test_resend_without_verification_token(
        self,
        mocked_create_event,
        mocked_start_cooldown,
        mocked_verify_token,
    ):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verification_token", response.data)

        mocked_verify_token.assert_not_called()
        mocked_start_cooldown.assert_not_called()
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.block.start_resend_cooldown")
    @patch("apps.users.views.create_outbox_event")
    def test_resend_with_missing_token_does_not_create_event(
        self,
        mocked_create_event,
        mocked_start_cooldown,
        mocked_verify_token,
    ):
        response = self.client.post(
            self.url,
            {"unexpected_field": "value"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mocked_verify_token.assert_not_called()
        mocked_start_cooldown.assert_not_called()
        mocked_create_event.assert_not_called()

    @patch("apps.users.views.verify_verification_token")
    @patch("apps.users.views.block.start_resend_cooldown")
    @patch("apps.users.views.create_outbox_event")
    def test_resend_returns_same_response_for_ineligible_accounts(
        self,
        mocked_create_event,
        mocked_start_cooldown,
        mocked_verify_token,
    ):
        mocked_verify_token.return_value = self.user.id

        responses = []

        mocked_start_cooldown.return_value = None
        responses.append(
            self.client.post(self.url, self.valid_data, format="json")
        )

        self.user.status = User.AccountStatus.ACTIVE
        self.user.save(update_fields=["status"])

        responses.append(
            self.client.post(self.url, self.valid_data, format="json")
        )

        for response in responses:
            self.assert_generic_response(response)

        mocked_create_event.assert_not_called()


class UserChangePasswordViewTests(APITestCase):

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.url = reverse("users:user-change-password")

        self.current_password = "CurrentStrong!2026"
        self.new_password = "NewStrongPassword!2026"

        self.user = User.objects.create_user(
            email="password-change@example.com",
            password=self.current_password,
            status=User.AccountStatus.ACTIVE,
        )

        access_token, refresh_token, self.session = create_session_tokens(
            user=self.user,
        )
        self.access_token = access_token
        self.refresh_token = RefreshToken(refresh_token)

        second_access_token, second_refresh_token, self.second_session = (
            create_session_tokens(user=self.user)
        )
        self.second_access_token = second_access_token
        self.second_refresh_token = RefreshToken(second_refresh_token)

    def authenticate_client(self):
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = str(self.refresh_token)

    def get_csrf_token(self):
        response = self.client.get(reverse("users:csrf-token"))
        return response.cookies[settings.CSRF_COOKIE_NAME].value

    def get_valid_data(self):
        return {
            "current_password": self.current_password,
            "new_password": self.new_password,
            "confirm_new_password": self.new_password,
        }

    def assert_auth_cookies_deleted(self, response):
        access_cookie = settings.SIMPLE_JWT["AUTH_COOKIE"]
        refresh_cookie = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]

        self.assertEqual(response.cookies[access_cookie].value, "")
        self.assertEqual(response.cookies[refresh_cookie].value, "")

    def test_successful_password_change(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.current_password))
        self.assert_auth_cookies_deleted(response)

        self.session.refresh_from_db()
        self.second_session.refresh_from_db()

        self.assertIsNotNone(self.session.revoked_at)
        self.assertIsNotNone(self.second_session.revoked_at)

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=self.refresh_token["jti"]
            ).exists()
        )
        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=self.second_refresh_token["jti"]
            ).exists()
        )

    @patch("apps.users.views.create_outbox_event")
    def test_successful_password_change_creates_outbox_event(
        self,
        mock_create_event,
    ):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_create_event.assert_called_once_with(
            event_type="users.password_changed",
            aggregate_type="user",
            aggregate_id=self.user.id,
            payload={"email": self.user.email},
        )

    def test_old_access_token_is_rejected_immediately_after_password_change(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    @patch(
        "apps.users.views.create_outbox_event",
        side_effect=RuntimeError("Outbox failure"),
    )
    def test_password_change_rolls_back_when_outbox_creation_fails(
        self,
        mock_create_event,
    ):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        with self.assertRaises(RuntimeError):
            self.client.post(
                self.url,
                self.get_valid_data(),
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.user.refresh_from_db()
        self.session.refresh_from_db()
        self.second_session.refresh_from_db()

        self.assertTrue(self.user.check_password(self.current_password))
        self.assertFalse(self.user.check_password(self.new_password))

        self.assertIsNone(self.session.revoked_at)
        self.assertIsNone(self.second_session.revoked_at)

        self.assertFalse(
            BlacklistedToken.objects.filter(
                token__jti=self.refresh_token["jti"]
            ).exists()
        )
        self.assertFalse(
            BlacklistedToken.objects.filter(
                token__jti=self.second_refresh_token["jti"]
            ).exists()
        )

        mock_create_event.assert_called_once()


    @patch(
        "apps.users.views.create_outbox_event",
        side_effect=RuntimeError("Outbox creation failed"),
    )
    def test_outbox_failure_rolls_back_password_and_token_revocation(
        self,
        mock_create_event,
    ):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        with self.assertRaisesMessage(RuntimeError, "Outbox creation failed"):
            self.client.post(
                self.url,
                self.get_valid_data(),
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        mock_create_event.assert_called_once()

        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(self.current_password))
        self.assertFalse(self.user.check_password(self.new_password))

        for refresh_token in (
            self.refresh_token,
            self.second_refresh_token,
        ):
            self.assertFalse(
                BlacklistedToken.objects.filter(
                    token__jti=refresh_token["jti"]
                ).exists()
            )

        # Session revocation must also roll back with the transaction.
        self.session.refresh_from_db()
        self.second_session.refresh_from_db()

        self.assertIsNone(self.session.revoked_at)
        self.assertIsNone(self.second_session.revoked_at)

    def test_successful_password_change_blacklists_all_refresh_tokens(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for refresh_token in (
            self.refresh_token,
            self.second_refresh_token,
        ):
            self.assertTrue(
                BlacklistedToken.objects.filter(
                    token__jti=refresh_token["jti"]
                ).exists()
            )

    def test_password_change_with_incorrect_current_password(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        data = {
            **self.get_valid_data(),
            "current_password": "IncorrectPassword!2026",
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("current_password", response.data)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.current_password))

        self.assertFalse(
            BlacklistedToken.objects.filter(
                token__jti=self.refresh_token["jti"]
            ).exists()
        )

    def test_password_change_with_mismatched_confirmation(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        data = {
            **self.get_valid_data(),
            "confirm_new_password": "DifferentPassword!2026",
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_new_password", response.data)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.current_password))

    def test_password_change_with_weak_new_password(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        data = {
            **self.get_valid_data(),
            "new_password": "weak",
            "confirm_new_password": "weak",
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.data)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.current_password))

    def test_password_change_without_authentication(self):
        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_password_change_without_csrf_token(self):
        self.authenticate_client()

        response = self.client.post(
            self.url,
            self.get_valid_data(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.current_password))

    def test_password_change_with_same_password_is_rejected(self):
        self.authenticate_client()
        csrf_token = self.get_csrf_token()

        data = {
            "current_password": self.current_password,
            "new_password": self.current_password,
            "confirm_new_password": self.current_password,
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.data)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.current_password))


class ForgotPasswordViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:forgot-password")

        self.user = User.objects.create_user(
            email="password-reset@example.com",
            password="CurrentStrongPassword!2026",
            status=User.AccountStatus.ACTIVE,
        )

        self.generic_response_data = {
            "detail": (
                "If the account is eligible, "
                "a password reset email will be sent."
            )
        }

        self.throttle_patcher = patch(
            "apps.users.throttles.ForgotPasswordThrottle.allow_request",
            return_value=True,
        )
        self.throttle_patcher.start()
        self.addCleanup(self.throttle_patcher.stop)

        self.addCleanup(
            _get_redis_client().delete,
            _get_password_reset_key(self.user.id),
        )

    def request_password_reset(self, email=None):
        return self.client.post(
            self.url,
            {"email": email or self.user.email},
            format="json",
        )

    def assert_generic_response(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.generic_response_data)

    def test_successful_password_reset_request(self):
        response = self.request_password_reset()

        self.assert_generic_response(response)

        event = OutboxEvent.objects.get(
            event_type="users.password_reset_requested",
            aggregate_type="user",
            aggregate_id=self.user.id,
        )

        self.assertEqual(event.payload["email"], self.user.email)
        self.assertIn("reset_token", event.payload)

        reset_token = event.payload["reset_token"]

        self.assertEqual(get_password_reset_user_id(reset_token), self.user.id)
        self.assertEqual(event.status, OutboxEvent.Status.PENDING)

    def test_unknown_email_returns_same_generic_response(self):
        response = self.request_password_reset(email="unknown@example.com")

        self.assert_generic_response(response)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_invalid_email_is_rejected(self):
        response = self.client.post(
            self.url,
            {"email": "invalid-email"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_missing_email_is_rejected(self):
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_new_request_invalidates_previous_reset_token(self):
        first_response = self.request_password_reset()
        self.assert_generic_response(first_response)

        first_event = OutboxEvent.objects.get(
            event_type="users.password_reset_requested",
            aggregate_id=self.user.id,
        )
        first_token = first_event.payload["reset_token"]

        second_response = self.request_password_reset()
        self.assert_generic_response(second_response)

        events = OutboxEvent.objects.filter(
            event_type="users.password_reset_requested",
            aggregate_id=self.user.id,
        ).order_by("created_at", "id")

        self.assertEqual(events.count(), 2)

        second_token = events.last().payload["reset_token"]

        self.assertIsNone(get_password_reset_user_id(first_token))
        self.assertEqual(get_password_reset_user_id(second_token), self.user.id)

    def test_pending_verification_user_can_request_reset(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.save(update_fields=["status"])

        response = self.request_password_reset()

        self.assert_generic_response(response)
        self.assertTrue(
            OutboxEvent.objects.filter(
                event_type="users.password_reset_requested",
                aggregate_id=self.user.id,
            ).exists()
        )

    def test_suspended_user_cannot_request_reset(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        response = self.request_password_reset()

        self.assert_generic_response(response)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_deactivated_user_cannot_request_reset(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        response = self.request_password_reset()

        self.assert_generic_response(response)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_inactive_user_cannot_request_reset(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.request_password_reset()

        self.assert_generic_response(response)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    def test_deleted_user_cannot_request_reset(self):
        self.user.soft_delete()

        response = self.request_password_reset()

        self.assert_generic_response(response)
        self.assertEqual(OutboxEvent.objects.count(), 0)

    @patch(
        "apps.users.views.create_outbox_event",
        side_effect=RuntimeError("Outbox creation failed"),
    )
    def test_outbox_failure_does_not_create_database_event(
        self,
        mocked_create_event,
    ):
        with self.assertRaisesMessage(RuntimeError, "Outbox creation failed"):
            self.request_password_reset()

        mocked_create_event.assert_called_once()
        self.assertEqual(OutboxEvent.objects.count(), 0)


class ResetPasswordViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:reset-password")

        self.current_password = "CurrentStrongPassword!2026"
        self.new_password = "BrandNewStrongPassword!2026"

        self.user = User.objects.create_user(
            email="reset-password@example.com",
            password=self.current_password,
            status=User.AccountStatus.ACTIVE,
        )

        self.email_verified_at = timezone.now()
        self.user.email_verified_at = self.email_verified_at
        self.user.save(update_fields=["email_verified_at"])

        self.reset_token = generate_password_reset_token(self.user.id)

        # First device
        self.access_token, refresh_token, self.session = create_session_tokens(
            user=self.user,
        )
        self.refresh_token = RefreshToken(refresh_token)

        # Second device
        (
            self.second_access_token,
            second_refresh_token,
            self.second_session,
        ) = create_session_tokens(user=self.user)

        self.second_refresh_token = RefreshToken(second_refresh_token)

        self.throttle_patcher = patch(
            "apps.users.throttles.ResetPasswordThrottle.allow_request",
            return_value=True,
        )
        self.throttle_patcher.start()
        self.addCleanup(self.throttle_patcher.stop)

        self.addCleanup(
            _get_redis_client().delete,
            _get_password_reset_key(self.user.id),
        )

    def get_valid_data(self):
        return {
            "token": self.reset_token,
            "new_password": self.new_password,
            "confirm_new_password": self.new_password,
        }

    def reset_password(self, data=None):
        return self.client.post(
            self.url,
            data or self.get_valid_data(),
            format="json",
        )

    def assert_password_unchanged(self):
        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(self.current_password))
        self.assertFalse(self.user.check_password(self.new_password))

    def assert_refresh_tokens_blacklisted(self):
        for refresh_token in (
            self.refresh_token,
            self.second_refresh_token,
        ):
            self.assertTrue(
                BlacklistedToken.objects.filter(
                    token__jti=refresh_token["jti"]
                ).exists()
            )

    def assert_sessions_revoked(self):
        self.session.refresh_from_db()
        self.second_session.refresh_from_db()

        self.assertIsNotNone(self.session.revoked_at)
        self.assertIsNotNone(self.second_session.revoked_at)

    def assert_sessions_active(self):
        self.session.refresh_from_db()
        self.second_session.refresh_from_db()

        self.assertIsNone(self.session.revoked_at)
        self.assertIsNone(self.second_session.revoked_at)

    def test_successful_password_reset(self):
        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            (
                "Password reset successfully. "
                "Please log in with your new password."
            ),
        )

        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.current_password))
        self.assertEqual(self.user.status, User.AccountStatus.ACTIVE)
        self.assertEqual(self.user.email_verified_at, self.email_verified_at)

        self.assert_sessions_revoked()
        self.assert_refresh_tokens_blacklisted()

        self.assertIsNone(get_password_reset_user_id(self.reset_token))

        self.assertEqual(
            response.cookies[settings.SIMPLE_JWT["AUTH_COOKIE"]].value,
            "",
        )
        self.assertEqual(
            response.cookies[
                settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
            ].value,
            "",
        )

    def test_successful_reset_creates_password_changed_event(self):
        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = OutboxEvent.objects.get(
            event_type="users.password_changed",
            aggregate_type="user",
            aggregate_id=self.user.id,
        )

        self.assertEqual(event.payload, {"email": self.user.email})

    def test_pending_verification_user_can_reset_password(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.email_verified_at = None
        self.user.save(update_fields=["status", "email_verified_at"])

        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(self.new_password))
        self.assertEqual(
            self.user.status,
            User.AccountStatus.PENDING_VERIFICATION,
        )
        self.assertIsNone(self.user.email_verified_at)

        self.assert_sessions_revoked()
        self.assert_refresh_tokens_blacklisted()

    def test_old_access_token_is_rejected_immediately_after_reset(self):
        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Reuse the first device's old access token.
        response = self.client.post(
            reverse("users:user-change-password"),
            {},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.access_token}",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_invalid_token_is_rejected(self):
        data = {**self.get_valid_data(), "token": "invalid-token"}

        response = self.reset_password(data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("token", response.data)
        self.assert_password_unchanged()
        self.assert_sessions_active()

    def test_missing_token_is_rejected(self):
        data = self.get_valid_data()
        data.pop("token")

        response = self.reset_password(data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("token", response.data)
        self.assert_password_unchanged()

    def test_expired_token_is_rejected(self):
        with patch(
            "apps.users.services.password_reset.signing.loads",
            side_effect=__import__(
                "django.core.signing",
                fromlist=["SignatureExpired"],
            ).SignatureExpired("Expired"),
        ):
            response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("token", response.data)
        self.assert_password_unchanged()

    def test_token_can_only_be_used_once(self):
        first_response = self.reset_password()

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)

        second_response = self.reset_password()

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("token", second_response.data)

    def test_password_mismatch_is_rejected(self):
        data = {
            **self.get_valid_data(),
            "confirm_new_password": "DifferentStrongPassword!2026",
        }

        response = self.reset_password(data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_new_password", response.data)
        self.assert_password_unchanged()
        self.assertEqual(
            get_password_reset_user_id(self.reset_token),
            self.user.id,
        )

    def test_weak_password_is_rejected(self):
        data = {
            **self.get_valid_data(),
            "new_password": "weak",
            "confirm_new_password": "weak",
        }

        response = self.reset_password(data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.data)
        self.assert_password_unchanged()
        self.assertEqual(
            get_password_reset_user_id(self.reset_token),
            self.user.id,
        )

    def test_same_password_is_rejected(self):
        data = {
            **self.get_valid_data(),
            "new_password": self.current_password,
            "confirm_new_password": self.current_password,
        }

        response = self.reset_password(data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.data)
        self.assert_password_unchanged()
        self.assertEqual(
            get_password_reset_user_id(self.reset_token),
            self.user.id,
        )

    def test_suspended_user_cannot_reset_password(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_password_unchanged()

    def test_deactivated_user_cannot_reset_password(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_password_unchanged()

    def test_inactive_user_cannot_reset_password(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_password_unchanged()

    def test_deleted_user_cannot_reset_password(self):
        self.user.soft_delete()

        response = self.reset_password()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_password_unchanged()

    @patch(
        "apps.users.views.create_outbox_event",
        side_effect=RuntimeError("Outbox creation failed"),
    )
    def test_outbox_failure_rolls_back_password_and_session_revocation(
        self,
        mocked_create_event,
    ):
        with self.assertRaisesMessage(RuntimeError, "Outbox creation failed"):
            self.reset_password()

        mocked_create_event.assert_called_once()

        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(self.current_password))
        self.assertFalse(self.user.check_password(self.new_password))

        self.assert_sessions_active()

        for refresh_token in (
            self.refresh_token,
            self.second_refresh_token,
        ):
            self.assertFalse(
                BlacklistedToken.objects.filter(
                    token__jti=refresh_token["jti"]
                ).exists()
            )

        # Redis consumption is not rolled back with the database.
        self.assertIsNone(get_password_reset_user_id(self.reset_token))


class RefreshAccessTokenViewTests(APITestCase):
    url = reverse("users:token-refresh")

    def setUp(self):
        self.user = User.objects.create_user(
            email="refresh@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
            is_active=True,
        )

        self.access_token, self.refresh_token, self.session = (
            create_session_tokens(user=self.user)
        )

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = self.refresh_token

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

        self.csrf_client = self.client

    def _set_csrf_cookie(self):
        self.client.cookies["csrftoken"] = "test-csrf-token"

    def _post(self):
        self._set_csrf_cookie()
        return self.client.post(
            self.url,
            HTTP_X_CSRFTOKEN="test-csrf-token",
        )

    def _get_refresh_cookie(self, response):
        return response.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ].value

    def _get_access_cookie(self, response):
        return response.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ].value

    def test_refresh_successfully_rotates_tokens(self):
        old_jti = self.session.refresh_token_jti

        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        new_access = AccessToken(
            self._get_access_cookie(response)
        )
        new_refresh = RefreshToken(
            self._get_refresh_cookie(response)
        )

        self.session.refresh_from_db()

        self.assertEqual(
            str(new_access["sid"]),
            str(self.session.id),
        )
        self.assertEqual(
            str(new_refresh["sid"]),
            str(self.session.id),
        )
        self.assertNotEqual(
            old_jti,
            self.session.refresh_token_jti,
        )
        self.assertEqual(
            str(new_refresh["jti"]),
            self.session.refresh_token_jti,
        )

    def test_old_refresh_token_cannot_be_reused(self):
        first_response = self._post()

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = self.refresh_token

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_without_refresh_cookie(self):
        self.client.cookies.pop(
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"],
            None,
        )

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_with_invalid_token(self):
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = "invalid-token"

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_for_deleted_user(self):
        self.user.deleted_at = timezone.now()
        self.user.save(update_fields=["deleted_at"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_for_inactive_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_for_suspended_user(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_for_deactivated_user(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_pending_verification_user_can_refresh(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.save(update_fields=["status"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_for_revoked_session(self):
        self.session.revoked_at = timezone.now()
        self.session.save(update_fields=["revoked_at"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_for_expired_session(self):
        self.session.expires_at = timezone.now() - timedelta(minutes=1)
        self.session.save(update_fields=["expires_at"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_when_session_does_not_exist(self):
        self.session.delete()

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_when_session_belongs_to_another_user(self):
        another_user = User.objects.create_user(
            email="another@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
            is_active=True,
        )

        self.session.user = another_user
        self.session.save(update_fields=["user"])

        response = self._post()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_fails_without_csrf_token(self):

        client = APIClient(enforce_csrf_checks=True)

        client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        ] = self.refresh_token

        client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

        response = client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )


class UserSessionListViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:user-session-list")

        self.user = User.objects.create_user(
            email="session-list@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.other_user = User.objects.create_user(
            email="other-session-list@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.access_token, _, self.current_session = (
            create_session_tokens(user=self.user)
        )

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

    def test_authenticated_user_can_list_active_sessions(self):
        _, _, second_session = create_session_tokens(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        session_ids = {
            str(item["id"])
            for item in response.data
        }

        self.assertEqual(
            session_ids,
            {
                str(self.current_session.id),
                str(second_session.id),
            },
        )

    def test_list_excludes_revoked_sessions(self):
        _, _, revoked_session = create_session_tokens(user=self.user)

        revoked_session.revoked_at = timezone.now()
        revoked_session.save(update_fields=["revoked_at"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session_ids = {
            str(item["id"])
            for item in response.data
        }

        self.assertNotIn(str(revoked_session.id), session_ids)

    def test_list_excludes_expired_sessions(self):
        _, _, expired_session = create_session_tokens(user=self.user)

        UserSession.objects.filter(
            id=expired_session.id,
        ).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session_ids = {
            str(item["id"])
            for item in response.data
        }

        self.assertNotIn(str(expired_session.id), session_ids)

    def test_list_does_not_include_other_users_sessions(self):
        _, _, other_session = create_session_tokens(
            user=self.other_user,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session_ids = {
            str(item["id"])
            for item in response.data
        }

        self.assertNotIn(str(other_session.id), session_ids)

    def test_current_session_is_identified_correctly(self):
        _, _, another_session = create_session_tokens(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        sessions = {
            str(item["id"]): item
            for item in response.data
        }

        self.assertTrue(
            sessions[str(self.current_session.id)]["is_current"]
        )

        self.assertFalse(
            sessions[str(another_session.id)]["is_current"]
        )

    def test_unauthenticated_user_cannot_list_sessions(self):
        self.client.cookies.pop(
            settings.SIMPLE_JWT["AUTH_COOKIE"],
            None,
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class UserSessionRevokeViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="session-revoke@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.other_user = User.objects.create_user(
            email="other-session-revoke@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.access_token, self.refresh_token, self.session = (
            create_session_tokens(user=self.user)
        )

        self.url = reverse(
            "users:user-session-revoke",
            kwargs={"session_id": self.session.id},
        )

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

    def test_authenticated_user_can_revoke_own_session(self):
        response = self.client.delete(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.revoked_at)

    def test_revoking_session_blacklists_refresh_token(self):
        refresh_jti = self.session.refresh_token_jti

        response = self.client.delete(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_204_NO_CONTENT,
        )

        self.assertTrue(
            OutstandingToken.objects.filter(
                jti=refresh_jti,
                blacklistedtoken__isnull=False,
            ).exists()
        )

    def test_user_cannot_revoke_another_users_session(self):
        _, _, other_session = create_session_tokens(
            user=self.other_user
        )

        url = reverse(
            "users:user-session-revoke",
            kwargs={"session_id": other_session.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        other_session.refresh_from_db()
        self.assertIsNone(other_session.revoked_at)

    def test_revoke_nonexistent_session_returns_404(self):
        nonexistent_session_id = UUID(
            "00000000-0000-0000-0000-000000000000"
        )

        url = reverse(
            "users:user-session-revoke",
            kwargs={"session_id": nonexistent_session_id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_revoking_already_revoked_session_returns_404(self):
        _, _, revoked_session = create_session_tokens(
            user=self.user
        )

        revoked_session.revoked_at = timezone.now()
        revoked_session.save(update_fields=["revoked_at"])

        url = reverse(
            "users:user-session-revoke",
            kwargs={"session_id": revoked_session.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_user_cannot_revoke_session(self):
        self.client.cookies.pop(
            settings.SIMPLE_JWT["AUTH_COOKIE"],
            None,
        )

        response = self.client.delete(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class UserLogoutAllSessionsViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="logout-all@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.other_user = User.objects.create_user(
            email="other-logout-all@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.access_token, self.refresh_token, self.current_session = (
            create_session_tokens(user=self.user)
        )

        self.url = reverse("users:user-session-logout-all")

        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = self.access_token

    def test_authenticated_user_can_revoke_all_sessions(self):
        _, _, second_session = create_session_tokens(user=self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["revoked_count"], 2)

        self.current_session.refresh_from_db()
        second_session.refresh_from_db()

        self.assertIsNotNone(self.current_session.revoked_at)
        self.assertIsNotNone(second_session.revoked_at)

    def test_all_refresh_tokens_are_blacklisted(self):
        _, _, second_session = create_session_tokens(user=self.user)

        jtis = {
            self.current_session.refresh_token_jti,
            second_session.refresh_token_jti,
        }

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        blacklisted_jtis = set(
            OutstandingToken.objects.filter(
                user=self.user,
                jti__in=jtis,
                blacklistedtoken__isnull=False,
            ).values_list("jti", flat=True)
        )

        self.assertEqual(blacklisted_jtis, jtis)

    def test_logout_all_deletes_authentication_cookies(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        access_cookie = settings.SIMPLE_JWT["AUTH_COOKIE"]
        refresh_cookie = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]

        self.assertEqual(response.cookies[access_cookie].value, "")
        self.assertEqual(response.cookies[refresh_cookie].value, "")

    def test_logout_all_does_not_revoke_other_users_sessions(self):
        _, _, other_session = create_session_tokens(
            user=self.other_user
        )

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        other_session.refresh_from_db()
        self.assertIsNone(other_session.revoked_at)

    def test_logout_all_returns_zero_when_no_active_sessions_remain(self):
        self.current_session.revoked_at = timezone.now()
        self.current_session.save(update_fields=["revoked_at"])

        # Use a fresh session for authentication.
        access_token, _, _ = create_session_tokens(user=self.user)
        self.client.cookies[
            settings.SIMPLE_JWT["AUTH_COOKIE"]
        ] = access_token

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["revoked_count"], 1)

    def test_unauthenticated_user_cannot_logout_all_sessions(self):
        self.client.cookies.pop(
            settings.SIMPLE_JWT["AUTH_COOKIE"],
            None,
        )

        response = self.client.post(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
