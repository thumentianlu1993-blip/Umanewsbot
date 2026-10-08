"""Independently reviewed private career row: real dry-run or atomic commit."""
import argparse
from contextlib import ExitStack
import json
import re
import subprocess
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from stable.services.horse_basic_profile_prepare_input import _root, _CapturedInputs, _strict_json, _reject
from stable.services.horse_career_record_from_review import consume_reviewed_career_record


def _positive(value):
    if not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise argparse.ArgumentTypeError('actor-id must be a positive integer')
    return int(value)


class Command(BaseCommand):
    help = 'Consume one independently reviewed private HKJC career row; no source fetch or publication.'
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--commit', action='store_true')
        for key in ('input-root', 'review-root', 'review-input', 'expected-reviewed-input-sha256',
                    'expected-source-row-sha256', 'code-sha'):
            parser.add_argument('--' + key, required=True)
        parser.add_argument('--actor-id', type=_positive, required=True)

    def handle(self, *args, **options):
        if bool(options['dry_run']) == bool(options['commit']):
            raise CommandError('exactly_one_mode_required')
        try:
            executing_sha = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parent, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            raise CommandError('execution_code_unavailable') from None
        if options['code_sha'] != executing_sha:
            raise CommandError('execution_code_mismatch')
        capture = _CapturedInputs()
        with ExitStack() as stack:
            source_fd = stack.enter_context(_root(options['input_root'], 'input_path', private=True))
            review_fd = stack.enter_context(_root(options['review_root'], 'input_path', private=True))
            reviewed = capture.read(review_fd, options['review_input'], options['expected_reviewed_input_sha256'])
            decision = _strict_json(reviewed)
            if type(decision) is not dict or type(decision.get('inputs')) is not dict:
                _reject('review_inputs')
            try:
                packet = capture.read(source_fd, decision['inputs']['packet']['path'], decision['inputs']['packet']['sha256'])
                raw = capture.read(source_fd, decision['inputs']['cache']['path'], decision['inputs']['cache']['sha256'])
            except (KeyError, TypeError):
                _reject('review_inputs')
            actor = get_user_model().objects.filter(pk=options['actor_id']).first()
            result = consume_reviewed_career_record(packet=packet, source_raw=raw, reviewed_raw=reviewed,
                expected_review_sha256=options['expected_reviewed_input_sha256'],
                expected_row_sha256=options['expected_source_row_sha256'], actor=actor,
                code_sha=options['code_sha'], dry_run=options['dry_run'])
            if result['status'] == 'blocked':
                raise CommandError(result['reason'])
        # Deliberately after commit: BrokenPipe must retain actual durable facts.
        self.stdout.write(json.dumps(result, sort_keys=True, allow_nan=False))
