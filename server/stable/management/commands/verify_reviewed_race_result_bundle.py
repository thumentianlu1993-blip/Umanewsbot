from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "独立 verify 已审核赛果包。"

    def add_arguments(self, parser):
        parser.add_argument("--bundle-dir", required=True)
        parser.add_argument("--expected-bundle-sha256", required=True)
        parser.add_argument("--approve", action="append", default=[])

    def handle(self, *args, **options):
        call_command(
            "apply_reviewed_race_result_bundle",
            bundle_dir=options["bundle_dir"],
            expected_bundle_sha256=options["expected_bundle_sha256"],
            approve=options["approve"],
            verify=True,
            stdout=self.stdout,
        )
