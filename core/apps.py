from django.apps import AppConfig
import os


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        username = (os.getenv("COORDINATOR_USERNAME") or "").strip()
        password = (os.getenv("COORDINATOR_PASSWORD") or "").strip()
        email = (os.getenv("COORDINATOR_EMAIL") or "admin@example.com").strip()

        if not username or not password:
            return

        try:
            from django.contrib.auth import get_user_model
            from django.db import connection
            from django.db.utils import OperationalError, ProgrammingError

            # Avoid DB lookups while auth tables are not ready.
            table_names = connection.introspection.table_names()
            if "auth_user" not in table_names:
                return

            User = get_user_model()
            if not User.objects.filter(username=username).exists():
                User.objects.create_superuser(
                    username=username,
                    email=email,
                    password=password,
                )
        except (OperationalError, ProgrammingError):
            return
