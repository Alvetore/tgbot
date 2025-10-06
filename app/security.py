import hmac, hashlib
from cryptography.fernet import Fernet
from .config import settings

def hash_user_id(raw_id: int) -> str:
    msg = str(raw_id).encode("utf-8")
    key = settings.user_id_salt.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

fernet = Fernet(settings.feedback_fernet_key.encode()) if settings.feedback_fernet_key else None

def encrypt_feedback(text: str) -> bytes:
    if not fernet:
        return text.encode("utf-8")
    return fernet.encrypt(text.encode("utf-8"))

def decrypt_feedback(blob: bytes) -> str:
    if not fernet:
        return blob.decode("utf-8", errors="ignore")
    return fernet.decrypt(blob).decode("utf-8")
