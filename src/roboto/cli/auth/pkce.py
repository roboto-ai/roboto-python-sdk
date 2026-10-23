# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import base64
import dataclasses
import hashlib
import secrets


def s256_challenge(verifier: str) -> str:
    """Return the RFC 7636 S256 code challenge for ``verifier``: unpadded base64url of its SHA-256 digest."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """Return a random, URL-safe value with 256 bits of entropy for matching a redirect to its request."""
    return secrets.token_urlsafe(32)


@dataclasses.dataclass(frozen=True)
class PkcePair:
    """A PKCE (Proof Key for Code Exchange, RFC 7636) code verifier and its S256 challenge.

    The challenge is sent when a credential request starts; the verifier is revealed only when redeeming the request's
    code, so an intercepted code is useless to anyone but the process that generated the pair.
    """

    verifier: str
    challenge: str

    @classmethod
    def generate(cls) -> "PkcePair":
        """Return a pair built from a new random verifier."""
        # 64 random bytes encode to 86 base64url characters, inside RFC 7636's 43-128 range.
        verifier = secrets.token_urlsafe(64)
        return cls(verifier=verifier, challenge=s256_challenge(verifier))
