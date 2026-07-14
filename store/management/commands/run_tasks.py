import time

from django.core.management.base import BaseCommand

from store.tasks import run_pending


class Command(BaseCommand):
    help = "Drain the background task queue (single pass by default, --forever for a worker loop)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Max tasks per pass.")
        parser.add_argument("--forever", action="store_true", help="Keep polling instead of exiting after one pass.")
        parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between passes in --forever mode.")

    def handle(self, *args, **options):
        limit = options["limit"]
        if not options["forever"]:
            processed = run_pending(limit=limit)
            self.stdout.write(self.style.SUCCESS(f"Processed {processed} task(s)."))
            return

        self.stdout.write("Task worker started (Ctrl+C to stop).")
        try:
            while True:
                processed = run_pending(limit=limit)
                if processed:
                    self.stdout.write(f"Processed {processed} task(s).")
                else:
                    time.sleep(options["sleep"])
        except KeyboardInterrupt:
            self.stdout.write("Task worker stopped.")
