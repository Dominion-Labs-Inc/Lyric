#!/usr/bin/env python3
"""The substrate's keys: one authority over the files that hold them.

Lyric holds credentials for the services it works with (GitHub, Cloudflare and
the rest). They live in key files on disk and nowhere else. This module is the
one place that knows which values are keys, and every path out of the substrate
asks it:

  * what the substrate SAYS            the coordinator's `say`
  * what it REMEMBERS                  the memory agent's writes
  * what a tool is HANDED              the tool registry refuses a key in the
                                       parameters, or a key file as a path
  * what a tool HANDS BACK             the registry redacts it before anything
                                       records the result
  * what a child process INHERITS      the execution tools start it without keys
  * what is LOGGED                     every log record, at creation

So a key leaves only inside the request of the code that owns its service: the
substrate has no route by which to hand one to anything else. That is enforced
here, structurally, and not left to the substrate's judgement.

A setting is a key when its name says so (KEY, TOKEN, SECRET, PASSWORD, ...);
paths, ids, flags and expiry settings are not. Values shorter than eight
characters are never treated as keys, so redaction cannot eat ordinary words.

The substrate may add a key of its own (`hold`): it is written to its own key
file, mode 600, atomically, and the audit records the name, never the value.
A person adds one with `./lyric secret set NAME`, which reads it without echo.
"""
from __future__ import annotations

import base64
import binascii
import functools
import getpass
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

LYRIC_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = LYRIC_ROOT.parent

#: The substrate's own key file, the one it may add to. `.env` is a link to it.
OWN_KEY_FILE = LYRIC_ROOT / ".env.production"

#: Key files whose values the authority holds for redaction. The substrate LOADS
#: only its own; the workspace file holds the company's keys, and redacting them
#: too costs nothing and closes the case where one reaches a tool's output.
KEY_FILES = (OWN_KEY_FILE, LYRIC_ROOT / ".env.postgres", WORKSPACE_ROOT / ".env")

_SECRET_NAME = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|SIGNING|PRIVATE|WEBHOOK|_PAT)(_|$)")
_NOT_A_KEY = re.compile(
    r"(_PATH|_ID|_ENABLED|_URL|_EXPIRE_MINUTES|_EXPIRE_DAYS|_ALGORITHM|_MODEL_ID)$")
_MIN_LENGTH = 8
_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def is_key_name(name: str) -> bool:
    """Whether a setting's name says its value is a key."""
    return bool(_SECRET_NAME.search(name)) and not _NOT_A_KEY.search(name)


def _forms(value: str) -> List[str]:
    """The value and the encodings it is most simply smuggled in."""
    raw = value.encode()
    forms = {value, urllib.parse.quote(value, safe=""), binascii.hexlify(raw).decode()}
    for enc in (base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()):
        forms.add(enc)
        forms.add(enc.rstrip("="))
    return [f for f in forms if len(f) >= _MIN_LENGTH]


class SecretsAuthority:
    """Which values are keys, and keeping them in: the one owner of that answer."""

    def __init__(self, key_files: Iterable[Path] = KEY_FILES,
                 own_file: Path = OWN_KEY_FILE,
                 guarded_root: Path = WORKSPACE_ROOT):
        self._files = tuple(Path(f) for f in key_files)
        self._own = Path(own_file)
        self._root = Path(guarded_root)
        self._lock = threading.RLock()
        self._stamp: Optional[tuple] = None
        self._checked = 0.0
        self._by_form: Dict[str, str] = {}
        self._pattern: Optional[re.Pattern] = None

    # ── what is held ─────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        # Every log record asks, so the files are looked at no more than once a
        # second; `hold` clears the stamp, so a key it adds counts at once.
        now = time.monotonic()
        if self._stamp is not None and now - self._checked < 1.0:
            return
        self._checked = now
        stamp = tuple((str(f), f.stat().st_mtime_ns if f.exists() else None)
                      for f in self._files)
        if stamp == self._stamp:
            return
        from dotenv import dotenv_values
        by_form: Dict[str, str] = {}
        for f in self._files:
            if not f.exists():
                continue
            for name, value in dotenv_values(f).items():
                if value and is_key_name(name) and len(value) >= _MIN_LENGTH:
                    for form in _forms(value):
                        by_form.setdefault(form, name)
        self._by_form = by_form
        self._pattern = (re.compile("|".join(re.escape(f) for f in
                                             sorted(by_form, key=len, reverse=True)))
                         if by_form else None)
        self._stamp = stamp

    def names(self) -> List[str]:
        """The names of the keys held (never their values)."""
        with self._lock:
            self._refresh()
            return sorted(set(self._by_form.values()))

    # ── keeping them in ──────────────────────────────────────────────────────
    def find(self, obj: Any) -> Optional[str]:
        """The name of the first key found anywhere in `obj`, or None."""
        with self._lock:
            self._refresh()
            pattern, by_form = self._pattern, self._by_form
        if pattern is None:
            return None

        def walk(o) -> Optional[str]:
            if isinstance(o, str):
                m = pattern.search(o)
                return by_form[m.group(0)] if m else None
            if isinstance(o, bytes):
                return walk(o.decode("utf-8", "ignore"))
            if isinstance(o, Mapping):
                for k, v in o.items():
                    hit = walk(k) or walk(v)
                    if hit:
                        return hit
                return None
            if isinstance(o, (list, tuple, set, frozenset)):
                for v in o:
                    hit = walk(v)
                    if hit:
                        return hit
            return None
        return walk(obj)

    def redact(self, obj: Any) -> Any:
        """`obj` with every key replaced by `[secret:NAME]`; anything else unchanged."""
        with self._lock:
            self._refresh()
            pattern, by_form = self._pattern, self._by_form
        if pattern is None:
            return obj

        def walk(o):
            if isinstance(o, str):
                return pattern.sub(lambda m: f"[secret:{by_form[m.group(0)]}]", o)
            if isinstance(o, bytes):
                text = o.decode("utf-8", "ignore")
                cleaned = walk(text)
                return o if cleaned == text else cleaned.encode()
            if isinstance(o, dict):
                return {walk(k): walk(v) for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v) for v in o]
            if isinstance(o, tuple):
                return tuple(walk(v) for v in o)
            return o
        return walk(obj)

    def is_key_file(self, path: Any) -> bool:
        """Whether `path` names a file that holds keys: one of the known key files,
        or any `.env*` file under the guarded root other than an example."""
        try:
            resolved = Path(os.path.realpath(os.path.expanduser(str(path))))
        except Exception:
            return False
        known = {Path(os.path.realpath(f)) for f in self._files}
        if resolved in known:
            return True
        name = resolved.name
        if not name.startswith(".env") or name.endswith(".example"):
            return False
        try:
            resolved.relative_to(Path(os.path.realpath(self._root)))
            return True
        except ValueError:
            return False

    def scrubbed_env(self, env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        """An environment for a child process: every key-named variable, and every
        variable holding a key's value, left out."""
        source = dict(os.environ if env is None else env)
        return {k: v for k, v in source.items()
                if not is_key_name(k) and self.find(v) is None}

    # ── adding one ───────────────────────────────────────────────────────────
    def hold(self, name: str, value: str) -> None:
        """Write a key into the substrate's own key file: replaced if the name is
        there, appended if not, mode 600, atomically. Audited by name only."""
        if not _NAME.match(name or ""):
            raise ValueError("a key's name is UPPER_CASE letters, digits and underscores")
        if not value or "\n" in value:
            raise ValueError("a key's value is one non-empty line")
        with self._lock:
            target = Path(os.path.realpath(self._own))
            lines = target.read_text().splitlines() if target.exists() else []
            line = f"{name}={value}"
            replaced = False
            for i, existing in enumerate(lines):
                if existing.split("=", 1)[0].strip() == name:
                    lines[i], replaced = line, True
            if not replaced:
                lines.append(line)
            fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".keys-")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write("\n".join(lines) + "\n")
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            os.environ[name] = value
            self._stamp = None
        logger.info("key %s %s in the substrate's key file", name,
                    "replaced" if replaced else "added")


_authority: Optional[SecretsAuthority] = None


def get_secrets_authority() -> SecretsAuthority:
    """The one authority over the substrate's keys."""
    global _authority
    if _authority is None:
        _authority = SecretsAuthority()
    return _authority


def keyless(fn):
    """The substrate's voice: whatever `fn` returns is said with every key
    replaced by its name. Applied to the one speech path, so no branch of it can
    say a key, whichever branch produced the words."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return get_secrets_authority().redact(fn(*args, **kwargs))
    return wrapper


def install_log_redaction() -> None:
    """Redact keys from every log record, wherever it is logged, as it is made.

    A filter on the root logger would miss records from child loggers (filters
    do not propagate), and one on each handler would miss handlers added later,
    so the record factory itself is wrapped. Installed once per process."""
    if getattr(logging, "_lyric_key_redaction", False):
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        authority = get_secrets_authority()
        try:
            message = record.getMessage()
        except Exception:
            message = None
        if message is not None and authority.find(message):
            record.msg, record.args = authority.redact(message), ()
        # An exception's own text is formatted later, from `exc_info`, and would
        # carry a key past the message check; format it now and keep it clean.
        if record.exc_info and record.exc_info[0] is not None:
            import traceback
            text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
            if authority.find(text):
                record.exc_text = authority.redact(text)
        if record.stack_info and authority.find(record.stack_info):
            record.stack_info = authority.redact(record.stack_info)
        return record

    logging.setLogRecordFactory(factory)
    logging._lyric_key_redaction = True


def _main(argv: List[str]) -> int:
    """`./lyric secret set NAME` reads a key without echo and holds it;
    `./lyric secret names` lists the names held."""
    if len(argv) >= 2 and argv[0] == "set":
        value = getpass.getpass(f"{argv[1]}: ")
        get_secrets_authority().hold(argv[1], value)
        print(f"{argv[1]} held in {OWN_KEY_FILE.name} (mode 600)")
        return 0
    if argv[:1] == ["names"]:
        for name in get_secrets_authority().names():
            print(name)
        return 0
    print("usage: secret set NAME | secret names", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
