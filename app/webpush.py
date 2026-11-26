import base64
import json
import os
import struct
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text):
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _raw_public(pub):
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def new_vapid_key():
    key = ec.generate_private_key(ec.SECP256R1())
    num = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u(num)


def _load_private(b64):
    return ec.derive_private_key(int.from_bytes(unb64u(b64), "big"), ec.SECP256R1())


def vapid_public(b64_private):
    return b64u(_raw_public(_load_private(b64_private).public_key()))


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload, ua_public_b64, auth_b64, as_private=None, salt=None):
    ua_public = unb64u(ua_public_b64)
    auth = unb64u(auth_b64)
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_private.public_key())
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_private.exchange(ec.ECDH(), peer)
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    rs = 4096
    return salt + struct.pack(">IB", rs, len(as_public)) + as_public + record


def _vapid_header(endpoint, b64_private, subject):
    u = urllib.parse.urlsplit(endpoint)
    aud = f"{u.scheme}://{u.netloc}"
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": subject},
                           separators=(",", ":")).encode())
    signing = f"{head}.{body}".encode()
    der = _load_private(b64_private).sign(signing, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{body}.{sig}, k={vapid_public(b64_private)}"


def send(sub, data, b64_private, subject="mailto:faar-manager@users.noreply.github.com", ttl=3600, urgency="high"):
    import requests
    keys = sub.get("keys", {})
    body = encrypt(json.dumps(data).encode(), keys["p256dh"], keys["auth"])
    headers = {
        "Authorization": _vapid_header(sub["endpoint"], b64_private, subject),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": urgency,
    }
    r = requests.post(sub["endpoint"], data=body, headers=headers, timeout=15)
    return r.status_code
