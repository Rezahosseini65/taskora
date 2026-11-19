
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.users.models import UserProfile


class Command(BaseCommand):
    help = "Find and optionally delete orphaned profile avatar files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Actually delete orphaned files. Without this flag, only report them.",
        )
        parser.add_argument(
            "--older-than",
            type=int,
            default=24,
            help="Only consider files older than this many hours (default: 24).",
        )

    def handle(self, *args, **options):
        delete_files = options["delete"]
        older_than = options["older_than"]

        if older_than < 1:
            raise CommandError("--older-than must be at least 1 hour.")

        storage = UserProfile._meta.get_field("avatar").storage
        directory = "profiles/avatars"

        try:
            _, filenames = storage.listdir(directory)
        except NotImplementedError as exc:
            raise CommandError(
                "The configured avatar storage does not support listing files."
            ) from exc
        except FileNotFoundError:
            self.stdout.write(
                self.style.SUCCESS("Avatar directory does not exist. Nothing to clean.")
            )
            return

        referenced_files = set(
            UserProfile.objects.exclude(avatar="")
            .values_list("avatar", flat=True)
        )

        cutoff = timezone.now() - timedelta(hours=older_than)

        orphaned_files = []

        for filename in filenames:
            file_path = f"{directory}/{filename}"

            if file_path in referenced_files:
                continue

            try:
                modified_at = storage.get_modified_time(file_path)
            except (FileNotFoundError, NotImplementedError):
                continue

            if modified_at < cutoff:
                orphaned_files.append(file_path)

        if not orphaned_files:
            self.stdout.write(
                self.style.SUCCESS("No orphaned avatar files found.")
            )
            return

        self.stdout.write(
            f"Found {len(orphaned_files)} orphaned avatar file(s):"
        )

        for file_path in orphaned_files:
            self.stdout.write(f"  {file_path}")

        if not delete_files:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Run again with --delete to remove these files."
                )
            )
            return

        deleted_count = 0

        for file_path in orphaned_files:
            if UserProfile.objects.filter(avatar=file_path).exists():
                continue
            
            storage.delete(file_path)
            deleted_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully deleted {deleted_count} orphaned avatar file(s)."
            )
        )
