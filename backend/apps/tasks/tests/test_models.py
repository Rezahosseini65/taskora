from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.boards.services import create_board
from apps.organizations.services import create_organization
from apps.tasks.models import Task, TaskAssignee
from apps.users.models import User
from apps.workspaces.services import create_workspace


class TaskModelTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email="task-owner@example.com",
            password="TestPassword123!",
        )

        cls.assignee = User.objects.create_user(
            email="task-assignee@example.com",
            password="TestPassword123!",
        )

        cls.organization = create_organization(
            name="Task Organization",
            created_by=cls.owner,
        )

        cls.workspace = create_workspace(
            organization=cls.organization,
            name="Task Workspace",
            created_by=cls.owner,
        )

        cls.board = create_board(
            workspace=cls.workspace,
            name="Task Board",
            created_by=cls.owner,
        )

        cls.board_list = cls.board.lists.get(position=1)

    def create_task(self, **kwargs):
        defaults = {
            "board_list": self.board_list,
            "title": "Implement authentication",
            "position": 1,
            "created_by": self.owner,
        }
        defaults.update(kwargs)

        return Task.objects.create(**defaults)


class TaskCreationTests(TaskModelTestCase):

    def test_create_task(self):
        task = self.create_task()

        self.assertEqual(task.board_list, self.board_list)
        self.assertEqual(task.title, "Implement authentication")
        self.assertEqual(task.position, 1)
        self.assertEqual(task.created_by, self.owner)
        self.assertEqual(task.priority, Task.Priority.MEDIUM)
        self.assertEqual(task.description, "")
        self.assertIsNone(task.start_date)
        self.assertIsNone(task.due_date)
        self.assertIsNone(task.deleted_at)
        self.assertIsNotNone(task.id)

    def test_title_is_stripped_on_save(self):
        task = self.create_task(title="  Review pull request  ")

        self.assertEqual(task.title, "Review pull request")

    def test_empty_title_is_not_valid(self):
        task = Task(
            board_list=self.board_list,
            title="   ",
            position=1,
            created_by=self.owner,
        )

        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_default_priority_is_medium(self):
        task = self.create_task()

        self.assertEqual(task.priority, Task.Priority.MEDIUM)

    def test_all_priority_choices_are_valid(self):
        for priority, _ in Task.Priority.choices:
            task = Task(
                board_list=self.board_list,
                title=f"Task {priority}",
                position=1,
                priority=priority,
                created_by=self.owner,
            )

            task.full_clean()

    def test_optional_fields_can_be_empty(self):
        task = self.create_task(
            description="",
            start_date=None,
            due_date=None,
        )

        self.assertEqual(task.description, "")
        self.assertIsNone(task.start_date)
        self.assertIsNone(task.due_date)


class TaskConstraintTests(TaskModelTestCase):

    def test_position_must_be_unique_per_board_list(self):
        self.create_task(position=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_task(
                    title="Another task",
                    position=1,
                )

    def test_position_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_task(position=0)

    def test_deleted_task_position_remains_reserved(self):
        task = self.create_task(position=1)
        task.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_task(
                    title="Another task",
                    position=1,
                )

    def test_same_position_is_allowed_in_different_board_lists(self):
        second_board_list = self.board.lists.get(position=2)

        first = self.create_task(position=1)

        second = self.create_task(
            board_list=second_board_list,
            title="Another task",
            position=1,
        )

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.position, second.position)

    def test_due_date_cannot_be_before_start_date(self):
        task = Task(
            board_list=self.board_list,
            title="Invalid dates",
            position=1,
            created_by=self.owner,
            start_date=timezone.now().date(),
            due_date=timezone.now().date() - timedelta(days=1),
        )

        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_invalid_dates_are_rejected_by_database(self):
        today = timezone.now().date()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_task(
                    start_date=today,
                    due_date=today - timedelta(days=1),
                )

    def test_same_title_is_allowed_in_same_board_list(self):
        first = self.create_task(position=1)

        second = self.create_task(
            title=first.title,
            position=2,
        )

        self.assertEqual(first.title, second.title)
        self.assertNotEqual(first.pk, second.pk)


class TaskManagerTests(TaskModelTestCase):

    def test_default_manager_excludes_deleted_tasks(self):
        task = self.create_task()
        task.soft_delete()

        self.assertFalse(
            Task.objects.filter(pk=task.pk).exists()
        )

    def test_all_objects_manager_includes_deleted_tasks(self):
        task = self.create_task()
        task.soft_delete()

        self.assertTrue(
            Task.all_objects.filter(pk=task.pk).exists()
        )

    def test_default_manager_includes_active_tasks(self):
        task = self.create_task()

        self.assertTrue(
            Task.objects.filter(pk=task.pk).exists()
        )


class TaskLifecycleTests(TaskModelTestCase):

    def test_soft_delete(self):
        task = self.create_task()

        task.soft_delete()
        task.refresh_from_db()

        self.assertIsNotNone(task.deleted_at)

    def test_soft_delete_is_idempotent(self):
        task = self.create_task()

        task.soft_delete()
        first_deleted_at = task.deleted_at

        task.soft_delete()
        task.refresh_from_db()

        self.assertEqual(task.deleted_at, first_deleted_at)

    def test_restore(self):
        task = self.create_task()

        task.soft_delete()
        task.restore()
        task.refresh_from_db()

        self.assertIsNone(task.deleted_at)

        self.assertTrue(
            Task.objects.filter(pk=task.pk).exists()
        )

    def test_restore_preserves_position(self):
        task = self.create_task(position=5)

        task.soft_delete()
        task.restore()
        task.refresh_from_db()

        self.assertEqual(task.position, 5)

    def test_restore_preserves_reserved_position(self):
        task = self.create_task(position=1)
        task.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_task(
                    title="Another task",
                    position=1,
                )

        task.restore()
        task.refresh_from_db()

        self.assertIsNone(task.deleted_at)
        self.assertEqual(task.position, 1)

    def test_created_by_user_cannot_be_physically_deleted(self):
        creator = User.objects.create_user(
            email="task-creator@example.com",
            password="TestPassword123!",
        )

        task = self.create_task(created_by=creator)

        with self.assertRaises(ProtectedError):
            creator.delete()

        self.assertTrue(
            Task.all_objects.filter(pk=task.pk).exists()
        )


class TaskAssigneeModelTests(TaskModelTestCase):

    def create_assignment(self, **kwargs):
        task = kwargs.pop("task", None)

        if task is None:
            task = self.create_task()

        defaults = {
            "task": task,
            "user": self.assignee,
            "assigned_by": self.owner,
        }
        defaults.update(kwargs)

        return TaskAssignee.objects.create(**defaults)

    def test_create_task_assignee(self):
        assignment = self.create_assignment()

        self.assertEqual(assignment.user, self.assignee)
        self.assertEqual(assignment.assigned_by, self.owner)
        self.assertIsNone(assignment.unassigned_at)
        self.assertIsNotNone(assignment.assigned_at)
        self.assertTrue(assignment.is_active)

    def test_duplicate_active_assignment_is_rejected(self):
        task = self.create_task()

        self.create_assignment(task=task)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_assignment(task=task)

    def test_same_user_can_be_assigned_again_after_unassignment(self):
        task = self.create_task()

        first_assignment = self.create_assignment(task=task)

        first_assignment.unassigned_at = timezone.now()
        first_assignment.save(update_fields=["unassigned_at"])

        second_assignment = self.create_assignment(task=task)

        self.assertNotEqual(
            first_assignment.pk,
            second_assignment.pk,
        )

        self.assertFalse(first_assignment.is_active)
        self.assertTrue(second_assignment.is_active)

    def test_assignment_history_is_preserved(self):
        task = self.create_task()

        assignment = self.create_assignment(task=task)

        assignment.unassigned_at = timezone.now()
        assignment.save(update_fields=["unassigned_at"])

        self.assertEqual(
            TaskAssignee.objects.filter(task=task).count(),
            1,
        )

        self.assertEqual(
            TaskAssignee.objects.filter(
                task=task,
                unassigned_at__isnull=True,
            ).count(),
            0,
        )

    def test_multiple_users_can_be_assigned_to_same_task(self):
        task = self.create_task()

        self.create_assignment(task=task)

        third_user = User.objects.create_user(
            email="third-user@example.com",
            password="TestPassword123!",
        )

        self.create_assignment(
            task=task,
            user=third_user,
        )

        self.assertEqual(
            TaskAssignee.objects.filter(
                task=task,
                unassigned_at__isnull=True,
            ).count(),
            2,
        )

    def test_task_assignees_many_to_many_relation(self):
        task = self.create_task()

        self.create_assignment(task=task)

        self.assertTrue(
            task.assignees.filter(pk=self.assignee.pk).exists()
        )

    def test_task_deletion_preserves_assignment_history(self):
        task = self.create_task()

        assignment = self.create_assignment(task=task)

        task.soft_delete()

        self.assertTrue(
            TaskAssignee.objects.filter(pk=assignment.pk).exists()
        )

    def test_assignee_user_cannot_be_physically_deleted(self):
        task = self.create_task()

        assignment = self.create_assignment(task=task)

        with self.assertRaises(ProtectedError):
            self.assignee.delete()

        self.assertTrue(
            TaskAssignee.objects.filter(pk=assignment.pk).exists()
        )


    def test_assigned_by_user_cannot_be_physically_deleted(self):
        task = self.create_task()

        assigner = User.objects.create_user(
            email="task-assigner@example.com",
            password="TestPassword123!",
        )

        assignment = self.create_assignment(
            task=task,
            assigned_by=assigner,
        )

        with self.assertRaises(ProtectedError):
            assigner.delete()

        self.assertTrue(
            TaskAssignee.objects.filter(pk=assignment.pk).exists()
        )