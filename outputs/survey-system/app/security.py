from hashlib import sha256
import hmac
import secrets
import unicodedata
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def password_hash(password): return HASHER.hash(password)


def verify_password(hashed, password):
    try: return HASHER.verify(hashed, password)
    except (VerificationError, InvalidHashError): return False


def normalize_username(name): return unicodedata.normalize('NFKC', name).strip().casefold()


def new_token(): return secrets.token_urlsafe(32)


def token_hash(token): return sha256(token.encode()).hexdigest()


def keyed(secret, purpose, value): return hmac.new(secret.encode(), f'{purpose}:{value}'.encode(), sha256).hexdigest()


def respondent_key(secret, survey_id, user_id): return keyed(secret, 'respondent-v1', f'{survey_id}:{user_id}')


def csrf_token(secret, token): return keyed(secret, 'csrf', token)
