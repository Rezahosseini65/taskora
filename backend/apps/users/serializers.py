from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from .models import User, UserProfile, UserSession
from .validators import validate_strong_password
from apps.users.services.verification import generate_verification_token

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


class EmailVerificationSerializer(serializers.Serializer):
    verification_token = serializers.CharField(
        required=True,
        trim_whitespace=False,
    )
    verification_code = serializers.CharField(
        required=True,
        min_length=6,
        max_length=6,
        trim_whitespace=False,
    )

    def validate_verification_code(self, value) -> str:
        if not value.isdigit():
            raise serializers.ValidationError(
                _("Verification code must contain only digits.")
            )

        return value


class ResendVerificationEmailSerializer(serializers.Serializer):
    verification_token = serializers.CharField(
        required=True,
        trim_whitespace=False,
    )


class UserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        required=True,
        style={"input_type": "password"},
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
                _("Your email or password is incorrect, please try again."),
                code="invalid_credentials",
            )

        if user.deleted_at is not None or not user.is_active:
            raise serializers.ValidationError(
                _("Your email or password is incorrect, please try again."),
                code="invalid_credentials",
            )

        if user.status == User.AccountStatus.PENDING_VERIFICATION:
            verification_token = generate_verification_token(
                                user_id=user.id
                            )
            raise serializers.ValidationError(
                {
                    "code": "email_not_verified",
                    "detail": _(
                        "Please verify your email address before logging in."
                    ),
                    "verification_required": True,
                    "verification_token":verification_token,
                }
            )

        if user.status == User.AccountStatus.SUSPENDED:
            raise serializers.ValidationError(
                _("Your account is suspended."),
                code="account_suspended",
            )

        if user.status != User.AccountStatus.ACTIVE:
            raise serializers.ValidationError(
                _("Your email or password is incorrect, please try again."),
                code="invalid_credentials",
            )

        attrs["user"] = user
        return attrs


class UserChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        write_only=True,
        validators=[validate_strong_password],
        style={"input_type": "password"},
    )
    confirm_new_password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_current_password(self, value):
        user = self.context["request"].user

        if not user.check_password(value):
            raise serializers.ValidationError(
                _("Your current password is incorrect."),
                code="incorrect_current_password",
            )

        return value

    def validate(self, attrs):
        user = self.context["request"].user

        new_password = attrs["new_password"]
        confirm_new_password = attrs["confirm_new_password"]

        if new_password != confirm_new_password:
            raise serializers.ValidationError({
                "confirm_new_password": _(
                    "New passwords do not match."
                )
            })

        if user.check_password(new_password):
            raise serializers.ValidationError({
                "new_password": _(
                    "New password must be different from your current password."
                )
            })

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({
                "new_password": list(exc.messages)
            })

        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.strip().lower()


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(
        required=True,
        trim_whitespace=False,
        write_only=True,
    )
    new_password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        write_only=True,
        validators=[validate_strong_password],
        style={"input_type": "password"},
    )
    confirm_new_password = serializers.CharField(
        required=True,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        new_password = attrs["new_password"]
        confirm_new_password = attrs["confirm_new_password"]

        if new_password != confirm_new_password:
            raise serializers.ValidationError({
                "confirm_new_password": _("New passwords do not match.")
            })

        return attrs


class UserSessionSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            "id",
            "is_current",
            "created_at",
            "last_activity_at",
            "expires_at",
            "ip_address",
            "user_agent",
        ]
        read_only_fields = fields

    def get_is_current(self, obj) -> bool:
        request = self.context.get("request")

        if request is None:
            return False

        current_session_id = getattr(
            request,
            "session_id",
            None,
        )

        return str(obj.id) == str(current_session_id)


class UserMeSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(
        source="profile.first_name",
        max_length=150,
        required=False,
        allow_blank=True,
    )
    last_name = serializers.CharField(
        source="profile.last_name",
        max_length=150,
        required=False,
        allow_blank=True,
    )
    display_name = serializers.CharField(
        source="profile.display_name",
        max_length=150,
        required=False,
        allow_blank=True,
    )
    avatar = serializers.ImageField(
        source="profile.avatar",
        required=False,
        allow_null=True,
    )
    bio = serializers.CharField(
        source="profile.bio",
        required=False,
        allow_blank=True,
    )
    phone_number = serializers.CharField(
        source="profile.phone_number",
        max_length=20,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "locale",
            "timezone",
            "first_name",
            "last_name",
            "display_name",
            "avatar",
            "bio",
            "phone_number",
        ]
        read_only_fields = ["id", "email"]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", {})

        new_avatar_name = None
        avatar_storage = None
        old_avatar_name = None

        try:
            with transaction.atomic():
                if profile_data:
                    profile, _ = UserProfile.objects.get_or_create(
                        user=instance
                    )

                    old_avatar_name = (
                        profile.avatar.name if profile.avatar else None
                    )
                    avatar_storage = profile.avatar.storage

                    for attr, value in profile_data.items():
                        setattr(profile, attr, value)

                    profile.save()

                    new_avatar_name = (
                        profile.avatar.name if profile.avatar else None
                    )

                    if (
                        "avatar" in profile_data
                        and old_avatar_name
                        and old_avatar_name != new_avatar_name
                    ):
                        transaction.on_commit(
                            lambda storage=avatar_storage, name=old_avatar_name:
                                storage.delete(name)
                        )

                for attr, value in validated_data.items():
                    setattr(instance, attr, value)

                if validated_data:
                    instance.save()

        except Exception:
            if (
                new_avatar_name
                and new_avatar_name != old_avatar_name
                and avatar_storage
            ):
                avatar_storage.delete(new_avatar_name)

            raise

        return instance

    def validate_avatar(self, value):
        if value is None:
            return None

        max_size = 5 * 1024 * 1024  # 5 MB
        allowed_formats = {"JPEG", "PNG", "WEBP"}
        max_dimensions = (4096, 4096)

        if value.size > max_size:
            raise serializers.ValidationError(
                _("Avatar file size must not exceed 5 MB.")
            )

        from PIL import Image, UnidentifiedImageError

        try:
            image = Image.open(value)
            image.verify()

            if image.format not in allowed_formats:
                raise serializers.ValidationError(
                    _("Only JPEG, PNG, and WebP images are allowed.")
                )

            value.seek(0)
            image = Image.open(value)

            if image.width > max_dimensions[0] or image.height > max_dimensions[1]:
                raise serializers.ValidationError(
                    _("Avatar dimensions must not exceed 4096x4096 pixels.")
                )

        except (UnidentifiedImageError, OSError, SyntaxError):
            raise serializers.ValidationError(
                _("The uploaded file is not a valid image.")
            )

        finally:
            value.seek(0)

        return value

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError(
                _("Enter a valid timezone.")
            )

        return value
