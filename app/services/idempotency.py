import hashlib
import json


def request_hash(method: str, path: str, body: dict) -> str:
    """Fingerprint a request so a reused Idempotency-Key can be compared.

    The body is serialised as canonical JSON (sorted keys, no spaces) so
    the same request always hashes the same, whatever its key order.
    """
    canonical_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
    fingerprint = "\n".join([method.upper(), path, canonical_body])
    return hashlib.sha256(fingerprint.encode()).hexdigest()
