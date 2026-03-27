from datetime import timedelta

from django.test import TestCase, override_settings

from django.contrib.auth.models import User
from django.utils import timezone

from core.models import AcademicCalendar, AcademicModule, College, ExamBlock, ExamBlockStudent, ExamFacultyProfile, ExamMarkEntry, ExamSeatingBlock, ExamTimetableEntry, LectureAdjustment, Mentor, ModuleExamSession, ResultUpload, RoleAssignment, SifMarksLock, Student, StudentResult, Subject, TimetableChangeLog, TimetableEntry, TimetableUpload, University, YearScope
from core.qa_test_helpers import create_college_head, create_coordinator, create_erp_owner, create_module, create_superadmin, create_university_head, create_year_head, login_mentor_session


@override_settings(SECURE_SSL_REDIRECT=False)
class ManageMentorsAndAccessTests(TestCase):
    def test_year_head_can_open_home_dashboard_for_scoped_module(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.get("/home/")

        self.assertEqual(response.status_code, 200)
        response_modules = list(response.context["modules"])
        self.assertIn(module.id, [m.id for m in response_modules])
        self.assertTrue(all(m.year_scope_id == year_scope.id for m in response_modules))
        self.assertTrue(response.context["show_org_setup_link"])
        self.assertFalse(response.context["show_global_coordinator_management"])
        self.assertFalse(response.context["show_global_module_setup"])
        self.assertTrue(response.context["show_scoped_year_actions"])
        self.assertContains(response, 'href="/org-setup/"', html=False)
        self.assertContains(response, f'href="/modules/?year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/year-coordinators/?year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/upload-students/?module_id={module.id}&year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/upload-faculty/?module_id={module.id}&year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/subjects/?module_id={module.id}&year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/view-timetable/?module_id={module.id}&year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/manage-mentors/?module_id={module.id}&year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/attendance-analytics/?module_id={module.id}&year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, f'href="/year-home/?year_scope_id={year_scope.id}"', html=False)
        self.assertContains(response, "Subject Setup")
        self.assertContains(response, "Timetable Setup")
        self.assertContains(response, "Year Ownership")
        self.assertContains(response, year_scope.year_code)
        self.assertContains(response, "Current Scope")
        self.assertContains(response, year_scope.college.university.name)
        self.assertContains(response, year_scope.college.name)
        self.assertContains(response, module.name)

    def test_year_head_manage_mentors_honors_module_query_filter(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/manage-mentors/?module_id={alternate_module.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, alternate_module.id)

    def test_year_head_manage_mentors_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/manage-mentors/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_can_delete_scoped_coordinator_from_home(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        coordinator = create_coordinator(module, username="yearheaddeletecoord")
        self.client.force_login(year_head)

        response = self.client.post(
            "/home/",
            {
                "action": "delete_scoped_coordinator",
                "coordinator_id": str(coordinator.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(id=coordinator.id).exists())

    def test_year_head_can_delete_scoped_module_from_home(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            "/home/",
            {
                "action": "delete_scoped_module",
                "module_id": str(module.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AcademicModule.objects.filter(id=module.id).exists())

    def test_year_head_home_post_preserves_anchor(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            "/home/",
            {
                "action": "delete_scoped_module",
                "module_id": str(module.id),
                "return_anchor": "module-ownership",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/home/#module-ownership")

    def test_year_head_manage_modules_shows_only_scoped_modules(self):
        in_scope = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        out_of_scope = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        year_head, year_scope = create_year_head()
        in_scope.year_scope = year_scope
        in_scope.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.get("/modules/")

        self.assertEqual(response.status_code, 200)
        response_ids = {m.id for m in response.context["modules"]}
        self.assertIn(in_scope.id, response_ids)
        self.assertNotIn(out_of_scope.id, response_ids)

    def test_year_head_manage_modules_honors_year_scope_query_filter(self):
        university = University.objects.create(name="Module Filter University", code="MFU")
        college = College.objects.create(university=university, name="Module Filter College", code="MFC")
        user = User.objects.create_user(username="modulefilterhead", password="pass12345", is_active=True)
        fy_scope = YearScope.objects.create(college=college, year_code="FY", title="FY")
        sy_scope = YearScope.objects.create(college=college, year_code="SY", title="SY")
        RoleAssignment.objects.create(user=user, role=RoleAssignment.ROLE_YEAR_HEAD, year_scope=fy_scope)
        RoleAssignment.objects.create(user=user, role=RoleAssignment.ROLE_YEAR_HEAD, year_scope=sy_scope)
        fy_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        fy_module.year_scope = fy_scope
        fy_module.save(update_fields=["year_scope"])
        sy_module = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        sy_module.year_scope = sy_scope
        sy_module.save(update_fields=["year_scope"])
        self.client.force_login(user)

        response = self.client.get(f"/modules/?year_scope_id={fy_scope.id}")

        self.assertEqual(response.status_code, 200)
        response_ids = {m.id for m in response.context["modules"]}
        self.assertIn(fy_module.id, response_ids)
        self.assertNotIn(sy_module.id, response_ids)
        self.assertEqual(response.context["filters"]["year_scope_id"], str(fy_scope.id))
        self.assertEqual(response.context["default_year_scope"].id, fy_scope.id)
        self.assertContains(response, f"/modules/?year_scope_id={fy_scope.id}")

    def test_year_head_created_module_inherits_current_year_scope(self):
        existing = create_module()
        year_head, year_scope = create_year_head()
        existing.year_scope = year_scope
        existing.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = existing.id
        session.save()

        response = self.client.post(
            "/modules/",
            {
                "action": "create",
                "academic_batch": "2027-2031",
                "year_level": "SY",
                "variant": "FY3",
                "semester": "Sem-2",
                "is_active": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        created = AcademicModule.objects.get(name="FY3_Sem-2 - Batch 2027-2031")
        self.assertEqual(created.year_scope_id, year_scope.id)
        self.assertEqual(created.year_level, year_scope.year_code)

    def test_erp_owner_manage_modules_is_not_pinned_to_current_module_year_scope(self):
        existing = create_module()
        owner = create_erp_owner(username="moduleowneradmin")
        _, year_scope = create_year_head(username="moduleowneryearhead")
        existing.year_scope = year_scope
        existing.save(update_fields=["year_scope"])
        self.client.force_login(owner)
        session = self.client.session
        session["current_module_id"] = existing.id
        session.save()

        response = self.client.post(
            "/modules/",
            {
                "action": "create",
                "academic_batch": "2027-2031",
                "year_level": "SY",
                "variant": "SY1",
                "semester": "Sem-2",
                "is_active": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        created = AcademicModule.objects.get(name="SY1_Sem-2 - Batch 2027-2031")
        self.assertEqual(created.year_level, "SY")
        self.assertIsNone(created.year_scope_id)

    def test_year_head_modules_post_preserves_anchor(self):
        existing = create_module()
        year_head, year_scope = create_year_head()
        existing.year_scope = year_scope
        existing.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            "/modules/",
            {
                "action": "delete",
                "module_id": str(existing.id),
                "return_anchor": "module-details",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/modules/#module-details")

    def test_year_head_modules_post_preserves_year_scope_filter_and_anchor(self):
        existing = create_module()
        year_head, year_scope = create_year_head()
        existing.year_scope = year_scope
        existing.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            f"/modules/?year_scope_id={year_scope.id}",
            {
                "action": "delete",
                "module_id": str(existing.id),
                "year_scope_id": str(year_scope.id),
                "return_anchor": "module-details",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/modules/?year_scope_id={year_scope.id}#module-details")

    def test_academic_calendar_bulk_apply_preserves_year_and_anchor(self):
        admin = create_superadmin()
        module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030", semester="Sem-1")
        other_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3", semester="Sem-1")
        self.client.force_login(admin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/academic-calendar/?year=FY",
            {
                "action": "bulk_apply",
                "module_ids": [str(module.id), str(other_module.id)],
                "year": "FY",
                "return_anchor": "calendar-bulk-apply",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("year=FY", response.url)
        self.assertTrue(response.url.endswith("#calendar-bulk-apply"))

    def test_subject_alias_add_preserves_anchor(self):
        admin = create_superadmin(username="subjectanchoradmin")
        module = create_module()
        Subject.objects.create(module=module, name="Mathematics II", short_name="M-II")
        self.client.force_login(admin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/subjects/aliases/add/",
            {
                "alias": "MATHS-II",
                "canonical": "M-II",
                "return_anchor": "subjects-aliases",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/subjects/#subjects-aliases")

    def test_year_head_can_open_faculty_sample_download(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.get("/upload-faculty/sample/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_year_head_live_followup_sheet_gets_admin_view(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.get("/live-followup-sheet/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_admin_view"])

    def test_year_head_live_followup_sheet_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/live-followup-sheet/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_can_switch_live_followup_module_with_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/live-followup-sheet/?module_id={alternate_module.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, alternate_module.id)
        self.assertEqual(response.context["selected_module_id"], str(alternate_module.id))

    def test_year_head_can_switch_coordinator_daily_weekly_report_module(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/coordinator-daily-weekly-report/?module_id={alternate_module.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, alternate_module.id)
        self.assertEqual(response.context["selected_module_id"], str(alternate_module.id))

    def test_year_head_timetable_excel_uses_selected_module_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        TimetableEntry.objects.create(
            module=alternate_module,
            day_of_week=0,
            lecture_no=1,
            time_slot="10:00-11:00",
            batch="B-1",
            subject="Maths",
            faculty="Faculty A",
            room="101",
            is_active=True,
        )
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/timetable-excel/?module_id={alternate_module.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_mentor_print_sif_uses_selected_module_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        _, year_scope = create_year_head()
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        mentor = Mentor.objects.create(name="MENTOR-A")
        Student.objects.create(
            module=primary_module,
            enrollment="ENR-1",
            roll_no=1,
            name="Primary Student",
            batch="B-1",
            division="B-1",
            mentor=mentor,
        )
        Student.objects.create(
            module=alternate_module,
            enrollment="ENR-2",
            roll_no=2,
            name="Alternate Student",
            batch="B-2",
            division="B-2",
            mentor=mentor,
        )
        login_mentor_session(self.client, mentor, primary_module)

        response = self.client.get(
            f"/mentor-print-sif/?module_id={alternate_module.id}&year_scope_id={year_scope.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, alternate_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(
            response,
            f"/mentor-prefilled-sif-all/?module_id={alternate_module.id}&year_scope_id={year_scope.id}",
            html=False,
        )
        self.assertEqual(response.context["selected_module_id"], str(alternate_module.id))
        student_ids = [student.id for student in response.context["students"]]
        self.assertEqual(len(student_ids), 1)

    def test_year_head_upload_students_uses_selected_module_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/upload-students/?module_id={alternate_module.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, alternate_module.id)
        self.assertEqual(response.context["selected_module_id"], str(alternate_module.id))

    def test_year_head_upload_students_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/upload-students/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_upload_faculty_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/upload-faculty/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, "Scope:")
        self.assertContains(response, year_scope.college.university.name)
        self.assertContains(response, year_scope.college.name)
        self.assertContains(response, year_scope.year_code)

    def test_year_head_subjects_page_shows_scope_summary_for_selected_module(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        Subject.objects.create(module=alternate_module, name="Mathematics II", short_name="M-II")
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/subjects/?module_id={alternate_module.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, alternate_module.id)
        self.assertContains(response, "Scope:")
        self.assertContains(response, year_scope.college.university.name)
        self.assertContains(response, year_scope.college.name)
        self.assertContains(response, year_scope.year_code)
        self.assertContains(response, alternate_module.name)

    def test_year_head_subjects_page_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/subjects/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))

    def test_year_head_add_subject_preserves_year_scope_query_param(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            f"/subjects/add/?module_id={module.id}&year_scope_id={year_scope.id}",
            {
                "name": "Physics",
                "short_name": "PHY",
                "has_theory": "on",
                "has_practical": "on",
                "result_format": Subject.FORMAT_FULL,
                "return_anchor": "subjects-add",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/subjects/?"))
        self.assertIn(f"module_id={module.id}", response.url)
        self.assertIn(f"year_scope_id={year_scope.id}", response.url)
        self.assertTrue(response.url.endswith("#subjects-add"))

    def test_college_home_shows_year_rollup_counts(self):
        university = University.objects.create(name="Rollup University", code="RU")
        college = College.objects.create(university=university, name="Rollup College", code="RC")
        user = User.objects.create_user(username="rollupcollegehead", password="pass12345", is_active=True)
        RoleAssignment.objects.create(
            user=user,
            role=RoleAssignment.ROLE_COLLEGE_HEAD,
            college=college,
        )
        year_scope = YearScope.objects.create(college=college, year_code="FY", title="FY")
        module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        create_coordinator(module, username="rollupcoord")
        Subject.objects.create(module=module, name="Physics", short_name="PHY", is_active=True)
        TimetableEntry.objects.create(
            module=module,
            day_of_week=0,
            lecture_no=1,
            time_slot="10:00-11:00",
            batch="B-1",
            subject="Physics",
            faculty="FAC-1",
            room="R-101",
            is_active=True,
        )
        AcademicCalendar.objects.create(module=module, is_active=True)
        mentor = Mentor.objects.create(name="ROLLUP-MENTOR")
        Student.objects.create(
            module=module,
            enrollment="ROLLUP-1",
            roll_no=1,
            name="Rollup Student",
            batch="B-1",
            division="B-1",
            mentor=mentor,
        )
        self.client.force_login(user)

        response = self.client.get("/college-home/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["modules"], 1)
        self.assertEqual(response.context["summary"]["coordinators"], 1)
        self.assertEqual(response.context["summary"]["students"], 1)
        self.assertEqual(response.context["summary"]["subjects"], 1)
        self.assertEqual(response.context["summary"]["timetable_entries"], 1)
        self.assertEqual(response.context["summary"]["active_calendars"], 1)
        self.assertContains(response, "Modules")
        self.assertContains(response, "Coordinators")
        self.assertContains(response, "Students")
        self.assertContains(response, "Subjects")
        self.assertContains(response, "Timetable Entries")
        self.assertContains(response, "Active Calendars")
        self.assertContains(response, f'/modules/?year_scope_id={year_scope.id}', html=False)
        self.assertContains(response, f'/year-coordinators/?year_scope_id={year_scope.id}#year-coordinator-table', html=False)
        self.assertContains(response, f'/upload-students/?module_id={module.id}', html=False)
        self.assertContains(response, f'/subjects/?module_id={module.id}&year_scope_id={year_scope.id}', html=False)
        self.assertContains(response, f'/view-timetable/?module_id={module.id}&year_scope_id={year_scope.id}', html=False)
        self.assertContains(response, f'/academic-calendar/?module_id={module.id}&year_scope_id={year_scope.id}', html=False)

    def test_university_home_shows_college_rollup_counts(self):
        university = University.objects.create(name="University Rollup", code="UR")
        college = College.objects.create(university=university, name="College Rollup", code="CR")
        user = User.objects.create_user(username="universityrolluphead", password="pass12345", is_active=True)
        RoleAssignment.objects.create(
            user=user,
            role=RoleAssignment.ROLE_UNIVERSITY_HEAD,
            university=university,
        )
        year_scope = YearScope.objects.create(college=college, year_code="FY", title="FY")
        module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        create_coordinator(module, username="universityrollupcoord")
        Subject.objects.create(module=module, name="Mathematics", short_name="MATH", is_active=True)
        TimetableEntry.objects.create(
            module=module,
            day_of_week=0,
            lecture_no=1,
            time_slot="10:00-11:00",
            batch="B-1",
            subject="Mathematics",
            faculty="FAC-2",
            room="R-102",
            is_active=True,
        )
        AcademicCalendar.objects.create(module=module, is_active=True)
        mentor = Mentor.objects.create(name="UNIVERSITY-ROLLUP-MENTOR")
        Student.objects.create(
            module=module,
            enrollment="UNI-ROLLUP-1",
            roll_no=1,
            name="University Rollup Student",
            batch="B-1",
            division="B-1",
            mentor=mentor,
        )
        self.client.force_login(user)

        response = self.client.get("/university-home/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["year_scopes"], 1)
        self.assertEqual(response.context["summary"]["modules"], 1)
        self.assertEqual(response.context["summary"]["coordinators"], 1)
        self.assertEqual(response.context["summary"]["students"], 1)
        self.assertEqual(response.context["summary"]["subjects"], 1)
        self.assertEqual(response.context["summary"]["timetable_entries"], 1)
        self.assertEqual(response.context["summary"]["active_calendars"], 1)
        self.assertContains(response, "Years")
        self.assertContains(response, "Modules")
        self.assertContains(response, "Coordinators")
        self.assertContains(response, "Students")
        self.assertContains(response, "Subjects")
        self.assertContains(response, "Timetable Entries")
        self.assertContains(response, "Active Calendars")
        self.assertContains(response, f'/college-home/?college_id={college.id}', html=False)
        self.assertContains(response, f'/college-home/?college_id={college.id}#year-ownership', html=False)
        self.assertContains(response, f'/year-home/?college_id={college.id}#module-ownership', html=False)
        self.assertContains(response, f'/year-home/?college_id={college.id}#coordinator-ownership', html=False)

    def test_org_setup_year_scope_filter_supports_college_rollup_drilldown(self):
        university = University.objects.create(name="Drilldown University", code="DU")
        college = College.objects.create(university=university, name="Drilldown College", code="DC")
        user = User.objects.create_user(username="drilldowncollegehead", password="pass12345", is_active=True)
        RoleAssignment.objects.create(
            user=user,
            role=RoleAssignment.ROLE_COLLEGE_HEAD,
            college=college,
        )
        fy_scope = YearScope.objects.create(college=college, year_code="FY", title="FY")
        sy_scope = YearScope.objects.create(college=college, year_code="SY", title="SY")
        fy_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        fy_module.year_scope = fy_scope
        fy_module.save(update_fields=["year_scope"])
        sy_module = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        sy_module.year_scope = sy_scope
        sy_module.save(update_fields=["year_scope"])
        create_coordinator(fy_module, username="drilldowncoord")
        self.client.force_login(user)

        response = self.client.get(f"/org-setup/?college_id={college.id}&year_scope_id={fy_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["org_summary"]["modules"], 1)
        self.assertEqual(response.context["filters"]["year_scope_id"], str(fy_scope.id))
        self.assertContains(
            response,
            f"year_scope_id={fy_scope.id}",
            html=False,
        )

    def test_year_home_shows_filtered_year_scope_rollup(self):
        university = University.objects.create(name="Year Home University", code="YHU")
        college = College.objects.create(university=university, name="Year Home College", code="YHC")
        user = User.objects.create_user(username="yearhomecollegehead", password="pass12345", is_active=True)
        RoleAssignment.objects.create(
            user=user,
            role=RoleAssignment.ROLE_COLLEGE_HEAD,
            college=college,
        )
        fy_scope = YearScope.objects.create(college=college, year_code="FY", title="FY")
        sy_scope = YearScope.objects.create(college=college, year_code="SY", title="SY")
        fy_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        fy_module.year_scope = fy_scope
        fy_module.save(update_fields=["year_scope"])
        sy_module = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        sy_module.year_scope = sy_scope
        sy_module.save(update_fields=["year_scope"])
        create_coordinator(fy_module, username="yearhomecoord")
        subject = Subject.objects.create(module=fy_module, name="Year Physics", short_name="YP", is_active=True)
        TimetableEntry.objects.create(
            module=fy_module,
            day_of_week=0,
            lecture_no=1,
            time_slot="10:00-11:00",
            batch="B-1",
            subject="Year Physics",
            faculty="YEAR-FAC",
            room="R-201",
            is_active=True,
        )
        AcademicCalendar.objects.create(module=fy_module, is_active=True)
        ResultUpload.objects.create(module=fy_module, subject=subject, test_name="T1", uploaded_by="yearhead")
        mentor = Mentor.objects.create(name="YEARHOME-MENTOR")
        Student.objects.create(
            module=fy_module,
            enrollment="YEARHOME-1",
            roll_no=1,
            name="Year Home Student",
            batch="B-1",
            division="B-1",
            mentor=mentor,
        )
        self.client.force_login(user)

        response = self.client.get(f"/year-home/?college_id={college.id}&year_scope_id={fy_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["year_scopes"], 1)
        self.assertEqual(response.context["summary"]["modules"], 1)
        self.assertEqual(response.context["summary"]["coordinators"], 1)
        self.assertEqual(response.context["summary"]["students"], 1)
        self.assertEqual(response.context["summary"]["subjects"], 1)
        self.assertEqual(response.context["summary"]["timetable_entries"], 1)
        self.assertEqual(response.context["summary"]["active_calendars"], 1)
        self.assertEqual(response.context["summary"]["result_uploads"], 1)
        self.assertContains(response, "Year Home")
        self.assertContains(response, "Module Readiness")
        self.assertContains(response, fy_scope.year_code)
        self.assertContains(response, f"/modules/?year_scope_id={fy_scope.id}")
        self.assertContains(response, f"/year-coordinators/?year_scope_id={fy_scope.id}")
        self.assertContains(response, f"/year-coordinators/?year_scope_id={fy_scope.id}#year-coordinator-table")
        self.assertContains(response, f"/upload-students/?module_id={fy_module.id}")
        self.assertContains(response, f"/upload-faculty/?module_id={fy_module.id}")
        self.assertContains(response, f"/subjects/?module_id={fy_module.id}&year_scope_id={fy_scope.id}")
        self.assertContains(response, f"/view-timetable/?module_id={fy_module.id}&year_scope_id={fy_scope.id}")
        self.assertContains(response, f"/academic-calendar/?module_id={fy_module.id}&year_scope_id={fy_scope.id}")
        self.assertContains(response, f"/upload-results/?module_id={fy_module.id}&year_scope_id={fy_scope.id}")
        self.assertEqual(response.context["focus_module"].id, fy_module.id)

    def test_year_head_rbac_create_coordinator_rejects_out_of_scope_module(self):
        in_scope = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        out_of_scope = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        year_head, year_scope = create_year_head()
        in_scope.year_scope = year_scope
        in_scope.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            "/rbac/create-coordinator/",
            {
                "username": "scopedcoord",
                "password": "pass12345",
                "module_ids": str(out_of_scope.id),
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_year_head_can_download_db_backup_json(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.get("/live-followup-sheet/db-backup-json/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("himentor_legacy_full_backup_", response["Content-Disposition"])

    def test_erp_owner_can_create_university_from_org_setup(self):
        owner = create_erp_owner()
        self.client.force_login(owner)

        response = self.client.post(
            "/org-setup/",
            {"action": "create_university", "name": "Demo University", "code": "DU"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(University.objects.filter(name="Demo University").exists())

    def test_university_head_can_open_university_home(self):
        user, university = create_university_head()
        self.client.force_login(user)

        response = self.client.get("/university-home/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["universities"]), [university])
        self.assertEqual(response.context["summary"]["universities"], 1)
        self.assertEqual(response.context["summary"]["university_heads"], 1)
        self.assertContains(response, "University Overview")
        self.assertContains(response, "University Ownership")
        self.assertContains(response, "University Heads")
        self.assertContains(response, 'href="/org-setup/"', html=False)
        self.assertContains(response, 'href="/university-home/"', html=False)
        self.assertContains(response, 'href="/college-home/"', html=False)
        self.assertContains(response, 'href="/college-home/"', html=False)
        self.assertContains(response, user.username)
        self.assertContains(response, 'href="/college-home/"', html=False)
        self.assertContains(response, "Scope:")
        self.assertContains(response, university.name)
        self.assertContains(response, "University / College")

    def test_university_head_can_create_college_from_university_home(self):
        user, university = create_university_head()
        self.client.force_login(user)

        response = self.client.post(
            "/university-home/",
            {"action": "create_college", "university_id": str(university.id), "name": "LJMBA", "code": "LJMBA"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(university.colleges.filter(name="LJMBA").exists())

    def test_university_head_can_assign_college_head_from_university_home(self):
        user, university = create_university_head(username="uniassignhome")
        college = College.objects.create(university=university, name="LJP", code="LJP", is_active=True)
        target = User.objects.create_user(username="collegehomeassign", password="pass12345", is_active=True)
        self.client.force_login(user)

        response = self.client.post(
            "/university-home/",
            {"action": "assign_college_head", "user_id": str(target.id), "college_id": str(college.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RoleAssignment.objects.filter(
                user=target,
                role=RoleAssignment.ROLE_COLLEGE_HEAD,
                college=college,
            ).exists()
        )

    def test_university_head_can_remove_college_head_from_university_home(self):
        user, university = create_university_head(username="uniremovehome")
        target = User.objects.create_user(username="collegeremovehome", password="pass12345", is_active=True)
        college = College.objects.create(university=university, name="LJMCA", code="LJMCA", is_active=True)
        assignment = RoleAssignment.objects.create(
            user=target,
            role=RoleAssignment.ROLE_COLLEGE_HEAD,
            college=college,
            is_active=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            "/university-home/",
            {"action": "remove_college_head", "assignment_id": str(assignment.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(RoleAssignment.objects.filter(id=assignment.id).exists())

    def test_college_head_can_open_college_home(self):
        user, college = create_college_head()
        self.client.force_login(user)

        response = self.client.get("/college-home/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["colleges"]), [college])
        self.assertEqual(response.context["summary"]["colleges"], 1)
        self.assertEqual(response.context["summary"]["college_heads"], 1)
        self.assertContains(response, "College Overview")
        self.assertContains(response, "College Ownership")
        self.assertContains(response, "Year Heads")
        self.assertContains(response, 'href="/university-home/"', html=False)
        self.assertContains(response, 'href="/college-home/"', html=False)
        self.assertContains(response, 'href="/home/"', html=False)
        self.assertContains(response, 'href="/year-home/"', html=False)
        self.assertContains(response, 'href="/college-home/"', html=False)
        self.assertContains(response, user.username)
        self.assertContains(response, 'href="/org-setup/"', html=False)
        self.assertContains(response, "Scope:")
        self.assertContains(response, college.name)
        self.assertContains(response, "University / College / Year")

    def test_university_head_home_redirects_to_university_home(self):
        user, _ = create_university_head(username="redirunihead")
        self.client.force_login(user)

        response = self.client.get("/home/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/university-home/")

    def test_college_head_home_redirects_to_college_home(self):
        user, _ = create_college_head(username="redircollegehead")
        self.client.force_login(user)

        response = self.client.get("/home/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/college-home/")

    def test_college_head_can_create_year_from_college_home(self):
        user, college = create_college_head()
        self.client.force_login(user)

        response = self.client.post(
            "/college-home/",
            {"action": "create_year_scope", "college_id": str(college.id), "year_code": "SY", "title": "Second Year"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(college.year_scopes.filter(year_code="SY").exists())

    def test_college_head_can_assign_year_head_from_college_home(self):
        user, college = create_college_head(username="collegeassignhome")
        year_scope = college.year_scopes.get(year_code="FY")
        target = User.objects.create_user(username="yearhomeassign", password="pass12345", is_active=True)
        self.client.force_login(user)

        response = self.client.post(
            "/college-home/",
            {"action": "assign_year_head", "user_id": str(target.id), "year_scope_id": str(year_scope.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RoleAssignment.objects.filter(
                user=target,
                role=RoleAssignment.ROLE_YEAR_HEAD,
                year_scope=year_scope,
            ).exists()
        )

    def test_college_head_can_remove_year_head_from_college_home(self):
        user, college = create_college_head(username="collegeremoveyear")
        target = User.objects.create_user(username="yearremovehome", password="pass12345", is_active=True)
        year_scope = college.year_scopes.get(year_code="FY")
        assignment = RoleAssignment.objects.create(
            user=target,
            role=RoleAssignment.ROLE_YEAR_HEAD,
            year_scope=year_scope,
            is_active=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            "/college-home/",
            {"action": "remove_year_head", "assignment_id": str(assignment.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(RoleAssignment.objects.filter(id=assignment.id).exists())

    def test_university_and_college_home_links_show_in_sidebar_for_scoped_roles(self):
        university_user, _ = create_university_head(username="sidebarunihead")
        self.client.force_login(university_user)

        university_response = self.client.get("/university-home/")

        self.assertContains(university_response, 'href="/university-home/"', html=False)
        self.assertContains(university_response, 'href="/college-home/"', html=False)
        self.client.logout()

        college_user, _ = create_college_head(username="sidebarcollegehead")
        self.client.force_login(college_user)

        college_response = self.client.get("/college-home/")

        self.assertContains(college_response, 'href="/college-home/"', html=False)
        self.assertContains(college_response, '<a href="/university-home/" class="text-decoration-none">University Home</a>', html=False)

    def test_college_head_can_create_year_scope_for_owned_college(self):
        college_head, college = create_college_head()
        self.client.force_login(college_head)

        response = self.client.post(
            "/org-setup/",
            {"action": "create_year_scope", "college_id": str(college.id), "year_code": "SY", "title": "Second Year"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(college.year_scopes.filter(year_code="SY").exists())

    def test_erp_owner_can_assign_university_head(self):
        owner = create_erp_owner()
        target = User.objects.create_user(username="unihead", password="pass12345", is_active=True)
        university = University.objects.get(name="LJU")
        self.client.force_login(owner)

        response = self.client.post(
            "/org-setup/",
            {"action": "assign_university_head", "user_id": str(target.id), "university_id": str(university.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RoleAssignment.objects.filter(
                user=target,
                role=RoleAssignment.ROLE_UNIVERSITY_HEAD,
                university=university,
            ).exists()
        )

    def test_org_setup_shows_cross_level_summary_counts(self):
        owner = create_erp_owner(username="orgsummaryowner")
        module = create_module()
        _, year_scope = create_year_head(username="orgsummaryyearhead")
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        create_coordinator(module, username="orgsummarycoord")
        self.client.force_login(owner)

        response = self.client.get("/org-setup/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["org_summary"]["universities"], 1)
        self.assertGreaterEqual(response.context["org_summary"]["colleges"], 1)
        self.assertGreaterEqual(response.context["org_summary"]["year_scopes"], 1)
        self.assertGreaterEqual(response.context["org_summary"]["modules"], 1)
        self.assertGreaterEqual(response.context["org_summary"]["coordinators"], 1)
        self.assertContains(response, "Universities")
        self.assertContains(response, "Coordinators")

    def test_university_home_supports_search_filter(self):
        user, university = create_university_head(username="filterunihead")
        College.objects.create(university=university, name="Searchable College", code="SC", is_active=True)
        College.objects.create(university=university, name="Other College", code="OC", is_active=True)
        self.client.force_login(user)

        response = self.client.get("/university-home/?q=Searchable")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Searchable College")
        self.assertNotContains(response, "Other College")

    def test_college_home_supports_college_filter(self):
        user, owned_college = create_college_head(username="filtercollegehead")
        other_college = College.objects.create(
            university=owned_college.university,
            name="Second College",
            code="SEC",
            is_active=True,
        )
        RoleAssignment.objects.create(
            user=user,
            role=RoleAssignment.ROLE_COLLEGE_HEAD,
            college=other_college,
            is_active=True,
        )
        self.client.force_login(user)

        response = self.client.get(f"/college-home/?college_id={owned_college.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([college.name for college in response.context["colleges"]], [owned_college.name])
        self.assertEqual([row["college"].name for row in response.context["college_rows"]], [owned_college.name])

    def test_org_setup_supports_university_filter(self):
        owner = create_erp_owner(username="filterorgowner")
        primary_university = University.objects.get(name="LJU")
        secondary_university = University.objects.create(name="Demo University", code="DU", is_active=True)
        College.objects.create(university=secondary_university, name="Demo College", code="DC", is_active=True)
        self.client.force_login(owner)

        response = self.client.get(f"/org-setup/?university_id={primary_university.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([university.name for university in response.context["universities"]], [primary_university.name])
        self.assertEqual([college.university.name for college in response.context["colleges"]], [primary_university.name])

    def test_university_home_paginates_college_rows(self):
        user, university = create_university_head(username="paginateunihead")
        for idx in range(12):
            College.objects.create(university=university, name=f"Paged College {idx}", code=f"PC{idx}", is_active=True)
        self.client.force_login(user)

        response = self.client.get("/university-home/?colleges_page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["college_rows_page"].number, 2)
        self.assertContains(response, "Page 2 of")

    def test_university_home_post_preserves_filter_query_params(self):
        user, university = create_university_head(username="persistunihead")
        self.client.force_login(user)

        response = self.client.post(
            f"/university-home/?q=LJU&university_id={university.id}",
            {"action": "create_college", "university_id": str(university.id), "name": "Persist College", "code": "PERS"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/university-home/?"))
        self.assertIn("q=LJU", response.url)
        self.assertIn(f"university_id={university.id}", response.url)

    def test_university_home_post_preserves_pagination_and_anchor(self):
        user, university = create_university_head(username="persistanchorunihead")
        self.client.force_login(user)

        response = self.client.post(
            f"/university-home/?q=LJU&university_id={university.id}&colleges_page=2",
            {
                "action": "create_college",
                "university_id": str(university.id),
                "name": "Persist Anchor College",
                "code": "PAC",
                "return_anchor": "college-assignments",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("q=LJU", response.url)
        self.assertIn(f"university_id={university.id}", response.url)
        self.assertIn("colleges_page=2", response.url)
        self.assertTrue(response.url.endswith("#college-assignments"))

    def test_erp_owner_can_assign_college_head(self):
        owner = create_erp_owner()
        target = User.objects.create_user(username="collegeassign", password="pass12345", is_active=True)
        _, college = create_college_head(username="seedcollegehead")
        self.client.force_login(owner)

        response = self.client.post(
            "/org-setup/",
            {"action": "assign_college_head", "user_id": str(target.id), "college_id": str(college.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RoleAssignment.objects.filter(
                user=target,
                role=RoleAssignment.ROLE_COLLEGE_HEAD,
                college=college,
            ).exists()
        )

    def test_college_head_can_assign_year_head_for_owned_college(self):
        college_head, college = create_college_head()
        year_scope = college.year_scopes.get(year_code="FY")
        target = User.objects.create_user(username="yearassign", password="pass12345", is_active=True)
        self.client.force_login(college_head)

        response = self.client.post(
            "/org-setup/",
            {"action": "assign_year_head", "user_id": str(target.id), "year_scope_id": str(year_scope.id)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RoleAssignment.objects.filter(
                user=target,
                role=RoleAssignment.ROLE_YEAR_HEAD,
                year_scope=year_scope,
            ).exists()
        )

    def test_year_head_can_create_coordinator_from_org_setup_for_scoped_module(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            "/org-setup/",
            {
                "action": "create_coordinator",
                "coordinator_name": "Scoped Coord",
                "username": "scopedcoord2",
                "password": "pass12345",
                "module_ids": [str(module.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="scopedcoord2").exists())

    def test_year_head_org_setup_coordinator_post_preserves_year_scope_filter_and_anchor(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            f"/org-setup/?year_scope_id={year_scope.id}",
            {
                "action": "create_coordinator",
                "coordinator_name": "Scoped Coord",
                "username": "scopedcoord3",
                "password": "pass12345",
                "module_ids": [str(module.id)],
                "return_anchor": "org-coordinators",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/org-setup/?year_scope_id={year_scope.id}#org-coordinators")

    def test_year_head_year_coordinators_page_is_scoped_to_selected_year(self):
        first_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        second_module = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        university = University.objects.create(name="Year Coordinator University", code="YCU")
        college = College.objects.create(university=university, name="Year Coordinator College", code="YCC")
        user = User.objects.create_user(username="yearcoordhead", password="pass12345", is_active=True)
        fy_scope = YearScope.objects.create(college=college, year_code="FY", title="FY")
        sy_scope = YearScope.objects.create(college=college, year_code="SY", title="SY")
        RoleAssignment.objects.create(user=user, role=RoleAssignment.ROLE_YEAR_HEAD, year_scope=fy_scope)
        RoleAssignment.objects.create(user=user, role=RoleAssignment.ROLE_YEAR_HEAD, year_scope=sy_scope)
        first_module.year_scope = fy_scope
        first_module.save(update_fields=["year_scope"])
        second_module.year_scope = sy_scope
        second_module.save(update_fields=["year_scope"])
        first_coordinator = create_coordinator(first_module, username="yearcoord1")
        create_coordinator(second_module, username="yearcoord2")
        self.client.force_login(user)

        response = self.client.get(f"/year-coordinators/?year_scope_id={fy_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_year_scope"].id, fy_scope.id)
        self.assertEqual(response.context["summary"]["year_scopes"], 1)
        self.assertEqual(response.context["summary"]["modules"], 1)
        self.assertEqual(response.context["summary"]["coordinators"], 1)
        self.assertContains(response, first_coordinator.username)
        self.assertNotContains(response, "yearcoord2")

    def test_year_head_year_coordinators_post_preserves_year_scope_and_anchor(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            f"/year-coordinators/?year_scope_id={year_scope.id}",
            {
                "action": "create_coordinator",
                "coordinator_name": "Scoped Coord",
                "username": "scopedyearcoord",
                "password": "pass12345",
                "module_ids": [str(module.id)],
                "return_anchor": "year-coordinator-create",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/year-coordinators/?year_scope_id={year_scope.id}#year-coordinator-create")

    def test_year_head_cannot_create_coordinator_for_out_of_scope_module(self):
        in_scope = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        out_of_scope = create_module(name="SY1_Sem-1 - Batch 2026-2030", year_level="SY", variant="SY1")
        year_head, year_scope = create_year_head()
        in_scope.year_scope = year_scope
        in_scope.save(update_fields=["year_scope"])
        self.client.force_login(year_head)

        response = self.client.post(
            "/org-setup/",
            {
                "action": "create_coordinator",
                "coordinator_name": "Bad Coord",
                "username": "badcoord",
                "password": "pass12345",
                "module_ids": [str(out_of_scope.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="badcoord").exists())

    def test_year_head_can_update_coordinator_from_org_setup(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        coordinator = create_coordinator(module, username="editcoord")
        self.client.force_login(year_head)

        response = self.client.post(
            "/org-setup/",
            {
                "action": "update_coordinator",
                "coordinator_id": str(coordinator.id),
                "coordinator_name": "Edited Coord",
                "username": "editcoord2",
                "new_password": "newpass123",
                "is_active": "1",
                "module_ids": [str(module.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        coordinator.refresh_from_db()
        self.assertEqual(coordinator.username, "editcoord2")
        self.assertEqual(coordinator.first_name, "Edited Coord")

    def test_year_head_can_delete_coordinator_from_org_setup(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        coordinator = create_coordinator(module, username="deletecoord")
        self.client.force_login(year_head)

        response = self.client.post(
            "/org-setup/",
            {
                "action": "delete_coordinator",
                "coordinator_id": str(coordinator.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(id=coordinator.id).exists())

    def test_manage_mentors_shows_faculty_from_active_timetable(self):
        module = create_module()
        superadmin = create_superadmin()
        self.client.force_login(superadmin)
        upload = TimetableUpload.objects.create(module=module, is_active=True)
        Mentor.objects.create(name="HDS", full_name="Hardik D. Shah", department="FY2")
        TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.get("/manage-mentors/")

        self.assertEqual(response.status_code, 200)
        row_names = [row["mentor"].name for row in response.context["rows"]]
        self.assertIn("HDS", row_names)

    def test_manage_mentors_recovers_from_stale_session_module_selection(self):
        module = create_module()
        superadmin = create_superadmin()
        self.client.force_login(superadmin)
        Mentor.objects.create(name="HDS", department="FY2")
        session = self.client.session
        session["current_module_id"] = 999999
        session.save()

        response = self.client.get("/manage-mentors/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["current_module_id"], module.id)

    def test_manage_mentors_post_preserves_anchor(self):
        module = create_module()
        superadmin = create_superadmin(username="mentoranchoradmin")
        mentor = Mentor.objects.create(name="HDS", full_name="Hardik Shah", department="FY2")
        upload = TimetableUpload.objects.create(module=module, is_active=True)
        TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        self.client.force_login(superadmin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/manage-mentors/",
            {
                "action": "remove_from_dept",
                "mentor_id": str(mentor.id),
                "return_anchor": "mentors-list",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/manage-mentors/#mentors-list")

    def test_manage_mentors_post_preserves_year_scope_and_anchor(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        mentor = Mentor.objects.create(name="HDS", full_name="Hardik Shah", department="FY2")
        upload = TimetableUpload.objects.create(module=module, is_active=True)
        TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        self.client.force_login(year_head)

        response = self.client.post(
            f"/manage-mentors/?module_id={module.id}&year_scope_id={year_scope.id}",
            {
                "action": "remove_from_dept",
                "mentor_id": str(mentor.id),
                "return_anchor": "mentors-list",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"module_id={module.id}", response.url)
        self.assertIn(f"year_scope_id={year_scope.id}", response.url)
        self.assertTrue(response.url.endswith("#mentors-list"))

    def test_year_head_attendance_analytics_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/attendance-analytics/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_daily_absent_live_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/attendance-analytics/daily-live/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_weekly_attendance_live_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/attendance-analytics/weekly-live/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_upload_faculty_is_superadmin_only(self):
        module = create_module()
        coordinator = create_coordinator(module)
        self.client.force_login(coordinator)

        response = self.client.get("/upload-faculty/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/reports/")

    def test_upload_faculty_update_preserves_anchor(self):
        superadmin, _ = create_year_head(username="facultyanchoryearhead")
        mentor = Mentor.objects.create(name="HDS", full_name="Hardik Shah", department="FY2")
        self.client.force_login(superadmin)

        response = self.client.post(
            "/upload-faculty/",
            {
                "action": "update_faculty",
                "mentor_id": str(mentor.id),
                "full_name": "Hardik D Shah",
                "department": "FY2",
                "phone": "9999999999",
                "email": "hds@example.com",
                "faculty_type": "Faculty",
                "status": "Working",
                "return_anchor": "faculty-records",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/upload-faculty/#faculty-records")

    def test_year_head_upload_timetable_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/upload-timetable/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_upload_timetable_post_preserves_year_scope_and_anchor(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        upload = TimetableUpload.objects.create(module=module, is_active=True)
        TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        self.client.force_login(year_head)

        response = self.client.post(
            f"/upload-timetable/?module_id={module.id}&year_scope_id={year_scope.id}",
            {
                "action": "delete_all",
                "return_anchor": "timetable-uploads",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"module_id={module.id}", response.url)
        self.assertIn(f"year_scope_id={year_scope.id}", response.url)
        self.assertTrue(response.url.endswith("#timetable-uploads"))

    def test_upload_timetable_delete_preserves_anchor(self):
        year_head, year_scope = create_year_head(username="timetableanchoryearhead")
        module = create_module()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        upload = TimetableUpload.objects.create(module=module, is_active=True, source_name="demo.xlsx")
        TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/upload-timetable/",
            {
                "action": "delete_all",
                "return_anchor": "timetable-uploads",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/upload-timetable/#timetable-uploads")

    def test_manage_rooms_add_preserves_anchor(self):
        year_head, year_scope = create_year_head(username="roomsanchoryearhead")
        module = create_module()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/manage-rooms/",
            {
                "action": "add",
                "name": "517-A",
                "return_anchor": "rooms-add",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/manage-rooms/#rooms-add")

    def test_view_timetable_undo_preserves_recent_query_and_anchor(self):
        admin = create_superadmin()
        module = create_module()
        upload = TimetableUpload.objects.create(module=module, is_active=True)
        entry = TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        TimetableChangeLog.objects.create(
            module=module,
            timetable_entry=entry,
            change_group="group123",
            change_type=TimetableChangeLog.TYPE_PROXY,
            day_of_week=entry.day_of_week,
            lecture_no=entry.lecture_no,
            batch=entry.batch,
            prev_subject="DBMS",
            prev_faculty="HDS",
            prev_room="516-B",
            prev_time_slot="08:45-09:45",
            new_subject="IOT",
            new_faculty="ABC",
            new_room="517-A",
            new_time_slot="08:45-09:45",
            created_by=admin.username,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/view-timetable/?recent=1",
            {
                "action": "undo_change",
                "change_group": "group123",
                "return_anchor": "recent-changes",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/view-timetable/?recent=1#recent-changes")

    def test_control_panel_post_preserves_anchor(self):
        admin = create_superadmin()
        module = create_module()
        self.client.force_login(admin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            "/control-panel/",
            {
                "action": "mentor_home",
                "mode": "auto",
                "cutoff_time": "12:35",
                "before_page": "schedule",
                "after_page": "daily_calls",
                "manual_page": "schedule",
                "return_anchor": "mentor-home-settings",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/control-panel/#mentor-home-settings")

    def test_sif_marks_template_post_preserves_enrollment_and_anchor(self):
        admin = create_superadmin()
        module = create_module()
        student_mentor = Mentor.objects.create(name="HDS", full_name="Hardik Shah")
        from core.models import Student
        student = Student.objects.create(
            module=module,
            mentor=student_mentor,
            enrollment="ENR001",
            name="Test Student",
            roll_no=1,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.post(
            f"/sif-marks-template/?enrollment={student.enrollment}",
            {
                "action": "lock",
                "return_anchor": "sif-controls",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/sif-marks-template/?enrollment={student.enrollment}#sif-controls")

    def test_sif_marks_template_post_preserves_year_scope_query_param(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        mentor = Mentor.objects.create(name="SIFYEARMENTOR", full_name="SIF Year Mentor", department="FY2")
        student = Student.objects.create(
            module=module,
            enrollment="SIFYEAR1",
            roll_no=1,
            name="SIF Year Student",
            batch="B-1",
            division="B-1",
            mentor=mentor,
        )
        self.client.force_login(year_head)

        response = self.client.post(
            f"/sif-marks-template/?module_id={module.id}&year_scope_id={year_scope.id}&enrollment={student.enrollment}",
            {
                "action": "lock",
                "return_anchor": "sif-controls",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"module_id={module.id}", response.url)
        self.assertIn(f"year_scope_id={year_scope.id}", response.url)
        self.assertIn(f"enrollment={student.enrollment}", response.url)
        self.assertTrue(response.url.endswith("#sif-controls"))

    def test_year_head_coordinator_result_report_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/result-reports/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_mentor_result_report_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/mentor-result-report/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_view_practical_marks_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/view-practical-marks/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_mentor_report_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        _, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        mentor = Mentor.objects.create(name="MENTORFY2", full_name="Mentor FY2", department="FY2")
        Student.objects.create(
            module=primary_module,
            enrollment="ENRREP001",
            roll_no=1,
            name="Student Report",
            batch="A1",
            division="FY2",
            mentor=mentor,
            father_mobile="9876543210",
            student_mobile="9876543211",
        )
        session = self.client.session
        session["mentor"] = mentor.name
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/mentor-report/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_mentor_sif_marks_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        _, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        mentor = Mentor.objects.create(name="MENTORSIF", full_name="Mentor SIF", department="FY2")
        Student.objects.create(
            module=primary_module,
            enrollment="ENRSIF001",
            roll_no=1,
            name="Student One",
            batch="A1",
            division="FY2",
            mentor=mentor,
            father_mobile="9876543210",
            student_mobile="9876543211",
        )
        SifMarksLock.objects.create(module=primary_module, locked=True)
        session = self.client.session
        session["mentor"] = mentor.name
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/mentor-sif-marks/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)
        self.assertContains(
            response,
            f"/mentor-sif-marks-pdf-all/?module_id={primary_module.id}&year_scope_id={year_scope.id}",
            html=False,
        )

    def test_mentor_view_sif_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY2-CE_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY3_Sem-1 - Batch 2026-2030", variant="FY3")
        _, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        mentor = Mentor.objects.create(name="MENTORVIEW", full_name="Mentor View", department="FY2")
        student = Student.objects.create(
            module=primary_module,
            enrollment="ENRVIEW001",
            roll_no=1,
            name="Student View",
            batch="A1",
            division="FY2",
            mentor=mentor,
            father_mobile="9876543210",
            student_mobile="9876543211",
        )
        session = self.client.session
        session["mentor"] = mentor.name
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(
            f"/mentor-view-sif/?year_scope_id={year_scope.id}&enrollment={student.enrollment}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)
        self.assertContains(
            response,
            f"/mentor-prefilled-sif/{student.enrollment}/?module_id={primary_module.id}&year_scope_id={year_scope.id}",
            html=False,
        )

    def test_year_head_view_timetable_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/view-timetable/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_year_head_coordinator_daily_weekly_report_uses_selected_year_scope_query_param(self):
        primary_module = create_module(name="FY1_Sem-1 - Batch 2026-2030")
        alternate_module = create_module(name="FY2_Sem-1 - Batch 2026-2030", variant="FY2")
        year_head, year_scope = create_year_head()
        primary_module.year_scope = year_scope
        primary_module.save(update_fields=["year_scope"])
        alternate_module.year_scope = year_scope
        alternate_module.save(update_fields=["year_scope"])
        self.client.force_login(year_head)
        session = self.client.session
        session["current_module_id"] = primary_module.id
        session.save()

        response = self.client.get(f"/coordinator-daily-weekly-report/?year_scope_id={year_scope.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module"].id, primary_module.id)
        self.assertEqual(response.context["selected_year_scope_id"], str(year_scope.id))
        self.assertContains(response, f'name="year_scope_id" value="{year_scope.id}"', html=False)

    def test_view_timetable_post_preserves_year_scope_query_param(self):
        module = create_module()
        year_head, year_scope = create_year_head()
        module.year_scope = year_scope
        module.save(update_fields=["year_scope"])
        upload = TimetableUpload.objects.create(module=module, is_active=True)
        TimetableEntry.objects.create(
            module=module,
            upload=upload,
            day_of_week=0,
            lecture_no=1,
            time_slot="08:45-09:45",
            batch="B-1",
            subject="DBMS",
            faculty="HDS",
            room="516-B",
            is_active=True,
        )
        self.client.force_login(year_head)

        response = self.client.post(
            f"/view-timetable/?module_id={module.id}&year_scope_id={year_scope.id}&recent=1",
            {
                "action": "undo_change",
                "change_group": "missing-group",
                "return_anchor": "recent-changes",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/view-timetable/?"))
        self.assertIn(f"module_id={module.id}", response.url)
        self.assertIn(f"year_scope_id={year_scope.id}", response.url)
        self.assertIn("recent=1", response.url)
        self.assertTrue(response.url.endswith("#recent-changes"))

    def test_coordinator_adjustments_post_preserves_week_query_and_anchor(self):
        admin = create_superadmin()
        module = create_module()
        adjustment = LectureAdjustment.objects.create(
            module=module,
            date=timezone.localdate(),
            batch="B-1",
            lecture_no=1,
            time_slot="08:45-09:45",
            subject="DBMS",
            original_faculty="HDS",
            room="516-B",
            adjustment_type=LectureAdjustment.TYPE_ROOM,
            status=LectureAdjustment.STATUS_ACTIVE,
        )
        self.client.force_login(admin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()
        week_start = adjustment.date - timedelta(days=adjustment.date.weekday())

        response = self.client.post(
            f"/coordinator-adjustments/?start_date={week_start:%Y-%m-%d}",
            {
                "action": "cancel",
                "adjustment_id": str(adjustment.id),
                "return_anchor": "adjustments-list",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/coordinator-adjustments/?start_date={week_start:%Y-%m-%d}#adjustments-list")


@override_settings(SECURE_SSL_REDIRECT=False)
class ExamSectionTests(TestCase):
    def test_coordinator_can_create_exam_session_and_timetable_entry(self):
        module = create_module()
        coordinator = create_coordinator(module, username="examcoordinator1")
        subject = Subject.objects.create(module=module, name="Mathematics", short_name="MATHS")
        self.client.force_login(coordinator)

        response = self.client.post(
            f"/exam-section/?module_id={module.id}",
            {
                "action": "create_session",
                "module_id": str(module.id),
                "test_name": "T1",
                "title": "T1 March",
            },
        )

        self.assertEqual(response.status_code, 302)
        session = ModuleExamSession.objects.get(module=module, test_name="T1")
        response = self.client.post(
            f"/exam-section/?module_id={module.id}&test_name=T1",
            {
                "action": "create_entry",
                "module_id": str(module.id),
                "session_id": str(session.id),
                "subject_id": str(subject.id),
                "exam_date": "2026-03-25",
                "start_time": "10:00",
                "end_time": "11:00",
                "entry_deadline": "2026-03-26T18:00",
                "max_marks": "25",
                "pass_marks": "9",
                "total_pass_marks": "9",
            },
        )

        self.assertEqual(response.status_code, 302)
        entry = ExamTimetableEntry.objects.get(session=session, subject=subject)
        self.assertEqual(str(entry.max_marks), "25.0")
        self.assertEqual(str(entry.pass_marks), "9.0")

    def test_exam_evaluator_can_save_decimal_and_ab_marks(self):
        module = create_module()
        subject = Subject.objects.create(module=module, name="Physics", short_name="PHY")
        mentor = Mentor.objects.create(name="PHYFAC", full_name="Physics Faculty")
        student1 = Student.objects.create(module=module, mentor=mentor, enrollment="ENR001", roll_no=1, name="A Student", batch="B1")
        student2 = Student.objects.create(module=module, mentor=mentor, enrollment="ENR002", roll_no=2, name="B Student", batch="B1")
        evaluator = User.objects.create_user(username="phy", password="pass12345", is_active=True)
        ExamFacultyProfile.objects.create(user=evaluator, mentor=mentor, short_code="PHY", full_name="Physics Faculty")
        session = ModuleExamSession.objects.create(module=module, test_name="T1", created_by=evaluator)
        entry = ExamTimetableEntry.objects.create(
            session=session,
            subject=subject,
            exam_date=timezone.localdate(),
            start_time=(timezone.localtime() - timedelta(hours=1)).time().replace(second=0, microsecond=0),
            end_time=(timezone.localtime() + timedelta(hours=1)).time().replace(second=0, microsecond=0),
            entry_deadline=timezone.now() + timedelta(hours=2),
            max_marks=25,
            pass_marks=9,
            total_pass_marks=9,
        )
        block = ExamBlock.objects.create(timetable_entry=entry, evaluator=evaluator, block_type=ExamBlock.TYPE_MANUAL, name="PHY-B1")
        ExamBlockStudent.objects.create(block=block, student=student1)
        ExamBlockStudent.objects.create(block=block, student=student2)
        self.client.force_login(evaluator)

        response = self.client.post(
            f"/exam-section/marks/{block.id}/",
            {
                f"mark_{student1.id}": "9.5",
                f"mark_{student2.id}": "AB",
            },
        )

        self.assertEqual(response.status_code, 302)
        row1 = ExamMarkEntry.objects.get(block=block, student=student1)
        row2 = ExamMarkEntry.objects.get(block=block, student=student2)
        self.assertEqual(float(row1.marks_obtained), 9.5)
        self.assertFalse(row1.is_absent)
        self.assertTrue(row2.is_absent)

    def test_lock_entry_publishes_manual_marks_to_result_flow(self):
        module = create_module()
        coordinator = create_coordinator(module, username="examcoordinator2")
        subject = Subject.objects.create(module=module, name="Chemistry", short_name="CHEM")
        mentor = Mentor.objects.create(name="CHEMFA", full_name="Chem Faculty")
        student1 = Student.objects.create(module=module, mentor=mentor, enrollment="ENR101", roll_no=1, name="Student 1", batch="B1")
        student2 = Student.objects.create(module=module, mentor=mentor, enrollment="ENR102", roll_no=2, name="Student 2", batch="B1")
        evaluator = User.objects.create_user(username="chem", password="pass12345", is_active=True)
        ExamFacultyProfile.objects.create(user=evaluator, mentor=mentor, short_code="CHE", full_name="Chem Faculty")
        session = ModuleExamSession.objects.create(module=module, test_name="T1", created_by=coordinator)
        entry = ExamTimetableEntry.objects.create(
            session=session,
            subject=subject,
            exam_date=timezone.localdate(),
            start_time=(timezone.localtime() - timedelta(hours=1)).time().replace(second=0, microsecond=0),
            end_time=(timezone.localtime() + timedelta(hours=1)).time().replace(second=0, microsecond=0),
            entry_deadline=timezone.now() + timedelta(hours=2),
            max_marks=25,
            pass_marks=9,
            total_pass_marks=9,
        )
        block = ExamBlock.objects.create(timetable_entry=entry, evaluator=evaluator, block_type=ExamBlock.TYPE_MANUAL, name="CHEM-B1")
        ExamBlockStudent.objects.create(block=block, student=student1)
        ExamBlockStudent.objects.create(block=block, student=student2)
        ExamMarkEntry.objects.create(timetable_entry=entry, block=block, student=student1, evaluator=evaluator, raw_value="11.5", marks_obtained=11.5)
        ExamMarkEntry.objects.create(timetable_entry=entry, block=block, student=student2, evaluator=evaluator, raw_value="AB", is_absent=True)
        self.client.force_login(coordinator)

        response = self.client.post(
            f"/exam-section/?module_id={module.id}&test_name=T1",
            {
                "action": "lock_entry",
                "module_id": str(module.id),
                "timetable_entry_id": str(entry.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        upload = ResultUpload.objects.get(module=module, test_name="T1", subject=subject)
        self.assertEqual(StudentResult.objects.filter(upload=upload).count(), 2)
        self.assertTrue(ExamTimetableEntry.objects.get(id=entry.id).is_locked)

    def test_updating_seating_block_resyncs_evaluator_marks_students(self):
        module = create_module()
        coordinator = create_coordinator(module, username="examcoordinator3")
        subject = Subject.objects.create(module=module, name="Biology", short_name="BIO")
        mentor = Mentor.objects.create(name="BIOFAC", full_name="Biology Faculty")
        student1 = Student.objects.create(module=module, mentor=mentor, enrollment="ENR201", roll_no=1, name="Student 1", batch="CE")
        student2 = Student.objects.create(module=module, mentor=mentor, enrollment="ENR202", roll_no=2, name="Student 2", batch="CE")
        eval1 = User.objects.create_user(username="bio1", password="pass12345", is_active=True)
        eval2 = User.objects.create_user(username="bio2", password="pass12345", is_active=True)
        ExamFacultyProfile.objects.create(user=eval1, mentor=mentor, short_code="B01", full_name="Bio 1")
        ExamFacultyProfile.objects.create(user=eval2, short_code="B02", full_name="Bio 2")
        session = ModuleExamSession.objects.create(module=module, test_name="T1", created_by=coordinator)
        entry = ExamTimetableEntry.objects.create(
            session=session,
            subject=subject,
            exam_date=timezone.localdate(),
            start_time=(timezone.localtime() - timedelta(hours=1)).time().replace(second=0, microsecond=0),
            end_time=(timezone.localtime() + timedelta(hours=1)).time().replace(second=0, microsecond=0),
            entry_deadline=timezone.now() + timedelta(hours=2),
            max_marks=25,
            pass_marks=9,
            total_pass_marks=9,
        )
        seating1 = ExamSeatingBlock.objects.create(
            session=session,
            delivery_mode=ExamSeatingBlock.MODE_OFFLINE,
            block_number="1",
            room="A1",
            block_type=ExamSeatingBlock.TYPE_ENROLLMENT_RANGE,
            name="Block 1",
            enrollment_start="ENR201",
            enrollment_end="ENR201",
            is_preview=False,
            created_by=coordinator,
        )
        ExamSeatingBlock.objects.create(
            session=session,
            delivery_mode=ExamSeatingBlock.MODE_OFFLINE,
            block_number="2",
            room="A2",
            block_type=ExamSeatingBlock.TYPE_ENROLLMENT_RANGE,
            name="Block 2",
            enrollment_start="ENR202",
            enrollment_end="ENR202",
            is_preview=False,
            created_by=coordinator,
        )
        block1 = ExamBlock.objects.create(
            timetable_entry=entry,
            evaluator=eval1,
            delivery_mode=ExamBlock.MODE_OFFLINE,
            block_number="1",
            room="A1",
            block_type=ExamBlock.TYPE_ENROLLMENT_RANGE,
            name="Block 1",
            enrollment_start="ENR201",
            enrollment_end="ENR201",
            created_by=coordinator,
        )
        block2 = ExamBlock.objects.create(
            timetable_entry=entry,
            evaluator=eval2,
            delivery_mode=ExamBlock.MODE_OFFLINE,
            block_number="2",
            room="A2",
            block_type=ExamBlock.TYPE_ENROLLMENT_RANGE,
            name="Block 2",
            enrollment_start="ENR202",
            enrollment_end="ENR202",
            created_by=coordinator,
        )
        ExamBlockStudent.objects.create(block=block1, student=student1)
        ExamBlockStudent.objects.create(block=block2, student=student2)
        self.client.force_login(coordinator)

        response = self.client.post(
            f"/exam-section/?module_id={module.id}&test_name=T1",
            {
                "action": "update_seating_block",
                "seating_block_id": str(seating1.id),
                "delivery_mode": "offline",
                "block_number": "1",
                "dept_label": "",
                "room": "A1",
                "lab": "",
                "block_type": "range",
                "enrollment_start": "ENR202",
                "enrollment_end": "ENR202",
                "manual_enrollments": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ExamBlockStudent.objects.filter(block=block1, student=student1).exists())
        self.assertTrue(ExamBlockStudent.objects.filter(block=block1, student=student2).exists())
        self.assertFalse(ExamBlockStudent.objects.filter(block=block2, student=student2).exists())
