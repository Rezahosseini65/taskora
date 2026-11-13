import logging

from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.conf import settings
from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.settings import api_settings
from rest_framework.exceptions import ValidationError

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import User
from apps.outbox.services import create_outbox_event
from apps.users.services import otp, block
from common.authentication.jwt import CookieJWTAuthentication
from common.utils.services import (
    TokenCookieManager,
    generate_access_refresh_tokens,
)
from .serializers import (
    UserRegisterSerializer,
    EmailVerificationSerializer,
    ResendVerificationEmailSerializer,
    UserLoginSerializer,
)
from .throttles import (
    UserRegisterThrottle,
    UserLoginThrottle,
    EmailVerificationThrottle,
    EmailVerificationResendThrottle,
)
from apps.users.services.verification import (
    generate_verification_token,
    verify_verification_token,
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

        access_token, refresh_token = generate_access_refresh_tokens(
            user=user,
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
            access_token, refresh_token = generate_access_refresh_tokens(
                user=user
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
        refresh_cookie_name = settings.SIMPLE_JWT["AUTH_COOKIE_REFRESH"]
        refresh_token = request.COOKIES.get(refresh_cookie_name)

        # Revoke the refresh token when one is available.
        if refresh_token:
            TokenCookieManager.blacklist_refresh_token(refresh_token)

        response = Response(
            {"detail": "Logout successful."},
            status=status.HTTP_200_OK,
        )

        # Always remove both authentication cookies.
        TokenCookieManager.delete_tokens_cookies(response)

        return response


class RefreshAccessTokenView(APIView):
    """
    Refresh the access token using the refresh token stored
    in an HTTP-only cookie.
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

        # Check whether the refresh cookie exists.
        if not refresh_token:
            response = Response(
                {"detail": "No refresh token found."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        # Enforce CSRF protection for cookie-based authentication.
        self.enforce_csrf(request)

        # Validate the refresh token and retrieve its user.
        try:
            refresh = RefreshToken(refresh_token)

            user_id_claim = api_settings.USER_ID_CLAIM
            user_id = refresh[user_id_claim]

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

        # Check whether the user account is eligible for token refresh.
        if (
            user.deleted_at is not None
            or not user.is_active
            or user.status in (
                User.AccountStatus.SUSPENDED,
                User.AccountStatus.DEACTIVATED,
            )
        ):
            response = Response(
                {"detail": "Your account is not active."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            TokenCookieManager.delete_tokens_cookies(response)
            return response

        # Validate and rotate the refresh token.
        serializer = TokenRefreshSerializer(
            data={"refresh": refresh_token}
        )

        try:
            serializer.is_valid(raise_exception=True)

        except TokenError:
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

        token_data = serializer.validated_data

        response = Response(
            {"detail": "Access token refreshed successfully."},
            status=status.HTTP_200_OK,
        )

        TokenCookieManager.set_access_cookie(
            response,
            token_data["access"],
        )

        if "refresh" in token_data:
            TokenCookieManager.set_refresh_cookie(
                response,
                token_data["refresh"],
            )

        return response