# SPDX-License-Identifier: AGPL-3.0-only
"""Languages: every visible template string is translatable, the picker sets the language (and remembers it for
signed-in users), the restaurant's default applies otherwise, and right-to-left languages get dir="rtl"."""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import translation

from mealtally.web.i18n_check import scan
from mealtally.web.i18n_check import untranslated

APP = Path(__file__).resolve().parents[2]


def test_no_untranslated_template_text():
    found = {}
    for sub in ("web/templates", "preview/templates", "templates"):
        root = APP / sub
        if root.exists():
            found.update(scan(root))
    assert found == {}, "mark these for translation with {% trans %} / {% blocktrans %}: " + repr(found)


def test_checker_catches_plain_text_and_attributes():
    assert untranslated('<p>Hello there</p><input placeholder="Your name">') == ["Your name", "Hello there"]
    assert untranslated('{% load i18n %}<p>{% trans "Hello" %}</p><img alt="Mealtally">') == []
    assert untranslated('<a class="[&>svg]:h-5" href="#">{% trans "Go" %}</a>') == []


def test_language_list():
    codes = [c for c, _ in settings.LANGUAGES]
    assert codes[:2] == ["en", "hi"]
    assert {"ar", "mr", "ta", "te", "bn", "gu", "kn", "es", "fr", "pt-br", "id"} <= set(codes)
    assert set(settings.MEALTALLY_BETA_LANGUAGES) == set(codes) - {"en", "hi"}
    assert translation.get_language_info("ar")["bidi"] is True


@pytest.mark.django_db
def test_picker_sets_cookie_and_saves_preference(client, django_user_model):
    user = django_user_model.objects.create_user(email="lang@example.com", password="x-long-password-1")
    client.force_login(user)
    r = client.post("/i18n/setlang/", {"language": "ar", "next": "/"})
    assert r.status_code == 302
    assert r.cookies[settings.LANGUAGE_COOKIE_NAME].value == "ar"
    user.refresh_from_db()
    assert user.preferred_language == "ar"


@pytest.mark.django_db
def test_picker_rejects_unknown_language(client):
    r = client.post("/i18n/setlang/", {"language": "xx", "next": "/"})
    assert settings.LANGUAGE_COOKIE_NAME not in r.cookies


@pytest.mark.django_db
@override_settings(MEALTALLY_MARKETING_SITE=True)
def test_rtl_page(client):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "ar"
    body = client.get("/").content.decode()
    assert 'dir="rtl"' in body and 'lang="ar"' in body
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    assert 'dir="ltr"' in client.get("/").content.decode()


def test_restaurant_default_and_user_preference():
    from types import SimpleNamespace

    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from mealtally.web.views_language import activate_preferred

    tenant = SimpleNamespace(default_language="hi")
    with translation.override("en"):
        req = RequestFactory().get("/")
        req.user = AnonymousUser()
        activate_preferred(req, tenant)
        assert translation.get_language() == "hi"
        req.user = SimpleNamespace(is_authenticated=True, preferred_language="ta")
        activate_preferred(req, tenant)
        assert translation.get_language() == "ta"
        translation.activate("en")
        req = RequestFactory().get("/", HTTP_COOKIE=f"{settings.LANGUAGE_COOKIE_NAME}=fr")
        req.user = AnonymousUser()
        activate_preferred(req, tenant)  # a choice made on this device wins
        assert translation.get_language() == "en"


def test_compiled_catalogs_match_the_po_files():
    """`make messages` compiles the .mo files that ship in git; a stale .mo means a translation never reaches users."""
    import polib

    root = Path(settings.BASE_DIR) / "locale"
    pos = sorted(root.glob("*/LC_MESSAGES/django.po"))
    assert len(pos) == len(settings.LANGUAGES) - 1  # every language except the English source
    for po_path in pos:
        po = polib.pofile(str(po_path))
        mo = polib.mofile(str(po_path.with_suffix(".mo")))
        shipped = {e.msgid for e in po if e.msgstr or any(e.msgstr_plural.values())}
        assert {e.msgid for e in mo if e.msgid} == shipped, f"run `make messages`: {po_path.parent.parent.name}"


def test_hindi_is_complete_and_beta_languages_are_marked_fuzzy():
    import polib

    root = Path(settings.BASE_DIR) / "locale"
    hi = polib.pofile(str(root / "hi/LC_MESSAGES/django.po"))
    assert hi.untranslated_entries() == []
    assert hi.fuzzy_entries() == []
    for code in settings.MEALTALLY_BETA_LANGUAGES:
        po = polib.pofile(str(root / translation.to_locale(code) / "LC_MESSAGES/django.po"))
        assert len(po.fuzzy_entries()) >= 200, code  # noqa: PLR2004  the core set is drafted
        assert not po.translated_entries(), code  # drafts stay fuzzy until a native speaker reviews them
