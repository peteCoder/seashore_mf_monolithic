"""
Custom Authentication Backend
==============================

Authenticates users by employee_id (Staff ID) + password instead of email.

Accepted kwargs:
- ``staff_id`` — used by the web login form
- ``username``  — used by Django admin login and DRF AuthTokenSerializer;
                   both map to ``employee_id`` on the User model.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class StaffIDBackend(ModelBackend):
    """
    Authenticate against User.employee_id instead of email.

    Accepts both ``staff_id`` (web form) and ``username`` (Django admin /
    DRF token endpoint) so every entry-point works with a single backend.
    """

    def authenticate(self, request, staff_id=None, username=None, password=None, **kwargs):
        # Resolve the lookup value from either kwarg
        lookup = staff_id or username
        if not lookup or not password:
            return None

        # Try employee_id first (web login / DRF token)
        user = User.objects.filter(employee_id=lookup).first()

        # Fall back to email lookup so Django admin (/admin/) works
        if user is None:
            user = User.objects.filter(email=lookup).first()

        if user is None:
            # Run a dummy password hash to mitigate timing attacks
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    # get_user() is inherited from ModelBackend — no override needed.
