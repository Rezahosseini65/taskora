import logging

from django.db import IntegrityError, transaction

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse

from common.utils.services import (
    TokenCookieManager,
    generate_access_refresh_tokens,
)

from .models import User
from .serializers import UserRegisterSerializer
from .throttles import UserRegisterThrottle


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
