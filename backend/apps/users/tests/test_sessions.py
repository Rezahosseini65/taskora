
import uuid
from datetime import timedelta

from django.test import RequestFactory, TestCase
from django.utils import timezone

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.users.models import User, UserSession
from apps.users.services.sessions import (
    SESSION_ACTIVITY_UPDATE_INTERVAL,
    SessionError,
    create_session_tokens,
    revoke_all_user_sessions,
    revoke_session,
    rotate_session_tokens,
    touch_session_activity,
)


class SessionServiceTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="session@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        self.other_user = User.objects.create_user(
            email="other-session@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

    def create_session(self, user=None, request=None):
        user = user or self.user

        return create_session_tokens(
            user=user,
            request=request,
        )

    def test_create_session_tokens_creates_session(self):
        access_token, refresh_token, session = self.create_session()

        self.assertIsInstance(session, UserSession)
        self.assertEqual(session.user, self.user)
        self.assertIsNone(session.revoked_at)

        self.assertTrue(access_token)
        self.assertTrue(refresh_token)

    def test_created_tokens_contain_same_session_id(self):
        access_token, refresh_token, session = self.create_session()

        access = AccessToken(access_token)
        refresh = RefreshToken(refresh_token)

        self.assertEqual(access["sid"], str(session.id))
        self.assertEqual(refresh["sid"], str(session.id))

    def test_created_session_stores_refresh_token_jti(self):
        _, refresh_token, session = self.create_session()

        refresh = RefreshToken(refresh_token)

        self.assertEqual(
            session.refresh_token_jti,
            refresh["jti"],
        )

    def test_outstanding_token_contains_session_id(self):
        _, refresh_token, _ = self.create_session()

        refresh = RefreshToken(refresh_token)

        outstanding = OutstandingToken.objects.get(
            jti=refresh["jti"],
        )

        stored_refresh = RefreshToken(outstanding.token)

        self.assertEqual(
            stored_refresh["sid"],
            refresh["sid"],
        )

    def test_session_stores_request_metadata(self):
        request = RequestFactory().get(
            "/",
            HTTP_USER_AGENT="Taskora Test Browser",
            REMOTE_ADDR="192.168.1.10",
        )

        _, _, session = self.create_session(request=request)

        self.assertEqual(session.ip_address, "192.168.1.10")
        self.assertEqual(
            session.user_agent,
            "Taskora Test Browser",
        )

    def test_create_session_without_request(self):
        _, _, session = self.create_session()

        self.assertIsNone(session.ip_address)
        self.assertEqual(session.user_agent, "")


class SessionRotationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="rotation@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        (
            self.access_token,
            self.refresh_token,
            self.session,
        ) = create_session_tokens(self.user)

    def test_rotation_issues_new_tokens(self):
        old_refresh = RefreshToken(self.refresh_token)

        new_access, new_refresh_token, session = rotate_session_tokens(
            self.user,
            self.refresh_token,
        )

        new_refresh = RefreshToken(new_refresh_token)

        self.assertNotEqual(
            str(old_refresh["jti"]),
            str(new_refresh["jti"]),
        )

        self.assertEqual(
            new_access and AccessToken(new_access)["sid"],
            str(self.session.id),
        )

        self.assertEqual(
            new_refresh["sid"],
            str(self.session.id),
        )

        self.assertEqual(session.id, self.session.id)

    def test_rotation_updates_session_refresh_jti(self):
        new_access, new_refresh_token, session = rotate_session_tokens(
            self.user,
            self.refresh_token,
        )

        new_refresh = RefreshToken(new_refresh_token)

        self.assertEqual(
            session.refresh_token_jti,
            new_refresh["jti"],
        )

    def test_rotation_blacklists_previous_refresh_token(self):
        old_refresh = RefreshToken(self.refresh_token)
        old_jti = old_refresh["jti"]

        rotate_session_tokens(
            self.user,
            self.refresh_token,
        )

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=old_jti,
            ).exists()
        )

    def test_previous_refresh_token_cannot_be_reused(self):
        rotate_session_tokens(
            self.user,
            self.refresh_token,
        )

        with self.assertRaises(SessionError):
            rotate_session_tokens(
                self.user,
                self.refresh_token,
            )

    def test_rotation_creates_outstanding_record_for_new_token(self):
        _, new_refresh_token, _ = rotate_session_tokens(
            self.user,
            self.refresh_token,
        )

        new_refresh = RefreshToken(new_refresh_token)

        self.assertTrue(
            OutstandingToken.objects.filter(
                jti=new_refresh["jti"],
            ).exists()
        )

    def test_rotation_rejects_token_without_session_id(self):
        refresh = RefreshToken.for_user(self.user)

        with self.assertRaises(SessionError):
            rotate_session_tokens(
                self.user,
                str(refresh),
            )

    def test_rotation_rejects_another_users_token(self):
        other_user = User.objects.create_user(
            email="wrong-user@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        with self.assertRaises(SessionError):
            rotate_session_tokens(
                other_user,
                self.refresh_token,
            )

    def test_rotation_rejects_invalid_token(self):
        with self.assertRaises(SessionError):
            rotate_session_tokens(
                self.user,
                "invalid-refresh-token",
            )

    def test_rotation_rejects_revoked_session(self):
        revoke_session(self.session.id, self.user)

        with self.assertRaises(SessionError):
            rotate_session_tokens(
                self.user,
                self.refresh_token,
            )

    def test_rotation_rejects_expired_session(self):
        UserSession.objects.filter(
            id=self.session.id,
        ).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        with self.assertRaises(SessionError):
            rotate_session_tokens(
                self.user,
                self.refresh_token,
            )


class SessionRevocationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="revoke@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

    def test_revoke_session_sets_revoked_at(self):
        _, _, session = create_session_tokens(self.user)

        result = revoke_session(session.id, self.user)

        session.refresh_from_db()

        self.assertTrue(result)
        self.assertIsNotNone(session.revoked_at)

    def test_revoke_session_blacklists_refresh_token(self):
        _, refresh_token, session = create_session_tokens(self.user)

        refresh = RefreshToken(refresh_token)

        revoke_session(session.id, self.user)

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=refresh["jti"],
            ).exists()
        )

    def test_revoke_session_returns_false_if_already_revoked(self):
        _, _, session = create_session_tokens(self.user)

        first_result = revoke_session(session.id, self.user)
        second_result = revoke_session(session.id, self.user)

        self.assertTrue(first_result)
        self.assertFalse(second_result)

    def test_revoke_session_returns_false_for_unknown_session(self):
        result = revoke_session(uuid.uuid4(), self.user)

        self.assertFalse(result)

    def test_user_cannot_revoke_another_users_session(self):
        other_user = User.objects.create_user(
            email="session-owner@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        _, _, session = create_session_tokens(other_user)

        result = revoke_session(session.id, self.user)

        self.assertFalse(result)

        session.refresh_from_db()
        self.assertIsNone(session.revoked_at)

    def test_revoke_all_user_sessions(self):
        _, _, first_session = create_session_tokens(self.user)
        _, _, second_session = create_session_tokens(self.user)

        revoked_count = revoke_all_user_sessions(self.user)

        first_session.refresh_from_db()
        second_session.refresh_from_db()

        self.assertEqual(revoked_count, 2)
        self.assertIsNotNone(first_session.revoked_at)
        self.assertIsNotNone(second_session.revoked_at)

    def test_revoke_all_blacklists_all_outstanding_tokens(self):
        _, first_refresh, _ = create_session_tokens(self.user)
        _, second_refresh, _ = create_session_tokens(self.user)

        first_jti = RefreshToken(first_refresh)["jti"]
        second_jti = RefreshToken(second_refresh)["jti"]

        revoke_all_user_sessions(self.user)

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=first_jti,
            ).exists()
        )

        self.assertTrue(
            BlacklistedToken.objects.filter(
                token__jti=second_jti,
            ).exists()
        )

    def test_revoke_all_does_not_revoke_another_users_sessions(self):
        other_user = User.objects.create_user(
            email="unaffected@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        _, _, other_session = create_session_tokens(other_user)
        _, _, own_session = create_session_tokens(self.user)

        revoke_all_user_sessions(self.user)

        own_session.refresh_from_db()
        other_session.refresh_from_db()

        self.assertIsNotNone(own_session.revoked_at)
        self.assertIsNone(other_session.revoked_at)

    def test_revoke_all_returns_zero_without_active_sessions(self):
        result = revoke_all_user_sessions(self.user)

        self.assertEqual(result, 0)


class SessionActivityTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="activity@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        _, _, self.session = create_session_tokens(self.user)

    def test_touch_updates_old_session_activity(self):
        old_activity = timezone.now() - timedelta(
            seconds=SESSION_ACTIVITY_UPDATE_INTERVAL + 60,
        )

        UserSession.objects.filter(
            id=self.session.id,
        ).update(
            last_activity_at=old_activity,
        )

        touch_session_activity(
            self.session.id,
            self.user.id,
        )

        self.session.refresh_from_db()

        self.assertGreater(
            self.session.last_activity_at,
            old_activity,
        )

    def test_touch_does_not_update_recent_activity(self):
        recent_activity = timezone.now()

        UserSession.objects.filter(
            id=self.session.id,
        ).update(
            last_activity_at=recent_activity,
        )

        touch_session_activity(
            self.session.id,
            self.user.id,
        )

        self.session.refresh_from_db()

        self.assertEqual(
            self.session.last_activity_at,
            recent_activity,
        )

    def test_touch_does_not_update_revoked_session(self):
        old_activity = timezone.now() - timedelta(minutes=10)

        UserSession.objects.filter(
            id=self.session.id,
        ).update(
            last_activity_at=old_activity,
            revoked_at=timezone.now(),
        )

        touch_session_activity(
            self.session.id,
            self.user.id,
        )

        self.session.refresh_from_db()

        self.assertEqual(
            self.session.last_activity_at,
            old_activity,
        )

    def test_touch_does_not_update_expired_session(self):
        old_activity = timezone.now() - timedelta(minutes=10)

        UserSession.objects.filter(
            id=self.session.id,
        ).update(
            last_activity_at=old_activity,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        touch_session_activity(
            self.session.id,
            self.user.id,
        )

        self.session.refresh_from_db()

        self.assertEqual(
            self.session.last_activity_at,
            old_activity,
        )

    def test_touch_does_not_update_another_users_session(self):
        other_user = User.objects.create_user(
            email="other-activity@example.com",
            password="StrongPassword123!",
            status=User.AccountStatus.ACTIVE,
        )

        _, _, other_session = create_session_tokens(other_user)

        old_activity = timezone.now() - timedelta(minutes=10)

        UserSession.objects.filter(
            id=other_session.id,
        ).update(
            last_activity_at=old_activity,
        )

        touch_session_activity(
            other_session.id,
            self.user.id,
        )

        other_session.refresh_from_db()

        self.assertEqual(
            other_session.last_activity_at,
            old_activity,
        )
