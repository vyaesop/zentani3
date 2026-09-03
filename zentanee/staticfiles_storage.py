"""Static storage that appends a content-hash query string to every URL.

Manifest (hashed-filename) storage was ruled out because vendored CSS carries
relative references to files that are not shipped, which makes collectstatic
fail. Appending `?v=<hash>` to the URL instead keeps the on-disk names stable
(so vendor CSS keeps resolving) while still busting caches whenever a file's
bytes change. That is what lets vercel.json serve /static/ with a one-year
`immutable` Cache-Control header.
"""
import hashlib
import os

from django.contrib.staticfiles import finders

try:
    from whitenoise.storage import CompressedStaticFilesStorage as _Base
except ImportError:  # pragma: no cover - whitenoise is in requirements.txt
    from django.contrib.staticfiles.storage import StaticFilesStorage as _Base


class VersionedCompressedStaticFilesStorage(_Base):
    _version_cache = {}

    def _file_path(self, name):
        try:
            candidate = self.path(name)
        except (NotImplementedError, ValueError):
            candidate = None
        if candidate and os.path.isfile(candidate):
            return candidate
        # Development (`runserver` without collectstatic): resolve through the
        # finders so the hash still reflects the source file.
        found = finders.find(name)
        if found and os.path.isfile(found):
            return found
        return None

    def _version(self, name):
        cached = self._version_cache.get(name)
        if cached is not None:
            return cached
        path = self._file_path(name)
        if not path:
            self._version_cache[name] = ""
            return ""
        digest = hashlib.md5()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        version = digest.hexdigest()[:10]
        self._version_cache[name] = version
        return version

    def url(self, name, force=False):
        base = super().url(name)
        if not name or "?" in base:
            return base
        version = self._version(name)
        if not version:
            return base
        return f"{base}?v={version}"
