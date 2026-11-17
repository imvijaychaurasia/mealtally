"""Create (or reset) a platform administrator; the generated password is printed once."""

import secrets

from django.core.management.base import BaseCommand

from mealtally.accounts.models import User
from mealtally.tenancy.context import platform_context


class Command(BaseCommand):
    help = "Create a platform admin (can log into /platform/admin/ and /api/v1/platform/)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--reset-password", action="store_true")

    def handle(self, *args, **opts):
        email = opts["email"].strip().lower()
        with platform_context():
            user = User.objects.filter(email=email).first()
            if user is None:
                password = secrets.token_urlsafe(18)
                user = User.objects.create_superuser(email=email, password=password, name="Platform Admin")
                self.stdout.write(self.style.WARNING(f"CREDENTIALS (shown once)  login={email}  password={password}"))
            elif opts["reset_password"]:
                password = secrets.token_urlsafe(18)
                user.set_password(password)
                user.is_platform_admin = user.is_staff = user.is_superuser = True
                user.save()
                self.stdout.write(self.style.WARNING(f"CREDENTIALS (shown once)  login={email}  password={password}"))
            else:
                self.stdout.write(f"{email} already exists (use --reset-password to rotate).")
