from django.test import TestCase, override_settings

from core.qa_test_helpers import create_coordinator, create_module, create_superadmin


@override_settings(SECURE_SSL_REDIRECT=False)
class MobileStaffApiTests(TestCase):
    def test_staff_login_allows_superadmin_and_returns_role(self):
        create_module()
        create_superadmin(password="pass12345")

        response = self.client.post(
            "/api/mobile/staff/login/",
            data={"username": "superadmin1", "password": "pass12345"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["role"], "superadmin")
        self.assertTrue(payload["token"])

    def test_staff_login_denies_plain_user_without_module_access(self):
        from django.contrib.auth.models import User

        User.objects.create_user(username="plain", password="pass12345")

        response = self.client.post(
            "/api/mobile/staff/login/",
            data={"username": "plain", "password": "pass12345"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["msg"], "Access denied")

    def test_staff_modules_endpoint_returns_only_assigned_modules(self):
        module = create_module()
        coordinator = create_coordinator(module, password="pass12345")
        login = self.client.post(
            "/api/mobile/staff/login/",
            data={"username": coordinator.username, "password": "pass12345"},
            content_type="application/json",
        )
        token = login.json()["token"]

        response = self.client.get(
            "/api/mobile/staff/modules/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["role"], "coordinator")
        self.assertEqual(len(payload["modules"]), 1)
        self.assertEqual(payload["modules"][0]["module_id"], module.id)
