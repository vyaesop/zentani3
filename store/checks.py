import sys

from django.conf import settings
from django.core.checks import Error, Warning, register

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


@register()
def deployment_safety_checks(app_configs, **kwargs):
    issues = []

    # Catch accidental sqlite usage in serverless production.
    if getattr(settings, "IS_VERCEL", False):
        engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
        if engine.endswith("sqlite3"):
            issues.append(
                Error(
                    "Vercel deployment is using sqlite3.",
                    hint="Set a valid DATABASE_URL for Postgres in Vercel environment variables.",
                    id="store.E001",
                )
            )

        if not getattr(settings, "HAS_VALID_CLOUDINARY_CONFIG", False):
            issues.append(
                Error(
                    "Cloudinary configuration is missing or invalid on Vercel.",
                    hint="Set valid CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET values.",
                    id="store.E002",
                )
            )

        if PILImage is None:
            issues.append(
                Error(
                    "Pillow is not available in this deployment.",
                    hint="Install Pillow in requirements.txt so image uploads can be converted to WebP.",
                    id="store.E003",
                )
            )

    # Customer messaging: a production store with the console email backend
    # silently drops password resets, receipts and restock alerts. The test
    # runner forces DEBUG off, so skip these under `manage.py test`.
    running_tests = len(sys.argv) > 1 and sys.argv[1] == "test"
    if not settings.DEBUG and not running_tests:
        email_backend = getattr(settings, "EMAIL_BACKEND", "")
        if email_backend.endswith("console.EmailBackend") or email_backend.endswith("dummy.EmailBackend"):
            issues.append(
                Warning(
                    "EMAIL_BACKEND is the console backend in production: password resets, order receipts and restock alerts are never delivered.",
                    hint="Set EMAIL_HOST (+ EMAIL_HOST_USER / EMAIL_HOST_PASSWORD) for any SMTP provider.",
                    id="store.W002",
                )
            )
        if (getattr(settings, "SMS_BACKEND", "disabled") or "disabled") in {"", "disabled", "console"}:
            issues.append(
                Warning(
                    "SMS_BACKEND is disabled: customers get no order confirmation or dispatch SMS.",
                    hint="Set SMS_BACKEND=afromessage (with AFROMESSAGE_TOKEN) or SMS_BACKEND=http.",
                    id="store.W003",
                )
            )
        if not getattr(settings, "SITE_URL", ""):
            issues.append(
                Warning(
                    "SITE_URL is empty: canonical tags, the sitemap, feeds and message links fall back to the request host.",
                    hint="Set SITE_URL to the public https origin (custom domain).",
                    id="store.W004",
                )
            )

    # Keep local developers aware when placeholder values are present.
    if not getattr(settings, "HAS_VALID_CLOUDINARY_CONFIG", False):
        issues.append(
            Warning(
                "Cloudinary is disabled because credentials are missing or placeholders.",
                hint="Media uploads on read-only serverless environments require valid Cloudinary credentials.",
                id="store.W001",
            )
        )

    return issues
