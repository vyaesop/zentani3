"""Compile locale/*/LC_MESSAGES/django.po into django.mo without GNU gettext.

Django only reads compiled .mo files, and the Vercel build image (and most
Windows laptops) do not ship `msgfmt`. This is a minimal, dependency-free
writer for the GNU .mo format covering plain and plural entries.

    python manage.py compile_translations
"""
import array
import ast
import os
import struct

from django.conf import settings
from django.core.management.base import BaseCommand


def _parse_po(path):
    """Return {msgid: msgstr} (plural forms joined with NUL, like msgfmt)."""
    entries = {}
    msgid = msgid_plural = None
    msgstr = {}
    section = None
    fuzzy = False

    def flush():
        nonlocal msgid, msgid_plural, msgstr, fuzzy
        if msgid is not None and not fuzzy:
            if msgid_plural is not None:
                key = msgid + "\0" + msgid_plural
                value = "\0".join(msgstr[index] for index in sorted(msgstr))
            else:
                key = msgid
                value = msgstr.get(0, "")
            if key == "" or value:
                entries[key] = value
        msgid = msgid_plural = None
        msgstr = {}
        fuzzy = False

    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line.startswith("#,") and "fuzzy" in line:
                    fuzzy = True
                continue
            if line.startswith("msgid_plural"):
                section = ("plural", None)
                msgid_plural = ast.literal_eval(line[len("msgid_plural"):].strip())
                continue
            if line.startswith("msgid"):
                flush()
                section = ("id", None)
                msgid = ast.literal_eval(line[len("msgid"):].strip())
                continue
            if line.startswith("msgstr["):
                index = int(line[len("msgstr["):line.index("]")])
                section = ("str", index)
                msgstr[index] = ast.literal_eval(line[line.index("]") + 1:].strip())
                continue
            if line.startswith("msgstr"):
                section = ("str", 0)
                msgstr[0] = ast.literal_eval(line[len("msgstr"):].strip())
                continue
            if line.startswith('"'):
                text = ast.literal_eval(line)
                if section is None:
                    continue
                kind, index = section
                if kind == "id":
                    msgid += text
                elif kind == "plural":
                    msgid_plural += text
                else:
                    msgstr[index] = msgstr.get(index, "") + text
    flush()
    return entries


def _write_mo(entries, path):
    keys = sorted(entries)
    ids = b""
    strs = b""
    offsets = []
    for key in keys:
        encoded_id = key.encode("utf-8")
        encoded_str = entries[key].encode("utf-8")
        offsets.append((len(ids), len(encoded_id), len(strs), len(encoded_str)))
        ids += encoded_id + b"\0"
        strs += encoded_str + b"\0"

    count = len(keys)
    key_start = 7 * 4 + 16 * count
    value_start = key_start + len(ids)
    key_offsets = []
    value_offsets = []
    for id_offset, id_length, str_offset, str_length in offsets:
        key_offsets += [id_length, key_start + id_offset]
        value_offsets += [str_length, value_start + str_offset]
    header = struct.pack(
        "Iiiiiii",
        0x950412DE,  # magic
        0,  # version
        count,
        7 * 4,  # offset of key table
        7 * 4 + count * 8,  # offset of value table
        0,
        0,
    )
    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(array.array("i", key_offsets).tobytes())
        handle.write(array.array("i", value_offsets).tobytes())
        handle.write(ids)
        handle.write(strs)


class Command(BaseCommand):
    help = "Compile every django.po under LOCALE_PATHS into django.mo (no gettext needed)."

    def handle(self, *args, **options):
        compiled = 0
        for locale_root in getattr(settings, "LOCALE_PATHS", []):
            if not os.path.isdir(locale_root):
                continue
            for language in sorted(os.listdir(locale_root)):
                po_path = os.path.join(locale_root, language, "LC_MESSAGES", "django.po")
                if not os.path.isfile(po_path):
                    continue
                entries = _parse_po(po_path)
                mo_path = os.path.join(locale_root, language, "LC_MESSAGES", "django.mo")
                _write_mo(entries, mo_path)
                compiled += 1
                self.stdout.write(f"{language}: {len(entries)} message(s) -> {mo_path}")
        if not compiled:
            self.stdout.write(self.style.WARNING("No django.po files found under LOCALE_PATHS."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Compiled {compiled} catalogue(s)."))
