from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from .models import User
from .validators import validate_strong_password


class UserRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        validators=[validate_strong_password],
        style={"input_type": "password"}
    )
    confirm_password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        style={"input_type": "password"}
    )

    def validate_email(self, value) -> str:
        """
        Checks if the email already exists in the database.
        """

        value = value.strip().lower()
        
        if User.all_objects.filter(email=value).exists():
            raise serializers.ValidationError(
                _("This email address is already in use. Please use another one."),
                code='email_already_exists'
            )

        return value

    def validate(self, data: dict) -> dict:
        """
        Validate password confirmation and password similarity.
        """
        password = data.get("password")
        confirm_password = data.get("confirm_password")

        if password != confirm_password:
            raise serializers.ValidationError({
                "confirm_password": _("Passwords do not match.")
            })

        user = User(email=data.get("email"))

        try:
            validate_password(password, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({
                "password": list(exc.messages)
            })

        return data


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        required=True,
        style={'input_type':'password'},
        write_only=True
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs) -> dict:
        email = attrs.get("email")
        password = attrs.get("password")

        user = authenticate(
            request=self.context.get("request"),
            email=email,
            password=password,
        )

        if not user:
            raise serializers.ValidationError(
                _("Your email or password is incorrect, please try again.")
            )

        if user.deleted_at is not None or not user.is_active:
            raise serializers.ValidationError(
                _("Your email or password is incorrect, please try again.")
            )

        if user.status == User.AccountStatus.SUSPENDED:
            raise serializers.ValidationError(
                _("Your account is suspended.")
            )

        if user.status == User.AccountStatus.DEACTIVATED:
            raise serializers.ValidationError(
                _("Your email or password is incorrect, please try again.")
            )

        attrs["user"] = user
        return attrs