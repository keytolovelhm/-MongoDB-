"""The executable MongoDB collection validators and indexes (exactly four collections)."""
from bson import BSON
from .errors import fail


S = {'bsonType': 'string'}
I = {'bsonType': ['int', 'long'], 'minimum': 0}
D = {'bsonType': 'date'}
OID = {'bsonType': 'objectId'}
B = {'bsonType': 'bool'}


def obj(properties, required):
    return {'bsonType': 'object', 'required': required, 'additionalProperties': False, 'properties': properties}


OPTION = obj({'optionId': S, 'label': S}, ['optionId', 'label'])
CONDITION = obj({'op': {'enum': ['eq', 'contains_any', 'contains_all', 'set_equals', 'gt', 'gte', 'lt', 'lte', 'between']},
                 'value': {'oneOf': [S, {'bsonType': 'array', 'items': S}]}}, ['op', 'value'])
RULE = obj({'ruleId': S, 'priority': I, 'condition': CONDITION, 'target': S}, ['ruleId', 'priority', 'condition', 'target'])
CONSTRAINTS = obj({**{k: {'bsonType': ['int', 'null'], 'minimum': 0} for k in ['minSelections', 'maxSelections', 'minLength', 'maxLength']},
                   'minValue': {'bsonType': ['string', 'null']}, 'maxValue': {'bsonType': ['string', 'null']}, 'integerOnly': B}, ['integerOnly'])
QUESTION = obj({'questionId': S, 'order': I, 'title': S, 'type': {'enum': ['SINGLE', 'MULTI', 'TEXT', 'NUMBER']},
                'required': B, 'options': {'bsonType': 'array', 'maxItems': 100, 'items': OPTION},
                'constraints': CONSTRAINTS, 'rules': {'bsonType': 'array', 'maxItems': 50, 'items': RULE}},
               ['questionId', 'order', 'title', 'type', 'required', 'options', 'constraints', 'rules'])
ANSWER = obj({'questionId': S, 'selectedOptionId': S, 'selectedOptionIds': {'bsonType': 'array', 'items': S, 'uniqueItems': True},
              'textValue': S, 'numberValue': {'bsonType': 'decimal'}}, ['questionId'])
ANSWER['maxProperties'] = 2

SCHEMAS = {
    'users': obj({'_id': OID, 'username': S, 'usernameNormalized': S, 'passwordHash': S, 'createdAt': D, 'schemaVersion': {'enum': [1]}},
                 ['username', 'usernameNormalized', 'passwordHash', 'createdAt', 'schemaVersion']),
    'surveys': obj({'_id': OID, 'ownerId': OID, 'shareSlug': S, 'title': S, 'description': S, 'anonymousEnabled': B,
                    'allowMultipleSubmissions': B, 'status': {'enum': ['DRAFT', 'PUBLISHED', 'CLOSED']},
                    'closesAt': {'bsonType': ['date', 'null']}, 'questions': {'bsonType': 'array', 'maxItems': 200, 'items': QUESTION},
                    'contentVersion': {'enum': [1]}, 'ruleLanguageVersion': {'enum': [1]}, 'revision': I,
                    'createdAt': D, 'updatedAt': D, 'publishedAt': {'bsonType': ['date', 'null']},
                    'closedAt': {'bsonType': ['date', 'null']}, 'schemaVersion': {'enum': [1]}},
                   ['ownerId', 'shareSlug', 'title', 'description', 'anonymousEnabled', 'allowMultipleSubmissions', 'status', 'closesAt',
                    'questions', 'contentVersion', 'ruleLanguageVersion', 'revision', 'createdAt', 'updatedAt', 'publishedAt', 'closedAt', 'schemaVersion']),
    'responses': obj({'_id': OID, 'surveyId': OID, 'contentVersion': {'enum': [1]}, 'respondentKey': S,
                      'identityKeyVersion': {'enum': [1]}, 'identifiedUserId': OID,
                      'participationMode': {'enum': ['IDENTIFIED', 'ANONYMOUS']}, 'repeatMode': {'enum': ['SINGLE', 'MULTIPLE']},
                      'attemptKey': S, 'status': {'enum': ['DRAFT', 'SUBMITTED']},
                      'answers': {'bsonType': 'array', 'maxItems': 200, 'items': ANSWER},
                      'visitedQuestionIds': {'bsonType': 'array', 'items': S, 'uniqueItems': True}, 'revision': I,
                      'submissionDigest': S, 'admittedAt': D, 'startedAt': D, 'updatedAt': D,
                      'submittedAt': {'bsonType': ['date', 'null']}, 'schemaVersion': {'enum': [1]}},
                     ['surveyId', 'contentVersion', 'respondentKey', 'identityKeyVersion', 'participationMode', 'repeatMode',
                      'attemptKey', 'status', 'answers', 'visitedQuestionIds', 'revision', 'startedAt', 'updatedAt', 'submittedAt', 'schemaVersion']),
    'sessions': obj({'_id': OID, 'userId': OID, 'tokenHash': S, 'createdAt': D, 'expiresAt': D, 'schemaVersion': {'enum': [1]}},
                    ['userId', 'tokenHash', 'createdAt', 'expiresAt', 'schemaVersion']),
}


def ensure_schema(db):
    existing = set(db.list_collection_names())
    for name, schema in SCHEMAS.items():
        options = dict(validator={'$jsonSchema': schema}, validationLevel='strict', validationAction='error')
        if name in existing:
            db.command('collMod', name, **options)
        else:
            db.create_collection(name, **options)
    ensure_indexes(db)


def ensure_indexes(db):
    db.users.create_index('usernameNormalized', unique=True, name='username_unique')
    db.surveys.create_index('shareSlug', unique=True, name='share_slug_unique')
    db.surveys.create_index([('ownerId', 1), ('updatedAt', -1), ('_id', -1)], name='owner_list')
    db.responses.create_index([('surveyId', 1), ('status', 1), ('contentVersion', 1), ('submittedAt', -1), ('_id', -1)], name='submitted_stats')
    db.responses.create_index([('surveyId', 1), ('respondentKey', 1), ('attemptKey', 1)], unique=True, name='attempt_idempotency')
    db.responses.create_index([('surveyId', 1), ('respondentKey', 1)], unique=True, name='single_submission',
                              partialFilterExpression={'status': 'SUBMITTED', 'repeatMode': 'SINGLE'})
    db.sessions.create_index('tokenHash', unique=True, name='session_token_unique')
    db.sessions.create_index('expiresAt', expireAfterSeconds=0, name='session_expiry')


def check_size(document):
    if len(BSON.encode(document)) > 2 * 1024 * 1024:
        fail('document_too_large', '单份问卷或答卷不能超过2 MiB')
