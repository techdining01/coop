"""
Minimal field-level encryption for sensitive KYC data (BVN, NIN).

Uses Fernet (symmetric, authenticated encryption) from the `cryptography`
package. The key comes from settings.FIELD_ENCRYPTION_KEY and must never be
committed to source control — see .env.example.

This is deliberately simple rather than pulling in a third-party encrypted-
fields package, since the requirement here is narrow: encrypt a couple of
short identity-number fields at rest, decrypt transparently in Python,
never log or expose the raw value outside code that explicitly needs it.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _get_fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


class EncryptedCharField(models.CharField):
    """
    Stores an encrypted value in the database; encrypts on save, decrypts
    on load. Transparent to the rest of the app — read/write it like any
    other CharField. The stored column is wider than max_length to account
    for encryption overhead.
    """

    def __init__(self, *args, **kwargs):
        # Encrypted ciphertext is longer than the plaintext — pad generously.
        kwargs.setdefault("max_length", 255)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        fernet = _get_fernet()
        return fernet.encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        fernet = _get_fernet()
        try:
            return fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            # Value wasn't encrypted with the current key (e.g. corrupted
            # data or a key rotation without re-encryption). Fail loudly
            # rather than silently returning ciphertext as if it were the
            # real BVN/NIN.
            raise ValueError(
                "Could not decrypt field value — FIELD_ENCRYPTION_KEY may "
                "have changed, or the stored value is corrupted."
            )

    def to_python(self, value):
        return value
