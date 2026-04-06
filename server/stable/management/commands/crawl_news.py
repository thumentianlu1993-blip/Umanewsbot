from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from stable.tasks import (
    crawl_jra_news,
    crawl_netkeiba_access,
    crawl_netkeiba_attention,
    crawl_netkeiba_latest,
)


class Command(BaseCommand):
    help = "Run a crawl task manually."

    def add_arguments(self, parser):
        parser.add_argument("target", choices=["netkeiba_latest", "netkeiba_access", "netkeiba_attention", "jra"])
        parser.add_argument("--pages", type=int, default=3)

    def handle(self, *args, **options):
        target = options["target"]
        if target == "netkeiba_latest":
            result = crawl_netkeiba_latest(max_pages=options["pages"])
        elif target == "netkeiba_access":
            result = crawl_netkeiba_access()
        elif target == "netkeiba_attention":
            result = crawl_netkeiba_attention()
        elif target == "jra":
            result = crawl_jra_news()
        else:
            raise CommandError("Unknown target")
        self.stdout.write(self.style.SUCCESS(str(result)))
