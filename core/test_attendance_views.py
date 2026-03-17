from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import LectureAbsence, LectureAdjustment, LectureSession, Mentor, Student, TimetableEntry
from core.qa_test_helpers import create_active_calendar, create_module, login_mentor_session


@override_settings(SECURE_SSL_REDIRECT=False)
class AttendanceViewTests(TestCase):
    def setUp(self):
        self.module = create_module()
        create_active_calendar(self.module)
        self.today = timezone.localdate()
        self.mentor = Mentor.objects.create(name="HDS", full_name="Hardik D. Shah")
        self.proxy_mentor = Mentor.objects.create(name="IJT", full_name="Ishan Trivedi")
        self.entry = TimetableEntry.objects.create(
            module=self.module,
            day_of_week=self.today.weekday(),
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty=self.mentor.name,
            room="516-B",
            is_active=True,
        )
        self.student_1 = Student.objects.create(
            module=self.module,
            enrollment="2500217021001",
            roll_no=1,
            name="Student One",
            batch="B-1",
            division="B1",
            mentor=self.mentor,
        )
        self.student_2 = Student.objects.create(
            module=self.module,
            enrollment="2500217021002",
            roll_no=2,
            name="Student Two",
            batch="B-1",
            division="B1",
            mentor=self.mentor,
        )

    def test_save_lecture_attendance_rejects_unauthorized_requests(self):
        response = self.client.post(
            "/mentor-mark-attendance/save/",
            {
                "date": self.today.isoformat(),
                "batch": "B-1",
                "lecture_no": "1",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertJSONEqual(response.content, {"ok": False, "msg": "Unauthorized"})

    def test_mentor_can_save_attendance_and_replace_existing_absences(self):
        login_mentor_session(self.client, self.mentor, self.module)

        first = self.client.post(
            "/mentor-mark-attendance/save/",
            {
                "module_id": self.module.id,
                "date": self.today.isoformat(),
                "batch": "B-1",
                "lecture_no": "1",
                "absent_roll_numbers": ["2"],
            },
        )
        second = self.client.post(
            "/mentor-mark-attendance/save/",
            {
                "module_id": self.module.id,
                "date": self.today.isoformat(),
                "batch": "B-1",
                "lecture_no": "1",
                "absent_roll_numbers": ["1"],
            },
        )

        session = LectureSession.objects.get(module=self.module, date=self.today, batch="B-1", lecture_no=1)
        absent_rolls = list(
            LectureAbsence.objects.filter(session=session).order_by("student__roll_no").values_list(
                "student__roll_no", flat=True
            )
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(absent_rolls, [1])
        self.assertEqual(session.faculty, "HDS")
        self.assertEqual(session.subject, "DBMS")

    def test_original_faculty_cannot_mark_after_proxy_assignment(self):
        LectureAdjustment.objects.create(
            module=self.module,
            timetable_entry=self.entry,
            date=self.today,
            batch="B-1",
            lecture_no=1,
            time_slot="08:45-09:45",
            subject="DS",
            original_faculty=self.mentor.name,
            adjustment_type=LectureAdjustment.TYPE_PROXY,
            proxy_faculty=self.proxy_mentor,
            room="527-C",
            status=LectureAdjustment.STATUS_ACTIVE,
            created_by=self.mentor,
        )
        login_mentor_session(self.client, self.mentor, self.module)

        response = self.client.post(
            "/mentor-mark-attendance/save/",
            {
                "module_id": self.module.id,
                "date": self.today.isoformat(),
                "batch": "B-1",
                "lecture_no": "1",
                "absent_roll_numbers": ["2"],
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("Proxy assigned", response.json()["msg"])

    def test_proxy_faculty_can_mark_using_adjustment_id(self):
        TimetableEntry.objects.create(
            module=self.module,
            day_of_week=self.today.weekday(),
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-2",
            subject="DS",
            faculty=self.proxy_mentor.name,
            room="527-C",
            is_active=True,
        )
        adjustment = LectureAdjustment.objects.create(
            module=self.module,
            timetable_entry=self.entry,
            date=self.today,
            batch="B-1",
            lecture_no=1,
            time_slot="08:45-09:45",
            subject="DBMS",
            original_faculty=self.mentor.name,
            adjustment_type=LectureAdjustment.TYPE_PROXY,
            proxy_faculty=self.proxy_mentor,
            room="527-C",
            status=LectureAdjustment.STATUS_ACTIVE,
            created_by=self.mentor,
        )
        login_mentor_session(self.client, self.proxy_mentor, self.module)

        response = self.client.post(
            "/mentor-mark-attendance/save/",
            {
                "module_id": self.module.id,
                "adjustment_id": adjustment.id,
                "date": self.today.isoformat(),
                "batch": "B-1",
                "lecture_no": "1",
                "absent_roll_numbers": ["2"],
            },
        )

        session = LectureSession.objects.get(module=self.module, date=self.today, batch="B-1", lecture_no=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.faculty, "IJT")
        self.assertEqual(session.subject, "DS")
        self.assertEqual(session.room, "527-C")
