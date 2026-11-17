# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from mealtally.testing import World


def login_as(user) -> APIClient:
    client = APIClient()
    client.force_login(user, backend="mealtally.accounts.backends.IdentifierPasswordBackend")
    return client


@pytest.fixture
def w(db):
    world = World(slug="pilot")
    with world.ctx():  # the seeded customer has already changed the temporary PIN (D02.1 Q2 enforces it otherwise)
        world.customer.must_change_pin = False
        world.customer.save()
    return world


@pytest.fixture
def base(w):
    return f"/api/v1/t/{w.tenant.slug}"


@pytest.fixture
def owner_client(w):
    return login_as(w.owner.user)


@pytest.fixture
def staff_client(w):
    return login_as(w.staff.user)


@pytest.fixture
def manager_client(w):
    return login_as(w.manager.user)
