# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from django.contrib.auth.base_user import BaseUserManager

from mealtally.common.country import normalize_phone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, phone_e164, password, **extra):
        email = self.normalize_email(email).lower() if email else None
        phone = normalize_phone(phone_e164) if phone_e164 else None
        if not email and not phone:
            msg = "A user needs an email or a phone number."
            raise ValueError(msg)
        user = self.model(email=email, phone_e164=phone, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email=None, phone_e164=None, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, phone_e164, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, is_platform_admin=True)
        return self._create(email, None, password, **extra)
