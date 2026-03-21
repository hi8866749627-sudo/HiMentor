from django.test import TestCase, override_settings

from core.models import Mentor, TimetableEntry, TimetableUpload
from core.qa_test_helpers import create_coordinator, create_module, create_superadmin


@override_settings(SECURE_SSL_REDIRECT=False)
class ManageMentorsAndAccessTests(TestCase):
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

    def test_upload_faculty_is_superadmin_only(self):
        module = create_module()
        coordinator = create_coordinator(module)
        self.client.force_login(coordinator)

        response = self.client.get("/upload-faculty/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/reports/")

    def test_superadmin_home_shows_full_legacy_backup_button(self):
        module = create_module()
        superadmin = create_superadmin()
        self.client.force_login(superadmin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.get("/home/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Download Full Legacy Backup')
        self.assertContains(response, '/live-followup-sheet/db-backup-json/', html=False)

    def test_legacy_backup_download_uses_legacy_filename(self):
        module = create_module()
        superadmin = create_superadmin()
        self.client.force_login(superadmin)
        session = self.client.session
        session["current_module_id"] = module.id
        session.save()

        response = self.client.get("/live-followup-sheet/db-backup-json/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn('himentor_legacy_full_backup_', response["Content-Disposition"])
