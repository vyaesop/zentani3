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
