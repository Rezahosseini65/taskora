import logging
from uuid import UUID

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema

from rest_framework import status
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.outbox.services import create_outbox_event
from apps.users.services import block, otp
from apps.users.services.password_reset import (
    consume_password_reset_token,
    generate_password_reset_token,
    get_password_reset_user_id,
)
from apps.users.services.sessions import (
    SessionError,
    create_session_tokens,
    revoke_all_user_sessions,
    revoke_session,
    rotate_session_tokens,
)
from apps.users.services.verification import (
    generate_verification_token,
    verify_verification_token,
)

from common.authentication.jwt import CookieJWTAuthentication
from common.utils.services import TokenCookieManager

from .models import User, UserSession
from .serializers import (
    EmailVerificationSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    ResendVerificationEmailSerializer,
    UserChangePasswordSerializer,
    UserLoginSerializer,
    UserRegisterSerializer,
    UserSessionSerializer,
)
from .throttles import (
    EmailVerificationResendThrottle,
    EmailVerificationThrottle,
    ForgotPasswordThrottle,
    ResetPasswordThrottle,
    UserLoginThrottle,
    UserRegisterThrottle,
)


logger = logging.getLogger(__name__)


def _activate_resend_generation_after_commit(user_id, request_id):
    """
    Activate the generation after the Outbox event has been committed.

    Failures are logged but not raised because the database transaction
    has already committed. The Outbox handler will retry activation.
    """
    try:
        block.activate_resend_generation(
            user_id=user_id,
            request_id=request_id,
        )
    except Exception:
        logger.exception(
            "Failed to activate email verification generation "
            "after commit for user %s.",
            user_id,
        )


class UserRegisterView(APIView):
    """
    Handle user registration and create an email verification event.

    User creation and Outbox event creation are performed
    within a single database transaction.
    """

    throttle_classes = [UserRegisterThrottle]
    authentication_classes = []

    @extend_schema(
        request=UserRegisterSerializer,
        responses={
            201: OpenApiResponse(
                description="Registration successful. Email verification required."
            ),
        },
    )
    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = dict(serializer.validated_data)
        password = validated_data.pop("password")
        validated_data.pop("confirm_password", None)

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    password=password,
                    **validated_data,
                )

                generation = block.initialize_generation(user.id)

                create_outbox_event(
                    event_type="users.email_verification_requested",
                    aggregate_type="user",
                    aggregate_id=user.id,
                    payload={
                        "email": user.email,
                        "generation": generation,
                    },
                )

                verification_token = generate_verification_token(
                    user_id=user.id
                )

        except IntegrityError:
            logger.warning(
                "User registration failed due to a database integrity error."
            )
            return Response(
                {
                    "email": [
                        "This email address is already in use. "
                        "Please use another one."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:
            logger.exception("Unexpected error during user registration.")
            raise

        return Response(
            {
                "detail": (
                    "Registration successful. "
                    "Please verify your email address."
                ),
                "verification_token": verification_token,
            },
            status=status.HTTP_201_CREATED,
        )


class EmailVerificationView(APIView):
    """
    Verify a user's email address using a signed verification token
    and a one-time verification code.

    Upon successful verification, activate the account and issue
    access and refresh JWT tokens through HttpOnly cookies.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [EmailVerificationThrottle]

    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_token = serializer.validated_data["verification_token"]
        verification_code = serializer.validated_data["verification_code"]

        user_id = verify_verification_token(verification_token)

        if user_id is None:
            raise ValidationError({
                "verification_token": (
                    "Invalid or expired verification token."
                )
            })

        with transaction.atomic():
            try:
                user = User.all_objects.select_for_update().get(
                    pk=user_id,
                )
            except User.DoesNotExist:
                raise ValidationError({
                    "verification_token": (
                        "Invalid or expired verification token."
                    )
                })

            if user.deleted_at is not None:
                raise ValidationError({
                    "verification_token": (
                        "Invalid or expired verification token."
                    )
                })

            if user.status != User.AccountStatus.PENDING_VERIFICATION:
                raise ValidationError({
                    "detail": "This account does not require verification."
                })

            verification_result = otp.verify_and_consume_verification_code(
                user_id=user.id,
                code=verification_code,
            )

            if verification_result == -1:
                return Response(
                    {
                        "detail": (
                            "Too many failed attempts. "
                            "Please try again later."
                        )
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            if verification_result is not True:
                raise ValidationError({
                    "verification_code": (
                        "Invalid or expired verification code."
                    )
                })

            user.status = User.AccountStatus.ACTIVE
            user.email_verified_at = timezone.now()

            user.save(
                update_fields=[
                    "status",
                    "email_verified_at",
                    "updated_at",
                ]
            )

        access_token, refresh_token, session = create_session_tokens(
            user=user,
            request=request,
        )

        response = Response(
            {
                "detail": "Email verified successfully."
            },
            status=status.HTTP_200_OK,
        )

        TokenCookieManager.set_access_cookie(response, access_token)
        TokenCookieManager.set_refresh_cookie(response, refresh_token)

        return response


class ResendVerificationEmailView(APIView):
    """
    Resend an email verification code to an eligible account.

    A generic response is returned regardless of account eligibility
    to prevent account enumeration.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [EmailVerificationResendThrottle]

    def post(self, request):
        serializer = ResendVerificationEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_token = serializer.validated_data["verification_token"]
        user_id = verify_verification_token(verification_token)

        generic_response = Response(
            {
                "detail": (
                    "If the account is eligible, "
                    "a verification email will be sent."
                )
            },
            status=status.HTTP_200_OK,
        )

        if user_id is None:
            return generic_response

        request_id = None

        try:
            with transaction.atomic():
                try:
                    user = (
                        User.all_objects
                        .select_for_update()
                        .get(pk=user_id)
                    )
                except User.DoesNotExist:
                    return generic_response

                if (
                    user.deleted_at is not None
                    or user.status != User.AccountStatus.PENDING_VERIFICATION
                ):
                    return generic_response

                request_id = block.start_resend_cooldown(user.id)

                if request_id is None:
                    return generic_response

                create_outbox_event(
                    event_type="users.email_verification_requested",
                    aggregate_type="user",
                    aggregate_id=user.id,
                    payload={
                        "email": user.email,
                        "request_id": request_id,
                    },
                )

                transaction.on_commit(
                    lambda uid=user.id, rid=request_id: (
                        _activate_resend_generation_after_commit(uid, rid)
                    )
                )

        except Exception:
            if request_id is not None:
                try:
                    block.clear_resend_cooldown(
                        user_id,
                        request_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to clear email verification resend cooldown."
                    )

            logger.exception(
                "Failed to create email verification resend event."
            )
            raise

        return generic_response


class UserLoginView(APIView):
    throttle_classes = [UserLoginThrottle]
    authentication_classes = []

    @extend_schema(
            request=UserLoginSerializer,
            responses={
                200: OpenApiResponse(
                    description="Login successful"
                ),
            },
        )

    def post(self, request):
        serializer = UserLoginSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]

        try:
            access_token, refresh_token, session = create_session_tokens(
                user=user,
                request=request,
            )

            response = Response(
                {"detail": "Login successful"},
                status=status.HTTP_200_OK,
            )

            TokenCookieManager.set_access_cookie(response, access_token)
            TokenCookieManager.set_refresh_cookie(response, refresh_token)

            return response

        except Exception:
            logger.exception("Unexpected error during user login.")
            raise


class CSRFTokenView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def get(self, request):
        get_token(request)
        return Response(
            {"detail": "CSRF cookie set successfully."},
            status=status.HTTP_200_OK,
        )


class UserLogoutView(APIView):

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session_id = UUID(str(request.auth["sid"]))

        revoke_session(
            session_id=session_id,
            user=request.user,
        )

        response = Response(
            {"detail": "Logout successful."},
            status=status.HTTP_200_OK,
        )

        TokenCookieManager.delete_tokens_cookies(response)

        return response


class RefreshAccessTokenView(APIView):
    """
    Refresh access and refresh tokens using the refresh token
    stored in an HTTP-only cookie.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def enforce_csrf(self, request):
        check = CSRFCheck(lambda request: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})

        if reason:
            raise PermissionDenied(f"CSRF Failed: {reason}")

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                description="Access token refreshed successfully."
            ),
            401: OpenApiResponse(
                description="Refresh token is invalid or account is unavailable."
            ),
            403: OpenApiResponse(
                description="CSRF validation failed."
            ),
        },
    )
    def post(self, request):
        refresh_cookie_name = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        refresh_token = request.COOKIES.get(refresh_cookie_name)

        if not refresh_token:
            response = Response(
                {"detail": "No refresh token found."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        self.enforce_csrf(request)

        try:
            refresh = RefreshToken(refresh_token)

            user_id = refresh[api_settings.USER_ID_CLAIM]
            user = User.all_objects.get(pk=user_id)

        except (TokenError, User.DoesNotExist, KeyError):
            response = Response(
                {
                    "detail": (
                        "Refresh token is invalid or account is unavailable."
                    )
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        if (
            user.deleted_at is not None
            or not user.is_active
            or user.status != User.AccountStatus.ACTIVE
        ):
            response = Response(
                {"detail": "Your account is not active."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        try:
            access_token, new_refresh_token, session = (
                rotate_session_tokens(
                    user=user,
                    refresh_token=refresh_token,
                )
            )

        except SessionError:
            response = Response(
                {
                    "detail": (
                        "Refresh token is invalid, expired, or blacklisted."
                    )
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        response = Response(
            {"detail": "Access token refreshed successfully."},
            status=status.HTTP_200_OK,
        )

        TokenCookieManager.set_access_cookie(
            response,
            access_token,
        )
        TokenCookieManager.set_refresh_cookie(
            response,
            new_refresh_token,
        )

        return response


class UserChangePasswordView(APIView):
    """
    Change the authenticated user's password.
    All existing refresh tokens are revoked after a successful change.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def enforce_csrf(self, request):
        check = CSRFCheck(lambda request: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})

        if reason:
            raise PermissionDenied(f"CSRF Failed: {reason}")

    @extend_schema(
        request=UserChangePasswordSerializer,
        responses={
            200: OpenApiResponse(
                description="Password changed successfully."
            ),
            400: OpenApiResponse(
                description="Password validation failed."
            ),
            401: OpenApiResponse(
                description="Authentication failed."
            ),
            403: OpenApiResponse(
                description="CSRF validation failed."
            ),
        },
    )
    def post(self, request):
        self.enforce_csrf(request)

        user = request.user

        if (
            user.deleted_at is not None
            or not user.is_active
            or user.status != User.AccountStatus.ACTIVE
        ):
            response = Response(
                {"detail": "Your account is not active."},
                status=status.HTTP_403_FORBIDDEN,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        serializer = UserChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                user.set_password(
                    serializer.validated_data["new_password"]
                )
                user.save(update_fields=["password"])

                create_outbox_event(
                    event_type="users.password_changed",
                    aggregate_type="user",
                    aggregate_id=user.id,
                    payload={
                        "email": user.email,
                    },
                )

                revoke_all_user_sessions(user)
            response = Response(
                {
                    "detail": (
                        "Password changed successfully. "
                        "Please log in again."
                    )
                },
                status=status.HTTP_200_OK,
            )

            TokenCookieManager.delete_tokens_cookies(response)

            return response

        except Exception:
            logger.exception(
                "Unexpected error while changing user password."
            )
            raise


class ForgotPasswordView(APIView):
    """
    Request a password reset link.

    A generic response is returned regardless of account eligibility
    to prevent account enumeration.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordThrottle]

    @extend_schema(
        request=ForgotPasswordSerializer,
        responses={
            200: OpenApiResponse(
                description="If the account is eligible, a password reset email will be sent."
            ),
            400: OpenApiResponse(
                description="Invalid request data."
            ),
            429: OpenApiResponse(
                description="Too many requests."
            ),
        },
    )
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        generic_response = Response(
            {
                "detail": (
                    "If the account is eligible, "
                    "a password reset email will be sent."
                )
            },
            status=status.HTTP_200_OK,
        )

        try:
            with transaction.atomic():
                try:
                    user = (
                        User.all_objects
                        .select_for_update()
                        .get(email=email)
                    )
                except User.DoesNotExist:
                    return generic_response

                if (
                    user.deleted_at is not None
                    or not user.is_active
                    or user.status not in (
                        User.AccountStatus.ACTIVE,
                        User.AccountStatus.PENDING_VERIFICATION,
                    )
                ):
                    return generic_response

                reset_token = generate_password_reset_token(user.id)

                create_outbox_event(
                    event_type="users.password_reset_requested",
                    aggregate_type="user",
                    aggregate_id=user.id,
                    payload={
                        "email": user.email,
                        "reset_token": reset_token,
                    },
                )

        except Exception:
            logger.exception(
                "Failed to create password reset event."
            )
            raise

        return generic_response


class ResetPasswordView(APIView):
    """
    Reset a user's password using a signed, single-use token.

    Eligible accounts:
    - ACTIVE
    - PENDING_VERIFICATION

    The account status and email verification timestamp remain unchanged.
    All existing refresh tokens are revoked after a successful reset.
    No authentication cookies or JWT tokens are issued.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ResetPasswordThrottle]

    @extend_schema(
        request=ResetPasswordSerializer,
        responses={
            200: OpenApiResponse(
                description="Password reset successfully."
            ),
            400: OpenApiResponse(
                description="Invalid or expired token or invalid password."
            ),
            429: OpenApiResponse(
                description="Too many requests."
            ),
        },
    )
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]

        user_id = get_password_reset_user_id(token)

        if user_id is None:
            raise ValidationError({
                "token": "Invalid or expired password reset token."
            })

        try:
            with transaction.atomic():
                try:
                    user = (
                        User.all_objects
                        .select_for_update()
                        .get(pk=user_id)
                    )
                except User.DoesNotExist:
                    raise ValidationError({
                        "token": "Invalid or expired password reset token."
                    })

                if (
                    user.deleted_at is not None
                    or not user.is_active
                    or user.status not in (
                        User.AccountStatus.ACTIVE,
                        User.AccountStatus.PENDING_VERIFICATION,
                    )
                ):
                    raise ValidationError({
                        "token": "Invalid or expired password reset token."
                    })

                try:
                    validate_password(
                        new_password,
                        user=user,
                    )
                except DjangoValidationError as exc:
                    raise ValidationError({
                        "new_password": list(exc.messages)
                    })

                if user.check_password(new_password):
                    raise ValidationError({
                        "new_password": (
                            "New password must be different from "
                            "the current password."
                        )
                    })

                consumed_user_id = consume_password_reset_token(token)

                if consumed_user_id != user.id:
                    raise ValidationError({
                        "token": "Invalid or expired password reset token."
                    })

                user.set_password(new_password)
                user.save(update_fields=["password"])

                create_outbox_event(
                    event_type="users.password_changed",
                    aggregate_type="user",
                    aggregate_id=user.id,
                    payload={
                        "email": user.email,
                    },
                )

                revoke_all_user_sessions(user)

        except ValidationError:
            raise

        except Exception:
            logger.exception(
                "Unexpected error while resetting user password."
            )
            raise

        response = Response(
            {
                "detail": (
                    "Password reset successfully. "
                    "Please log in with your new password."
                )
            },
            status=status.HTTP_200_OK,
        )

        TokenCookieManager.delete_tokens_cookies(response)

        return response


class UserSessionListView(APIView):
    """
    List all active sessions belonging to the authenticated user.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: UserSessionSerializer(many=True),
            401: OpenApiResponse(
                description="Authentication failed."
            ),
        },
    )
    def get(self, request):
        sessions = UserSession.objects.filter(
            user=request.user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )

        serializer = UserSessionSerializer(
            sessions,
            many=True,
            context={"request": request},
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class UserSessionRevokeView(APIView):
    """
    Revoke one session belonging to the authenticated user.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            204: OpenApiResponse(
                description="Session revoked successfully."
            ),
            401: OpenApiResponse(
                description="Authentication failed."
            ),
            404: OpenApiResponse(
                description="Session not found."
            ),
        },
    )
    def delete(self, request, session_id):
        revoked = revoke_session(
            session_id=session_id,
            user=request.user,
        )

        if not revoked:
            return Response(
                {"detail": "Session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class UserLogoutAllSessionsView(APIView):
    """
    Revoke all sessions belonging to the authenticated user.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: OpenApiResponse(
                description="All sessions revoked successfully."
            ),
            401: OpenApiResponse(
                description="Authentication failed."
            ),
        },
    )
    def post(self, request):
        revoked_count = revoke_all_user_sessions(request.user)

        response = Response(
            {
                "detail": "All sessions have been revoked successfully.",
                "revoked_count": revoked_count,
            },
            status=status.HTTP_200_OK,
        )

        TokenCookieManager.delete_tokens_cookies(response)

        return response