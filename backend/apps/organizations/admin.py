from django.contrib import admin

from .models import Organization, OrganizationMembership
from apps.users.admin_site import admin_site

class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 0
    show_change_link = True

    fields = (
        "user",
        "role",
        "status",
        "joined_at",
        "created_at",
    )

    readonly_fields = (
        "joined_at",
        "created_at",
    )

    autocomplete_fields = ("user",)


class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "created_by",
        "membership_policy",
        "created_at",
        "is_deleted",
    )

    list_filter = (
        "membership_policy",
        "deleted_at",
        "created_at",
    )

    search_fields = (
        "name",
        "slug",
        "created_by__email",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
    )

    prepopulated_fields = {}

    ordering = ("-created_at",)

    inlines = (OrganizationMembershipInline,)

    list_per_page = 25

    def get_queryset(self, request):
        return Organization.all_objects.get_queryset()


class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "user",
        "role",
        "status",
        "joined_at",
        "created_at",
    )

    list_filter = (
        "role",
        "status",
        "created_at",
    )

    search_fields = (
        "organization__name",
        "user__email",
    )

    readonly_fields = (
        "joined_at",
        "created_at",
    )

    autocomplete_fields = (
        "organization",
        "user",
    )

    ordering = ("-joined_at",)

    list_per_page = 50


admin_site.register(Organization, OrganizationAdmin)
admin_site.register(OrganizationMembership, OrganizationMembershipAdmin)
