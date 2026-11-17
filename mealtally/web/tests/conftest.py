# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest
from django.test import Client

from mealtally.testing import World

B = "mealtally.accounts.backends.IdentifierPasswordBackend"


def client_for(user, backend=B):
    c = Client()
    c.force_login(user, backend=backend)
    return c


@pytest.fixture
def w(db):
    return World(slug="webt")


@pytest.fixture
def u(w):
    return f"/t/{w.tenant.slug}"


@pytest.fixture
def owner_c(w):
    return client_for(w.owner.user)


@pytest.fixture
def manager_c(w):
    return client_for(w.manager.user)


@pytest.fixture
def staff_c(w):
    return client_for(w.staff.user)


@pytest.fixture
def cust_c(w):
    return client_for(w.customer.user, "mealtally.accounts.backends.CustomerPinBackend")
