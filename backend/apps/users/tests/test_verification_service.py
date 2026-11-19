import time
from unittest.mock import patch
from uuid import uuid4

from django.core import signing
from django.test import TestCase

from apps.users.services.verification import (
    VERIFICATION_TOKEN_MAX_AGE,
    VERIFICATION_TOKEN_SALT,
    generate_verification_token,
    verify_verification_token,
)


class VerificationTokenTests(TestCase):
    def test_generate_and_verify_token_successfully(self):
        user_id = uuid4()

        token = generate_verification_token(user_id)

        self.assertIsInstance(token, str)
        self.assertEqual(verify_verification_token(token), user_id)

    def test_tampered_token_returns_none(self):
        token = generate_verification_token(uuid4())
        tampered_token = token + "tampered"

        self.assertIsNone(verify_verification_token(tampered_token))

    def test_expired_token_returns_none(self):
        user_id = uuid4()
        expired_timestamp = time.time() - VERIFICATION_TOKEN_MAX_AGE - 1

        with patch(
            "django.core.signing.time.time",
            return_value=expired_timestamp,
        ):
            token = generate_verification_token(user_id)

        self.assertIsNone(verify_verification_token(token))

    def test_token_with_missing_user_id_returns_none(self):
        token = signing.dumps(
            {},
            salt=VERIFICATION_TOKEN_SALT,
            compress=True,
        )

        self.assertIsNone(verify_verification_token(token))

    def test_token_with_invalid_user_id_returns_none(self):
        token = signing.dumps(
            {"user_id": "not-a-valid-uuid"},
            salt=VERIFICATION_TOKEN_SALT,
            compress=True,
        )

        self.assertIsNone(verify_verification_token(token))

    def test_token_signed_with_wrong_salt_returns_none(self):
        token = signing.dumps(
            {"user_id": str(uuid4())},
            salt="another.salt",
            compress=True,
        )

        self.assertIsNone(verify_verification_token(token))