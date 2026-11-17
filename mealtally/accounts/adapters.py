from allauth.account.adapter import DefaultAccountAdapter


class ClosedAccountAdapter(DefaultAccountAdapter):
    """No self-signup in v1: users are created by platform admins / tenant owners."""

    def is_open_for_signup(self, request):
        return False
