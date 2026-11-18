# SPDX-License-Identifier: AGPL-3.0-only
"""makemessages without fuzzy matching: a guessed translation would be shown to users of the Beta languages."""

from django.core.management.commands.makemessages import Command as BaseCommand


class Command(BaseCommand):
    msgmerge_options = [*BaseCommand.msgmerge_options, "--no-fuzzy-matching"]
