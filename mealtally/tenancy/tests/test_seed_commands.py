import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from mealtally.customers.models import Customer
from mealtally.ledger import services as ledger
from mealtally.passes.models import Pass
from mealtally.tenancy import services as tenancy
from mealtally.testing import World

pytestmark = pytest.mark.django_db


def test_seed_demo_builds_five_realistic_states_and_is_idempotent(capsys):
    w = World(slug="pilot-demo", buy_pass=False)
    call_command("seed_demo", "--slug", "pilot-demo")
    out = capsys.readouterr().out
    assert out.count("DEMO CREDENTIALS") == 5 and "Pilot Tiffin (test)" in out
    with w.ctx():
        by_name = {c.full_name: c for c in Customer.objects.filter(full_name__startswith="Demo")}
        state = {
            n: [(p.status, p.meals_remaining) for p in Pass.objects.filter(customer=c).order_by("starts_at")]
            for n, c in by_name.items()
        }
        assert state["Demo Fresh"] == [("ACTIVE", 30)]
        assert state["Demo Mid-use"] == [("ACTIVE", 18)]
        assert state["Demo Near expiry"] == [("ACTIVE", 3)]
        assert state["Demo Expired"] == [("EXPIRED", 0)]
        assert state["Demo Queued"] == [("ACTIVE", 26), ("QUEUED", 0)]
        assert tenancy.get_settings(w.tenant.id).display_name == "Pilot Tiffin (test)"
        assert ledger.find_mismatches() == []
    call_command("seed_demo", "--slug", "pilot-demo")
    assert "DEMO CREDENTIALS" not in capsys.readouterr().out
    with pytest.raises(CommandError):
        call_command("seed_demo", "--slug", "nope")
