import hmac
import hashlib

def test_webhook_signature_contract():
    """Verify HMAC signature format contract."""
    secret = 'secret_key'
    body = b'{"event": "ping"}'
    
    # Contract: HMAC signature should start with 'sha256=' followed by hex digest
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    formatted_signature = f'sha256={signature}'
    
    assert formatted_signature.startswith('sha256=')
    assert len(formatted_signature) == 7 + 64 # 'sha256=' + 64 chars sha256 hex
