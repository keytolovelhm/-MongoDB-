from datetime import timedelta
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from .errors import fail
from .repositories import utcnow
from .security import normalize_username, password_hash, verify_password, new_token, token_hash


class AuthService:
    def __init__(self, store, settings): self.store, self.settings = store, settings

    @staticmethod
    def public(user): return {'id': str(user['_id']), 'username': user['username']}

    def register(self, data):
        name = normalize_username(data.username)
        if len(name) < 3 or any(not (c.isalnum() or c in '_-') for c in name):
            fail('username_invalid', '用户名为3至40个字母、数字、汉字、下划线或连字符', field='username')
        doc = {'_id': ObjectId(), 'username': data.username.strip(), 'usernameNormalized': name,
               'passwordHash': password_hash(data.password), 'createdAt': utcnow(), 'schemaVersion': 1}
        try: self.store.users.insert(doc)
        except DuplicateKeyError: fail('username_exists', '用户名已存在', 409, 'username')
        return self.public(doc)

    def login(self, data):
        user = self.store.users.by_name(normalize_username(data.username))
        if not user or not verify_password(user['passwordHash'], data.password):
            fail('login_failed', '用户名或密码错误', 401)
        raw, now = new_token(), utcnow()
        self.store.sessions.insert({'_id': ObjectId(), 'userId': user['_id'], 'tokenHash': token_hash(raw), 'createdAt': now,
                                    'expiresAt': now + timedelta(hours=self.settings.session_hours), 'schemaVersion': 1})
        return self.public(user), raw

    def authenticate(self, raw):
        session = self.store.sessions.get({'tokenHash': token_hash(raw)}) if raw else None
        if not session or session['expiresAt'] <= utcnow():
            fail('login_required', '请先登录，登录已失效时请重新登录', 401)
        user = self.store.users.get({'_id': session['userId']})
        if not user: fail('login_required', '账号不存在', 401)
        return user

    def logout(self, raw):
        self.store.db.sessions.delete_one({'tokenHash': token_hash(raw)})
