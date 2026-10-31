from django.core.management.base import BaseCommand, CommandError

from store.models import SupplierChannel
from store.services.supplier_intake import IntakeError, ingest_channel, mark_on_site, run_daily


class Command(BaseCommand):
    help = (
        "Daily supplier intake: scrape the supplier channels, expire stale reviews, "
        "and send the newest posts to the admin bot (see store/services/supplier_intake.py)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--scrape-only",
            action="store_true",
            help="Only store new posts; no Gemini, no Telegram. For backfills.",
        )
        parser.add_argument(
            "--on-site",
            nargs="+",
            default=[],
            metavar="CHANNEL/ID[=NOTE]",
            help="Mark scraped posts as already on the site, e.g. adots_wear/3034=adot092.",
        )

    def handle(self, *args, **options):
        if options["scrape_only"]:
            for channel in SupplierChannel.objects.filter(is_active=True):
                created = ingest_channel(channel)
                self.stdout.write(f"{channel.username}: {created} new listing(s).")
        elif not options["on_site"]:
            summary = run_daily(log=self.stdout.write)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{summary['created']} new listing(s), {summary['sent']} sent for review, "
                    f"{summary['expired']} expired."
                )
            )
            if summary["errors"]:
                # Fail the scheduled run loudly so a dead channel gets noticed.
                raise SystemExit(f"Scrape errors: {'; '.join(summary['errors'])}")

        for spec in options["on_site"]:
            ref, _, note = spec.partition("=")
            channel, _, message_id = ref.partition("/")
            if not message_id.isdigit():
                raise CommandError(f"Expected CHANNEL/ID, got {spec!r}.")
            try:
                post = mark_on_site(channel, int(message_id), note)
            except IntakeError as exc:
                raise CommandError(str(exc))
            self.stdout.write(f"{post} marked as already on the site.")
