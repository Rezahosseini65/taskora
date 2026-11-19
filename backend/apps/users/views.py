import logging
from uuid import UUID

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils import timezone

from rest_framework import status
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from drf_spectacular.utils import OpenApiResponse, extend_schema

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

from .models import User, UserProfile, UserSession
from .serializers import (
    EmailVerificationSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    ResendVerificationEmailSerializer,
    UserChangePasswordSerializer,
    UserLoginSerializer,
    UserMeSerializer,
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


def _detail_response(example: str, description: str) -> OpenApiResponse:
    """
    Build a documented JSON response containing a single detail field.
    """
    return OpenApiResponse(
        response={
            "type": "object",
            "properties": {
                "detail": {
                    "type": "string",
                    "example": example,
                },
            },
            "required": ["detail"],
        },
        description=description,
    )


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
    Register a user and create an email verification event.

    User creation and Outbox event creation are performed
    within a single database transaction.
    """

    authentication_classes = []
    parser_classes = [JSONParser]
    throttle_classes = [UserRegisterThrottle]

    @extend_schema(
        operation_id="auth_register",
        summary="Register a new user",
        description=(
            "Create a user account and an email verification Outbox event. "
            "The account remains pending verification until the email "
            "verification process is completed. "
            "The verification token is returned in the response."
        ),
        request=UserRegisterSerializer,
        responses={
            201: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "detail": {
                            "type": "string",
                            "example": (
                                "Registration successful. "
                                "Please verify your email address."
                            ),
                        },
                        "verification_token": {
                            "type": "string",
                        },
                    },
                    "required": ["detail", "verification_token"],
                },
                description=(
                    "Registration successful. Email verification required."
                ),
            ),
            400: OpenApiResponse(
                description=(
                    "Invalid registration data or email address already in use."
                ),
            ),
            429: OpenApiResponse(
                description="Too many registration requests.",
            ),
        },
        auth=[],
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
    Verify a user's email address using a signed token and one-time code.

    On success, activate the account, create its profile, and issue
    access and refresh JWT tokens through HttpOnly cookies.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]
    throttle_classes = [EmailVerificationThrottle]

    @extend_schema(
        operation_id="auth_verify_email",
        summary="Verify email address",
        description=(
            "Verify a user's email address using the signed verification "
            "token received during registration and a one-time verification "
            "code. On success, the account is activated, a profile is created, "
            "and access and refresh JWT tokens are issued through HttpOnly "
            "cookies."
        ),
        request=EmailVerificationSerializer,
        responses={
            200: _detail_response(
                "Email verified successfully.",
                "Email verified and account activated.",
            ),
            400: OpenApiResponse(
                description=(
                    "Invalid or expired verification token/code, "
                    "or account does not require verification."
                ),
            ),
            429: _detail_response(
                "Too many failed attempts. Please try again later.",
                "Too many failed verification attempts.",
            ),
        },
        auth=[],
    )
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

            UserProfile.objects.get_or_create(user=user)

        access_token, refresh_token, session = create_session_tokens(
            user=user,
            request=request,
        )

        response = Response(
            {"detail": "Email verified successfully."},
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
    parser_classes = [JSONParser]
    throttle_classes = [EmailVerificationResendThrottle]

    @extend_schema(
        operation_id="auth_resend_verification_email",
        summary="Resend verification email",
        description=(
            "Request a new email verification code using the signed "
            "verification token received during registration. A generic "
            "response is returned regardless of account eligibility to "
            "prevent account enumeration. The request may be subject to "
            "a resend cooldown."
        ),
        request=ResendVerificationEmailSerializer,
        responses={
            200: _detail_response(
                "If the account is eligible, a verification email will be sent.",
                "Generic response returned regardless of account eligibility.",
            ),
            400: OpenApiResponse(
                description="Invalid request data.",
            ),
            429: OpenApiResponse(
                description="Too many resend requests.",
            ),
        },
        auth=[],
    )
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
    """Authenticate a user and issue JWT tokens through HttpOnly cookies."""

    authentication_classes = []
    parser_classes = [JSONParser]
    throttle_classes = [UserLoginThrottle]

    @extend_schema(
        operation_id="auth_login",
        summary="Log in",
        description=(
            "Authenticate using email and password. On success, access and "
            "refresh JWT tokens are issued through HttpOnly cookies. "
            "Tokens are not included in the JSON response."
        ),
        request=UserLoginSerializer,
        responses={
            200: _detail_response(
                "Login successful",
                "Login successful. Access and refresh tokens are set in HttpOnly cookies.",
            ),
            400: OpenApiResponse(
                description="Invalid credentials or account cannot log in.",
            ),
            429: OpenApiResponse(
                description="Too many login attempts.",
            ),
        },
        auth=[],
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
    """Set the CSRF cookie and return a confirmation response."""

    authentication_classes = []
    permission_classes = []
    parser_classes = [JSONParser]
    throttle_classes = []

    @extend_schema(
        operation_id="auth_csrf_token",
        summary="Get CSRF token",
        description=(
            "Sets the CSRF cookie and returns a confirmation message. "
            "The CSRF cookie is used by the client for subsequent "
            "state-changing requests."
        ),
        request=None,
        responses={
            200: _detail_response(
                "CSRF cookie set successfully.",
                "CSRF cookie was set successfully.",
            ),
        },
        auth=[],
    )
    def get(self, request):
        get_token(request)

        return Response(
            {"detail": "CSRF cookie set successfully."},
            status=status.HTTP_200_OK,
        )


class UserLogoutView(APIView):
    """Revoke the current session and delete authentication cookies."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @extend_schema(
        operation_id="auth_logout",
        summary="Log out",
        description=(
            "Revoke the authenticated user's current session and delete "
            "the access and refresh token cookies."
        ),
        request=None,
        responses={
            200: _detail_response(
                "Logout successful.",
                "Logout successful and authentication cookies deleted.",
            ),
            401: OpenApiResponse(
                description="Authentication failed.",
            ),
        },
    )
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
    stored in an HttpOnly cookie.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def enforce_csrf(self, request):
        check = CSRFCheck(lambda request: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})

        if reason:
            raise PermissionDenied(f"CSRF Failed: {reason}")

    @extend_schema(
        operation_id="auth_refresh",
        summary="Refresh authentication tokens",
        description=(
            "Rotate the access and refresh tokens using the refresh token "
            "stored in an HttpOnly cookie. A valid CSRF token is required. "
            "New tokens are returned through HttpOnly cookies, not in the "
            "JSON response."
        ),
        request=None,
        responses={
            200: _detail_response(
                "Access token refreshed successfully.",
                "Tokens refreshed successfully and authentication cookies updated.",
            ),
            401: _detail_response(
                "Refresh token is invalid or account is unavailable.",
                "Refresh token is missing, invalid, expired, blacklisted, or the account is unavailable.",
            ),
            403: OpenApiResponse(
                description="CSRF validation failed.",
            ),
        },
        auth=[],
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

    All existing sessions are revoked after a successful password change.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def enforce_csrf(self, request):
        check = CSRFCheck(lambda request: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})

        if reason:
            raise PermissionDenied(f"CSRF Failed: {reason}")

    @extend_schema(
        operation_id="auth_change_password",
        summary="Change password",
        description=(
            "Change the authenticated user's password. A valid CSRF token "
            "is required. All existing sessions are revoked after a "
            "successful password change, and authentication cookies are "
            "deleted. The user must log in again."
        ),
        request=UserChangePasswordSerializer,
        responses={
            200: _detail_response(
                "Password changed successfully. Please log in again.",
                "Password changed successfully. Authentication cookies deleted.",
            ),
            400: OpenApiResponse(
                description="Current password or new password validation failed.",
            ),
            401: OpenApiResponse(
                description="Authentication failed.",
            ),
            403: OpenApiResponse(
                description="CSRF validation failed or account is not active.",
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
    parser_classes = [JSONParser]
    throttle_classes = [ForgotPasswordThrottle]

    @extend_schema(
        operation_id="auth_forgot_password",
        summary="Request password reset",
        description=(
            "Request a password reset email. A generic response is returned "
            "regardless of account eligibility to prevent account enumeration."
        ),
        request=ForgotPasswordSerializer,
        responses={
            200: _detail_response(
                "If the account is eligible, a password reset email will be sent.",
                "Generic response returned regardless of account eligibility.",
            ),
            400: OpenApiResponse(
                description="Invalid request data.",
            ),
            429: OpenApiResponse(
                description="Too many password reset requests.",
            ),
        },
        auth=[],
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

    Account status and email verification timestamp remain unchanged.
    All existing sessions are revoked after a successful reset.
    No authentication cookies or JWT tokens are issued.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]
    throttle_classes = [ResetPasswordThrottle]

    @extend_schema(
        operation_id="auth_reset_password",
        summary="Reset password",
        description=(
            "Reset a user's password using a signed, single-use token. "
            "The account status and email verification timestamp remain "
            "unchanged. All existing sessions are revoked after a successful "
            "reset. The user must log in with the new password."
        ),
        request=ResetPasswordSerializer,
        responses={
            200: _detail_response(
                "Password reset successfully. Please log in with your new password.",
                "Password reset successfully. Existing sessions revoked.",
            ),
            400: OpenApiResponse(
                description="Invalid or expired token or invalid password.",
            ),
            429: OpenApiResponse(
                description="Too many password reset attempts.",
            ),
        },
        auth=[],
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


class UserMeView(APIView):
    """
    Retrieve or partially update the authenticated user's account and profile.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser]

    @extend_schema(
        operation_id="auth_me_retrieve",
        summary="Get current user",
        description=(
            "Retrieve the authenticated user's account and profile information."
        ),
        request=None,
        responses={
            200: UserMeSerializer,
            401: OpenApiResponse(
                description="Authentication failed.",
            ),
        },
    )
    def get(self, request):
        serializer = UserMeSerializer(
            instance=request.user,
            context={"request": request},
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="auth_me_update",
        summary="Update current user profile",
        description=(
            "Partially update the authenticated user's account and profile "
            "information. Only provided fields are updated. Use "
            "multipart/form-data when uploading an avatar; JSON is supported "
            "for other profile fields."
        ),
        request=UserMeSerializer,
        responses={
            200: UserMeSerializer,
            400: OpenApiResponse(
                description="Invalid profile data or avatar upload.",
            ),
            401: OpenApiResponse(
                description="Authentication failed.",
            ),
        },
    )
    def patch(self, request):
        serializer = UserMeSerializer(
            instance=request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class UserSessionListView(APIView):
    """List all active sessions belonging to the authenticated user."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @extend_schema(
        operation_id="auth_sessions_list",
        summary="List active sessions",
        description=(
            "List all non-revoked, non-expired sessions belonging "
            "to the authenticated user."
        ),
        request=None,
        responses={
            200: UserSessionSerializer(many=True),
            401: OpenApiResponse(
                description="Authentication failed.",
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
    """Revoke one session belonging to the authenticated user."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @extend_schema(
        operation_id="auth_session_revoke",
        summary="Revoke a session",
        description=(
            "Revoke a specific session belonging to the authenticated user. "
            "The session identifier must be a UUID."
        ),
        request=None,
        responses={
            204: OpenApiResponse(
                description="Session revoked successfully.",
            ),
            401: OpenApiResponse(
                description="Authentication failed.",
            ),
            404: _detail_response(
                "Session not found.",
                "The requested session does not exist or does not belong to the user.",
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
    """Revoke all sessions belonging to the authenticated user."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @extend_schema(
        operation_id="auth_logout_all_sessions",
        summary="Log out from all sessions",
        description=(
            "Revoke all sessions belonging to the authenticated user and "
            "delete the access and refresh token cookies."
        ),
        request=None,
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "detail": {
                            "type": "string",
                            "example": (
                                "All sessions have been revoked successfully."
                            ),
                        },
                        "revoked_count": {
                            "type": "integer",
                            "example": 3,
                        },
                    },
                    "required": ["detail", "revoked_count"],
                },
                description="All sessions revoked successfully.",
            ),
            401: OpenApiResponse(
                description="Authentication failed.",
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