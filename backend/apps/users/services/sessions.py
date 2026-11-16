import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.users.models import UserSession

User = get_user_model()

SESSION_ACTIVITY_UPDATE_INTERVAL = 5 * 60


class SessionError(Exception):
    """Raised when a session operation cannot be completed."""


def _get_token_expiration(token: RefreshToken) -> datetime:
    return datetime.fromtimestamp(
        token["exp"],
        tz=datetime_timezone.utc,
    )


def _get_request_metadata(request) -> dict:
    if request is None:
        return {
            "ip_address": None,
            "user_agent": "",
        }

    return {
        "ip_address": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:1000],
    }


def _record_outstanding_token(token: RefreshToken, user) -> None:
    """
    Ensure the current refresh token is recorded in OutstandingToken.
    """
    jti = token[api_settings.JTI_CLAIM]

    outstanding_token, _ = OutstandingToken.objects.get_or_create(
        jti=jti,
        defaults={
            "user": user,
            "token": str(token),
            "created_at": timezone.now(),
            "expires_at": _get_token_expiration(token),
        },
    )

    outstanding_token.user = user
    outstanding_token.token = str(token)
    outstanding_token.expires_at = _get_token_expiration(token)

    outstanding_token.save(
        update_fields=[
            "user",
            "token",
            "expires_at",
        ]
    )


def _blacklist_outstanding_tokens(queryset) -> int:
    tokens = list(queryset)

    if not tokens:
        return 0

    BlacklistedToken.objects.bulk_create(
        [
            BlacklistedToken(token=token)
            for token in tokens
        ],
        ignore_conflicts=True,
    )

    return len(tokens)


@transaction.atomic
def create_session_tokens(user, request=None) -> tuple[str, str, UserSession]:
    """
    Create a new user session and issue its access and refresh tokens.
    """
    User.objects.select_for_update().get(pk=user.pk)

    session_id = uuid.uuid4()

    refresh = RefreshToken.for_user(user)
    refresh["sid"] = str(session_id)

    session = UserSession.objects.create(
        id=session_id,
        user=user,
        refresh_token_jti=refresh[api_settings.JTI_CLAIM],
        expires_at=_get_token_expiration(refresh),
        **_get_request_metadata(request),
    )

    _record_outstanding_token(refresh, user)

    access = refresh.access_token

    return str(access), str(refresh), session


@transaction.atomic
def rotate_session_tokens(
    user,
    refresh_token: str,
) -> tuple[str, str, UserSession]:
    """
    Validate and rotate a refresh token for its existing session.

    The session row is locked to prevent concurrent refresh operations.
    """
    try:
        refresh = RefreshToken(refresh_token)

        session_id = UUID(str(refresh["sid"]))
        token_jti = str(refresh[api_settings.JTI_CLAIM])
        token_user_id = str(refresh[api_settings.USER_ID_CLAIM])

    except (TokenError, KeyError, TypeError, ValueError) as exc:
        raise SessionError("Invalid refresh token.") from exc

    if token_user_id != str(user.pk):
        raise SessionError("Invalid refresh token.")

    try:
        session = (
            UserSession.objects
            .select_for_update()
            .get(
                id=session_id,
                user=user,
                refresh_token_jti=token_jti,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
        )
    except UserSession.DoesNotExist as exc:
        raise SessionError("Session is invalid or expired.") from exc

    # Blacklist the previous refresh token before rotating it.
    refresh.blacklist()

    refresh.set_jti()
    refresh.set_iat()
    refresh.set_exp()

    new_jti = str(refresh[api_settings.JTI_CLAIM])

    session.refresh_token_jti = new_jti
    session.expires_at = _get_token_expiration(refresh)
    session.last_activity_at = timezone.now()

    session.save(
        update_fields=[
            "refresh_token_jti",
            "expires_at",
            "last_activity_at",
        ]
    )

    _record_outstanding_token(refresh, user)

    access = refresh.access_token

    return str(access), str(refresh), session


@transaction.atomic
def revoke_session(session_id: UUID, user) -> bool:
    """
    Revoke one session belonging to the specified user.
    """
    try:
        session = (
            UserSession.objects
            .select_for_update()
            .get(
                id=session_id,
                user=user,
                revoked_at__isnull=True,
            )
        )
    except UserSession.DoesNotExist:
        return False

    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at"])

    _blacklist_outstanding_tokens(
        OutstandingToken.objects.filter(
            user=user,
            jti=session.refresh_token_jti,
            blacklistedtoken__isnull=True,
        )
    )

    return True


@transaction.atomic
def revoke_all_user_sessions(user) -> int:
    """
    Revoke all sessions and outstanding refresh tokens for a user.
    """
    User.objects.select_for_update().get(pk=user.pk)

    now = timezone.now()

    sessions = list(
        UserSession.objects
        .select_for_update()
        .filter(
            user=user,
            revoked_at__isnull=True,
        )
    )

    revoked_count = len(sessions)

    UserSession.objects.filter(
        user=user,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    _blacklist_outstanding_tokens(
        OutstandingToken.objects.filter(
            user=user,
            blacklistedtoken__isnull=True,
        )
    )

    return revoked_count


def touch_session_activity(session_id: UUID, user_id) -> None:
    """
    Update last activity at most once per configured interval.
    """
    now = timezone.now()
    activity_threshold = now - timedelta(
        seconds=SESSION_ACTIVITY_UPDATE_INTERVAL
    )

    UserSession.objects.filter(
        id=session_id,
        user_id=user_id,
        revoked_at__isnull=True,
        expires_at__gt=now,
        last_activity_at__lt=activity_threshold,
    ).update(last_activity_at=now)
