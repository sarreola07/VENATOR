"""Message authentication for the C2 link.

Without this, anything in radio range that speaks the protocol is
indistinguishable from the operator's own ground station — LoRa is a broadcast
medium and the radio parameters are published in this repo because both ends
must agree on them. See docs/SECURITY.md.

Each message carries a nonce and a truncated HMAC-SHA256 over its canonical
form. A receiver with a key drops anything that does not verify, before it
reaches the dispatcher.

**Off unless a key exists.** No key file means no signing and no verification,
which is exactly how the link behaved before this module. Put the same key on
both machines and it becomes mandatory on both. That way deploying this changes
nothing until you choose a moment to switch it on, with both ends in front of
you, rather than needing a flag day.

Stdlib only.
"""
import hmac
import json
import os
import secrets
from hashlib import sha256
from pathlib import Path

# Where the key lives. Outside the repo, deliberately: a key in a working tree
# gets committed eventually.
DEFAULT_KEY_FILE = Path.home() / ".venator" / "key"
KEY_FILE_ENV = "VENATOR_KEY_FILE"

SIG_FIELD = "m"        # the tag
NONCE_FIELD = "n"      # per-message, so a captured packet cannot be replayed
SIG_HEX = 16           # 64 bits of tag. A forgery has to be found online,
                       # against a link that carries a few packets a second.
NONCE_HEX = 8          # 32 bits, only needs to be unique within the window
REPLAY_WINDOW = 512    # nonces remembered per receiver


def key_path():
    return Path(os.environ.get(KEY_FILE_ENV, DEFAULT_KEY_FILE))


def load_key(path=None):
    """The shared key, or None if there is no key file — which means the link
    runs unauthenticated, as it did before."""
    p = Path(path) if path else key_path()
    try:
        raw = p.read_bytes().strip()
    except OSError:
        return None
    return raw or None


def create_key(path=None):
    """Write a new random key, readable only by this user. Returns its path."""
    p = Path(path) if path else key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 0600 from the start rather than after writing: no window where it is
    # world-readable.
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(secrets.token_hex(32) + "\n")
    return p


def _canonical(msg):
    """The exact bytes both ends sign. sort_keys so dict order cannot change the
    tag; the signature and nonce are not part of what is signed except that the
    nonce is added first and then covered."""
    body = {k: v for k, v in msg.items() if k != SIG_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(msg, key):
    """Return a copy of msg carrying a nonce and a tag."""
    signed = dict(msg)
    signed[NONCE_FIELD] = secrets.token_hex(NONCE_HEX // 2)
    tag = hmac.new(key, _canonical(signed), sha256).hexdigest()[:SIG_HEX]
    signed[SIG_FIELD] = tag
    return signed


def verify(msg, key, seen=None):
    """True if msg carries a valid tag and its nonce has not been used.

    `seen` is a caller-owned list used as a bounded replay window. Pass the same
    list every time for one receiver."""
    tag = msg.get(SIG_FIELD)
    if not isinstance(tag, str):
        return False
    want = hmac.new(key, _canonical(msg), sha256).hexdigest()[:SIG_HEX]
    if not hmac.compare_digest(tag, want):
        return False
    if seen is not None:
        nonce = msg.get(NONCE_FIELD)
        if not isinstance(nonce, str) or nonce in seen:
            return False        # replayed, or no nonce to judge by
        seen.append(nonce)
        del seen[:-REPLAY_WINDOW]
    return True


def strip(msg):
    """The message as the application should see it, without the auth fields."""
    return {k: v for k, v in msg.items() if k not in (SIG_FIELD, NONCE_FIELD)}


if __name__ == "__main__":
    import sys
    if "--init" in sys.argv:
        p = create_key()
        print("Wrote a new key to {} (mode 0600).".format(p))
        print("Copy it to the other machine at the same path, then restart both "
              "ends. Until both have it, the one with a key will reject the "
              "other's messages.")
    else:
        k = load_key()
        print("key file: {}".format(key_path()))
        print("status  : {}".format(
            "present - the link is authenticated" if k else
            "missing - THE LINK IS UNAUTHENTICATED (see docs/SECURITY.md)"))
        print("\nCreate one with:  python3 radio/auth.py --init")
