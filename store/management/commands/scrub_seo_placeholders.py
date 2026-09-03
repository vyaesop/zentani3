"""Remove leaked AI template text ("| [Store Name]") from live product copy.

    python manage.py scrub_seo_placeholders          # report only
    python manage.py scrub_seo_placeholders --apply  # rewrite the fields
"""
from django.core.management.base import BaseCommand

from store.models import Product
from store.seo import clean_seo_copy, has_placeholder
from store.telegram_notify import suspend_telegram_autopublish

FIELDS = ("title", "short_description", "detail_description", "seo_title", "seo_description", "image_alt_text")


class Command(BaseCommand):
    help = "Find (and with --apply, clean) products whose copy still contains template placeholders."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the cleaned copy back to the database.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        touched = 0
        for product in Product.objects.all().order_by("id"):
            dirty_fields = [name for name in FIELDS if has_placeholder(getattr(product, name, ""))]
            if not dirty_fields:
                continue
            touched += 1
            self.stdout.write(f"#{product.id} {product.title!r}: {', '.join(dirty_fields)}")
            for name in dirty_fields:
                before = getattr(product, name) or ""
                after = clean_seo_copy(before, fallback="" if name != "title" else product.title)
                self.stdout.write(f"    {name}: {before!r} -> {after!r}")
                if apply_changes:
                    setattr(product, name, after)
            if apply_changes:
                with suspend_telegram_autopublish():
                    product.save(update_fields=[*dirty_fields, "updated_at"])
        if not touched:
            self.stdout.write(self.style.SUCCESS("No placeholder text found."))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Cleaned {touched} product(s)."))
        else:
            self.stdout.write(self.style.WARNING(f"{touched} product(s) need cleaning. Re-run with --apply."))
