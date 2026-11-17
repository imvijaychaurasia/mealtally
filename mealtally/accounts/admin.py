from django import forms
from django.contrib import admin

from .admin_site import PlatformModelAdmin
from .models import Membership
from .models import User


class UserAdminForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the current password (min 10 characters). Customers have none.",
    )

    class Meta:
        model = User
        fields = ["email", "phone_e164", "name", "is_active", "is_staff", "is_platform_admin"]

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            from django.contrib.auth.password_validation import validate_password  # noqa: PLC0415

            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_unusable_password()
        if user.is_platform_admin:
            user.is_staff = True
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(PlatformModelAdmin):
    form = UserAdminForm
    list_display = ("id", "email", "phone_e164", "name", "is_active", "is_platform_admin")
    search_fields = ("email", "phone_e164", "name")
    list_filter = ("is_active", "is_platform_admin")


@admin.register(Membership)
class MembershipAdmin(PlatformModelAdmin):
    list_display = ("id", "tenant", "user", "role", "is_active")
    list_filter = ("tenant", "role", "is_active")
    search_fields = ("user__email", "user__phone_e164")
    raw_id_fields = ("user",)
