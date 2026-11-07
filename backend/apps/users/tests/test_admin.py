from django.test import RequestFactory, TestCase
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from apps.users.admin import CustomUserCreationForm, CustomUserChangeForm
from apps.users.admin import CustomUserAdmin
from apps.users.admin_site import admin_site
from apps.users.models import User


class AdminPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPassword123",
        )

        self.staff_user = User.objects.create_user(
            email="staff@example.com",
            password="StrongPassword123",
            is_staff=True,
        )

        self.regular_user = User.objects.create_user(
            email="user@example.com",
            password="StrongPassword123",
        )

        self.user_admin = CustomUserAdmin(User, admin_site)

    def get_request(self, user):
        request = self.factory.get("/admin/")
        request.user = user
        return request

    def test_active_superuser_can_access_admin_site(self):
        request = self.get_request(self.superuser)

        self.assertTrue(admin_site.has_permission(request))

    def test_inactive_superuser_cannot_access_admin_site(self):
        self.superuser.is_active = False
        self.superuser.save(update_fields=["is_active"])

        request = self.get_request(self.superuser)

        self.assertFalse(admin_site.has_permission(request))

    def test_staff_user_cannot_access_admin_site(self):
        request = self.get_request(self.staff_user)

        self.assertFalse(admin_site.has_permission(request))

    def test_regular_user_cannot_access_admin_site(self):
        request = self.get_request(self.regular_user)

        self.assertFalse(admin_site.has_permission(request))

    def test_superuser_has_all_user_admin_permissions(self):
        request = self.get_request(self.superuser)

        self.assertTrue(self.user_admin.has_view_permission(request))
        self.assertTrue(self.user_admin.has_add_permission(request))
        self.assertTrue(self.user_admin.has_change_permission(request))
        self.assertTrue(self.user_admin.has_delete_permission(request))

    def test_staff_user_has_no_user_admin_permissions(self):
        request = self.get_request(self.staff_user)

        self.assertFalse(self.user_admin.has_view_permission(request))
        self.assertFalse(self.user_admin.has_add_permission(request))
        self.assertFalse(self.user_admin.has_change_permission(request))
        self.assertFalse(self.user_admin.has_delete_permission(request))

    def test_regular_user_has_no_user_admin_permissions(self):
        request = self.get_request(self.regular_user)

        self.assertFalse(self.user_admin.has_view_permission(request))
        self.assertFalse(self.user_admin.has_add_permission(request))
        self.assertFalse(self.user_admin.has_change_permission(request))
        self.assertFalse(self.user_admin.has_delete_permission(request))



class CustomUserAdminQuerySetTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPassword123",
        )

        self.user_admin = CustomUserAdmin(User, admin_site)

    def test_admin_queryset_includes_alive_and_deleted_users(self):
        alive_user = User.objects.create_user(
            email="alive@example.com",
            password="StrongPassword123",
        )

        deleted_user = User.objects.create_user(
            email="deleted@example.com",
            password="StrongPassword123",
        )
        deleted_user.soft_delete()

        request = self.factory.get("/admin/")
        request.user = self.superuser

        queryset = self.user_admin.get_queryset(request)

        self.assertIn(alive_user, queryset)
        self.assertIn(deleted_user, queryset)

    def test_soft_delete_users_action(self):
        user = User.objects.create_user(
            email="delete@example.com",
            password="StrongPassword123",
        )

        request = self.factory.post("/admin/")
        request.user = self.superuser
        request.session = SessionStore()
        request._messages = FallbackStorage(request)

        queryset = User.all_objects.filter(pk=user.pk)

        self.user_admin.soft_delete_users(request, queryset)

        user.refresh_from_db()

        self.assertIsNotNone(user.deleted_at)

    def test_restore_users_action(self):
        user = User.objects.create_user(
            email="restore@example.com",
            password="StrongPassword123",
        )
        user.soft_delete()

        request = self.factory.post("/admin/")
        request.user = self.superuser
        request.session = SessionStore()
        request._messages = FallbackStorage(request)

        queryset = User.all_objects.filter(pk=user.pk)

        self.user_admin.restore_users(request, queryset)

        user.refresh_from_db()

        self.assertIsNone(user.deleted_at)


class CustomUserAdminFormTests(TestCase):
    def test_creation_form_contains_expected_fields(self):
        form = CustomUserCreationForm()

        self.assertIn("email", form.fields)
        self.assertIn("password1", form.fields)
        self.assertIn("password2", form.fields)

    def test_creation_form_creates_user_with_valid_data(self):
        form = CustomUserCreationForm(
            data={
                "email": "newadmin@example.com",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
                "status": User.AccountStatus.ACTIVE,
                "is_staff": True,
                "is_active": True,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

        user = form.save()

        self.assertEqual(user.email, "newadmin@example.com")
        self.assertTrue(user.check_password("StrongPassword123!"))
        self.assertTrue(user.is_staff)
        self.assertEqual(user.status, User.AccountStatus.ACTIVE)

    def test_creation_form_rejects_password_mismatch(self):
        form = CustomUserCreationForm(
            data={
                "email": "newadmin@example.com",
                "password1": "StrongPassword123!",
                "password2": "DifferentPassword123!",
                "status": User.AccountStatus.ACTIVE,
                "is_staff": True,
                "is_active": True,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_change_form_contains_password_hash_field(self):
        user = User.objects.create_user(
            email="existing@example.com",
            password="StrongPassword123!",
        )

        form = CustomUserChangeForm(instance=user)

        self.assertIn("password", form.fields)
        self.assertIsInstance(
            form.fields["password"],
            ReadOnlyPasswordHashField,
        )

    def test_change_form_updates_user_fields(self):
        user = User.objects.create_user(
            email="existing@example.com",
            password="StrongPassword123!",
        )

        form = CustomUserChangeForm(
            data={
                "email": "updated@example.com",
                "status": User.AccountStatus.SUSPENDED,
                "locale": "fa",
                "timezone": "Asia/Tehran",
                "is_active": True,
                "is_staff": False,
                "is_superuser": False,
                "groups": [],
                "user_permissions": [],
            },
            instance=user,
        )

        self.assertTrue(form.is_valid(), form.errors)

        updated_user = form.save()

        self.assertEqual(updated_user.email, "updated@example.com")
        self.assertEqual(
            updated_user.status,
            User.AccountStatus.SUSPENDED,
        )
        self.assertEqual(updated_user.locale, "fa")
        self.assertEqual(updated_user.timezone, "Asia/Tehran")
        self.assertTrue(updated_user.check_password("StrongPassword123!"))