from datetime import datetime, timezone
from decimal import Decimal
from bson import ObjectId
from bson.decimal128 import Decimal128
from pymongo import MongoClient, ReturnDocument
from .errors import fail
from .schema import ensure_schema


def utcnow():
    return datetime.now(timezone.utc)


def oid(value):
    try: return ObjectId(value)
    except Exception: fail('not_found', '资源不存在', 404)


def to_bson(value):
    if isinstance(value, Decimal): return Decimal128(value)
    if isinstance(value, dict): return {k: to_bson(v) for k, v in value.items()}
    if isinstance(value, list): return [to_bson(v) for v in value]
    return value


def from_bson(value):
    if isinstance(value, Decimal128): return value.to_decimal()
    if isinstance(value, dict): return {k: from_bson(v) for k, v in value.items()}
    if isinstance(value, list): return [from_bson(v) for v in value]
    return value


def wire(value):
    if isinstance(value, ObjectId): return str(value)
    if isinstance(value, (Decimal128, Decimal)): return str(value.to_decimal() if isinstance(value, Decimal128) else value)
    if isinstance(value, datetime): return value.isoformat().replace('+00:00', 'Z')
    if isinstance(value, dict): return {('id' if k == '_id' else k): wire(v) for k, v in value.items()}
    if isinstance(value, list): return [wire(v) for v in value]
    return value


class Repository:
    def __init__(self, collection): self.collection = collection

    def get(self, query):
        doc = self.collection.find_one(query)
        return from_bson(doc) if doc else None

    def insert(self, doc):
        self.collection.insert_one(to_bson(doc))
        return doc

    def change(self, query, changes):
        result = self.collection.find_one_and_update(query, {'$set': to_bson(changes), '$inc': {'revision': 1}}, return_document=ReturnDocument.AFTER)
        return from_bson(result) if result else None


class Users(Repository):
    def by_name(self, name): return self.get({'usernameNormalized': name})


class Surveys(Repository):
    def owned(self, survey_id, owner):
        survey = self.get({'_id': oid(survey_id), 'ownerId': owner})
        if not survey: fail('not_found', '问卷不存在或无权访问', 404)
        return survey

    def by_slug(self, slug):
        survey = self.get({'shareSlug': slug})
        if not survey: fail('not_found', '问卷不存在', 404)
        return survey

    def listing(self, owner, skip, limit):
        query = {'ownerId': owner}
        docs = self.collection.find(query, {'questions': 0}).sort([('updatedAt', -1), ('_id', -1)]).skip(skip).limit(limit)
        return list(docs), self.collection.count_documents(query)


class Responses(Repository):
    def recent(self, survey_id, respondent):
        return [from_bson(d) for d in self.collection.find({'surveyId': survey_id, 'respondentKey': respondent},
                {'answers': 0, 'respondentKey': 0, 'identifiedUserId': 0, 'submissionDigest': 0}).sort([('startedAt', -1), ('_id', -1)]).limit(50)]


class Store:
    def __init__(self, settings):
        self.client = MongoClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=3000, connectTimeoutMS=3000)
        self.db = self.client[settings.database]
        self.client.admin.command('ping')
        ensure_schema(self.db)
        self.users, self.surveys = Users(self.db.users), Surveys(self.db.surveys)
        self.responses, self.sessions = Responses(self.db.responses), Repository(self.db.sessions)

    def close(self): self.client.close()
