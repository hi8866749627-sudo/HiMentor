from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from core.models import Mentor, MentorAuthToken, MentorPassword, Student
from core.qa_test_helpers import create_module


class CoreModelTests(TestCase):
    def test_student_enrollment_is_unique_per_module(self):
        module = create_module()
        mentor = Mentor.objects.create(name="HDS")
        Student.objects.create(
            module=module,
            enrollment="2500217021001",
            name="Student One",
            mentor=mentor,
        )

        with self.assertRaises(IntegrityError):
            Student.objects.create(
                module=module,
                enrollment="2500217021001",
                name="Student Two",
                mentor=mentor,
            )

    def test_mentor_password_hash_roundtrip(self):
        mentor = Mentor.objects.create(name="HDS")
        cred = MentorPassword.objects.create(mentor=mentor, password_hash="")
        cred.set_password("Secret@123")
        cred.save()

        self.assertNotEqual(cred.password_hash, "Secret@123")
        self.assertTrue(cred.check_password("Secret@123"))
        self.assertFalse(cred.check_password("wrong-pass"))

    def test_mentor_auth_token_validity_depends_on_expiry_and_active_flag(self):
        mentor = Mentor.objects.create(name="HDS")
        valid = MentorAuthToken.objects.create(
            mentor=mentor,
            token="tok_valid",
            expires_at=timezone.now() + timedelta(hours=1),
            is_active=True,
        )
        expired = MentorAuthToken.objects.create(
            mentor=mentor,
            token="tok_expired",
            expires_at=timezone.now() - timedelta(minutes=1),
            is_active=True,
        )

        self.assertTrue(valid.is_valid())
        self.assertFalse(expired.is_valid())

