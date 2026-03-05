from cryptography.fernet import Fernet
import os

def get_cipher():
    key = os.environ.get("VAULT_ENCRYPTION_KEY")
    if not key:
        raise ValueError("VAULT_ENCRYPTION_KEY not set")
    return Fernet(key.encode())

def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    return get_cipher().encrypt(plaintext.encode()).decode()

def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return get_cipher().decrypt(ciphertext.encode()).decode()
