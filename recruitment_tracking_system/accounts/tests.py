from django.contrib.auth import get_user_model
from django.test import TestCase


class LoginChooserTests(TestCase):
    def test_root_shows_login_chooser_for_anonymous(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Choose Login")

    def test_root_redirects_platform_superadmin(self):
        User = get_user_model()
        admin = User.objects.create_superuser(username="platform_admin_root", password="pw", email="root@example.com")
        self.client.force_login(admin)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/super-admin/dashboard/", resp.headers.get("Location", ""))

