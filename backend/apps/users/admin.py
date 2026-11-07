
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group, Permission
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from django_celery_results.models import (
    ChordCounter,
    GroupResult,
    TaskResult,
)

from .models import User
from .admin_site import admin_site


class CustomUserCreationForm(UserCreationForm):
    """Form for creating users with email authentication."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "email",
            "status",
            "is_staff",
            "is_active",
        )


class CustomUserChangeForm(UserChangeForm):
    """Form for updating existing users."""

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


class CustomUserAdmin(UserAdmin):
    """Admin configuration for the custom User model."""

    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User

    list_display = (
        "email",
        "status",
        "email_verified_at",
        "is_staff",
        "is_active",
        "deleted_at",
        "created_at",
    )

    list_filter = (
        "status",
        "is_staff",
        "is_superuser",
        "is_active",
        "deleted_at",
    )

    search_fields = ("email",)
    ordering = ("-created_at",)

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "last_login",
    )

    fieldsets = (
        (
            "Account Information",
            {
                "fields": (
                    "id",
                    "email",
                    "password",
                    "status",
                    "email_verified_at",
                    "locale",
                    "timezone",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Account Lifecycle",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "deleted_at",
                    "last_login",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            "Account Information",
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "status",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )

    actions = (
        "soft_delete_users",
        "restore_users",
    )

    def get_queryset(self, request):
        """Include soft-deleted users in the admin panel."""
        return self.model.all_objects.get_queryset()

    @admin.action(description="Soft-delete selected users")
    def soft_delete_users(self, request, queryset):
        """Soft-delete selected active records."""
        updated = queryset.soft_delete()

        self.message_user(
            request,
            f"{updated} user(s) successfully soft-deleted.",
            messages.SUCCESS,
        )

    @admin.action(description="Restore selected users")
    def restore_users(self, request, queryset):
        """Restore selected soft-deleted records."""
        updated = queryset.restore()

        self.message_user(
            request,
            f"{updated} user(s) successfully restored.",
            messages.SUCCESS,
        )

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    
admin_site.register(User, CustomUserAdmin)

# Django Authentication
admin_site.register(Group)
admin_site.register(Permission)

# Celery Beat
admin_site.register(ClockedSchedule)
admin_site.register(CrontabSchedule)
admin_site.register(IntervalSchedule)
admin_site.register(PeriodicTask)
admin_site.register(SolarSchedule)

# Celery Results
admin_site.register(ChordCounter)
admin_site.register(GroupResult)
admin_site.register(TaskResult)