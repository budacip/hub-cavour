"""Command fingerprints for service-scoped idempotency.

Command ids are unique within one application service: OrderEngine and
TableSessionService deliberately keep separate command ledgers for this MVP.
"""

from dataclasses import asdict
from hashlib import sha256
import json


def command_fingerprint(command: object) -> str:
    payload = {
        "type": f"{type(command).__module__}.{type(command).__qualname__}",
        "payload": asdict(command),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()
