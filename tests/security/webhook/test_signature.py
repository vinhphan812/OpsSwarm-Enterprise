import hashlib
import hmac

import pytest

from opsswarm.webhook import verify_signature


@pytest.mark.security
def test_signature():
    body = b'{}';
    secret = 'abc';
    sig = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, sig)
    assert not verify_signature(secret, body, 'sha256=bad')
