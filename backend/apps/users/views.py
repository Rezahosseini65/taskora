import logging

from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.conf import settings

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

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import User
from common.authentication.jwt import CookieJWTAuthentication
from common.utils.services import (
    TokenCookieManager,
    generate_access_refresh_tokens,
)
from .serializers import (
    UserRegisterSerializer,
    UserLoginSerializer,
)
from .throttles import (
    UserRegisterThrottle,
    UserLoginThrottle,
)


logger = logging.getLogger(__name__)


class UserRegisterView(APIView):
    """
    Handle user registration and issue JWT tokens.

    The user creation and token generation process are performed
    within a single database transaction.
    """

    throttle_classes = [UserRegisterThrottle]
    authentication_classes = []

    @extend_schema(
        request=UserRegisterSerializer,
        responses={
            201: OpenApiResponse(
                description="Registration successful"
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

                access_token, refresh_token = (
                    generate_access_refresh_tokens(user=user)
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

        response = Response(
            {"detail": "Registration successful"},
            status=status.HTTP_201_CREATED,
        )

        TokenCookieManager.set_access_cookie(response, access_token)
        TokenCookieManager.set_refresh_cookie(response, refresh_token)

        return response


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