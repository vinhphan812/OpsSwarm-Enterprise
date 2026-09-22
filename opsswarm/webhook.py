from __future__ import annotations
import hashlib,hmac,json

def verify_signature(secret:str,body:bytes,signature:str|None)->bool:
    if not secret: return False
    if not signature or not signature.startswith("sha256="): return False
    expected="sha256="+hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)
