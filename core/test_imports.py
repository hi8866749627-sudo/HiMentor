from io import BytesIO

import pandas as pd
from django.test import TestCase
from openpyxl import Workbook

from core.attendance_utils import import_attendance
from core.models import Attendance, CallRecord, Mentor, MentorModuleAccess, Student
from core.qa_test_helpers import create_module
from core.utils import import_faculty_from_excel, import_students_from_excel


def _excel_bytes_from_df(df, header=True):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=header)
    buffer.seek(0)
    return buffer


def _excel_bytes_from_rows(rows):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, header=False)
    buffer.seek(0)
    return buffer


def _attendance_excel_bytes(enrollment, percent):
    wb = Workbook()
    ws = wb.active
    ws.title = "OVERALL"
    ws.append(["Roll", "Name", "Enrol No", "Attendance"])
    ws.append(["", "", "", "Overall"])
    ws.append([1, "Student One", enrollment, percent])
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


class ImportUtilityTests(TestCase):
    def test_import_faculty_maps_realistic_headers_and_defaults(self):
        fy2_module = create_module()
        create_module(
            name="FY2-IT_Sem-2 - Batch 2026-2030",
            variant="FY2-Non CE",
        )
        faculty_df = pd.DataFrame(
            [
                {
                    "Faculty Full Name": "Hardik D. Shah",
                    "Faculty 3 Letter Initial": "HDS",
                    "Department": "FY2",
                    "Contact No.": "+91 88667 49627",
                    "L.J Official Mail ID": "hardik.shah@ljinstitutes.edu.in",
                    "DOJ in LJ": "20-Feb-2017",
                }
            ]
        )

        added, updated, skipped, skipped_rows, debug = import_faculty_from_excel(
            _excel_bytes_from_df(faculty_df)
        )

        mentor = Mentor.objects.get(name="HDS")
        self.assertEqual((added, updated, skipped), (1, 0, 0))
        self.assertEqual(skipped_rows, [])
        self.assertEqual(mentor.full_name, "Hardik D. Shah")
        self.assertEqual(mentor.department, "FY2")
        self.assertEqual(mentor.phone, "+918866749627")
        self.assertEqual(mentor.email, "hardik.shah@ljinstitutes.edu.in")
        self.assertEqual(mentor.faculty_type, "Faculty")
        self.assertEqual(mentor.status, "Working")
        self.assertTrue(
            MentorModuleAccess.objects.filter(mentor=mentor, module=fy2_module).exists()
        )
        self.assertIn("Faculty 3 Letter Initial", debug["mapped"]["short_name"])

    def test_import_students_detects_header_row_and_resolves_mentor(self):
        module = create_module()
        mentor = Mentor.objects.create(name="HDS", full_name="Hardik D. Shah")
        rows = [
            ["LJ Institute of Engineering and Technology", "", "", "", "", "", "", ""],
            [
                "Enrol No",
                "Name of Student",
                "Roll No",
                "Short Name of Mentor",
                "Name of Mentor",
                "Student Mobile No",
                "Branch",
                "Sem II Div",
            ],
            [
                "2500217021001",
                "Student One",
                "1",
                "HDS",
                "Hardik Shah",
                "9876543210",
                "IT",
                "B1",
            ],
        ]

        added, updated, skipped, skipped_rows = import_students_from_excel(
            _excel_bytes_from_rows(rows),
            module,
        )

        student = Student.objects.get(module=module, enrollment="2500217021001")
        self.assertEqual((added, updated, skipped), (1, 0, 0))
        self.assertEqual(skipped_rows, [])
        self.assertEqual(student.mentor_id, mentor.id)
        self.assertEqual(student.roll_no, 1)
        self.assertEqual(student.student_mobile, "+919876543210")
        self.assertEqual(student.division, "B1")

    def test_import_attendance_is_idempotent_for_call_record_seed(self):
        module = create_module()
        mentor = Mentor.objects.create(name="HDS")
        student = Student.objects.create(
            module=module,
            enrollment="2500217021001",
            roll_no=1,
            name="Student One",
            mentor=mentor,
            batch="B-1",
        )
        weekly_file = _attendance_excel_bytes("2500217021001", "75%")
        weekly_file_again = _attendance_excel_bytes("2500217021001", "75%")

        first = import_attendance(weekly_file, None, 1, module, rule="both")
        second = import_attendance(weekly_file_again, None, 1, module, rule="both")

        attendance = Attendance.objects.get(student=student, week_no=1)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(attendance.week_percentage, 75.0)
        self.assertEqual(attendance.overall_percentage, 75.0)
        self.assertTrue(attendance.call_required)
        self.assertEqual(CallRecord.objects.filter(student=student, week_no=1).count(), 1)
