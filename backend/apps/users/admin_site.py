from django.contrib.admin import AdminSite


class SuperuserAdminSite(AdminSite):
    """Allow only active superusers to access Django Admin."""

    def has_permission(self, request):
        return (
            request.user.is_active
            and request.user.is_superuser
        )

admin_site = SuperuserAdminSite(name="admin")