import os
import tempfile
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.management.base import CommandError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.users.models import User, UserProfile


class CleanupOrphanedAvatarsTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)

        self.settings_override = override_settings(
            MEDIA_ROOT=self.temp_media.name,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.storage = UserProfile._meta.get_field("avatar").storage
        self.directory = "profiles/avatars"

    def create_avatar_file(self, name, content=b"test-image"):
        
        path = f"{self.directory}/{name}"
        saved_name = self.storage.save(
            path,
            ContentFile(content),
        )
        return saved_name

    def set_file_age(self, name, hours):
        path = self.storage.path(name)
        old_time = (timezone.now() - timedelta(hours=hours)).timestamp()
        os.utime(path, (old_time, old_time))

    def test_dry_run_does_not_delete_orphaned_file(self):
        filename = self.create_avatar_file("orphan.png")
        self.set_file_age(filename, 48)

        call_command("cleanup_orphaned_avatars")

        self.assertTrue(self.storage.exists(filename))

    def test_delete_removes_old_orphaned_file(self):
        filename = self.create_avatar_file("orphan.png")
        self.set_file_age(filename, 48)

        call_command("cleanup_orphaned_avatars", delete=True)

        self.assertFalse(self.storage.exists(filename))

    def test_recent_orphaned_file_is_preserved(self):
        filename = self.create_avatar_file("recent.png")
        self.set_file_age(filename, 2)

        call_command("cleanup_orphaned_avatars", delete=True)

        self.assertTrue(self.storage.exists(filename))

    def test_referenced_avatar_is_preserved(self):
        filename = self.create_avatar_file("used.png")
        self.set_file_age(filename, 48)

        user = User.objects.create_user(
            email="avatar-test@example.com",
            password="StrongPassword123!",
        )
        UserProfile.objects.create(user=user, avatar=filename)

        call_command("cleanup_orphaned_avatars", delete=True)

        self.assertTrue(self.storage.exists(filename))

    def test_invalid_older_than_value_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "cleanup_orphaned_avatars",
                older_than=0,
            )
