"""Stage-two validators. schema.py remains the exact four-collection v1 initializer."""
from copy import deepcopy
from .schema import SCHEMAS, QUESTION, CONSTRAINTS, OPTION, obj, S, I, D, OID, B, ensure_schema

NID = {'bsonType': ['objectId', 'null']}
PAYLOAD = obj({k: deepcopy(QUESTION['properties'][k]) for k in
               ('title', 'type', 'required', 'options', 'constraints')},
              ['title', 'type', 'required', 'options', 'constraints'])
POLICY = obj({'policyVersion': {'enum': [1]}, 'numericCuts': {'bsonType': 'array', 'maxItems': 19, 'items': S}},
             ['policyVersion', 'numericCuts'])
SOURCE = obj({'libraryQuestionId': OID, 'questionVersionId': OID, 'contentHash': S,
              'reusePolicyVersion': {'enum': [1]}, 'acknowledgedAt': D},
             ['libraryQuestionId', 'questionVersionId', 'contentHash', 'reusePolicyVersion', 'acknowledgedAt'])
V2_SURVEY = deepcopy(SCHEMAS['surveys'])
V2_SURVEY['properties']['schemaVersion'] = {'enum': [2]}
V2_SURVEY['properties']['questions']['items']['properties']['sourceRef'] = SOURCE
RUNTIME_SCHEMAS = {**deepcopy(SCHEMAS), 'surveys': {'oneOf': [deepcopy(SCHEMAS['surveys']), V2_SURVEY]}}


def document(fields, required):
    return obj({'_id': OID, 'schemaVersion': {'enum': [1]}, **fields}, ['schemaVersion', *required])


RUNTIME_SCHEMAS.update({
    'question_items': document({
        'ownerId': OID, 'name': S, 'status': {'enum': ['ACTIVE', 'ARCHIVED']}, 'headVersionId': NID,
        'nextVersionNo': I, 'revision': I, 'createdAt': D, 'updatedAt': D,
        'workingDraft': {'oneOf': [{'bsonType': 'null'}, obj({'baseVersionId': NID, 'payload': PAYLOAD,
                            'summaryPolicy': POLICY}, ['baseVersionId', 'payload', 'summaryPolicy'])]}},
        ['ownerId', 'name', 'status', 'headVersionId', 'nextVersionNo', 'revision', 'createdAt', 'updatedAt', 'workingDraft']),
    'question_versions': document({
        'libraryQuestionId': OID, 'versionNo': I, 'parentVersionId': NID, 'derivedFromVersionId': NID,
        'restoredFromVersionId': NID, 'operation': {'enum': ['CREATE', 'EDIT', 'RESTORE', 'FORK']},
        'operationKey': S, 'requestHash': S, 'payload': PAYLOAD, 'summaryPolicy': POLICY,
        'contentHash': S, 'createdBy': OID, 'createdAt': D},
        ['libraryQuestionId', 'versionNo', 'parentVersionId', 'derivedFromVersionId', 'restoredFromVersionId',
         'operation', 'operationKey', 'requestHash', 'payload', 'summaryPolicy', 'contentHash', 'createdBy', 'createdAt']),
    'access_grants': document({'questionVersionId': OID, 'granteeId': OID, 'grantedBy': OID, 'active': B,
        'revision': I, 'createdAt': D, 'updatedAt': D, 'revokedAt': {'bsonType': ['date', 'null']}},
        ['questionVersionId', 'granteeId', 'grantedBy', 'active', 'revision', 'createdAt', 'updatedAt', 'revokedAt']),
    'question_banks': document({'ownerId': OID, 'name': S, 'description': S, 'status': {'enum': ['ACTIVE', 'ARCHIVED']},
        'revision': I, 'createdAt': D, 'updatedAt': D}, ['ownerId', 'name', 'description', 'status', 'revision', 'createdAt', 'updatedAt']),
    'question_bank_items': document({'bankId': OID, 'libraryQuestionId': OID, 'questionVersionId': OID,
        'position': I, 'revision': I, 'createdAt': D, 'updatedAt': D},
        ['bankId', 'libraryQuestionId', 'questionVersionId', 'position', 'revision', 'createdAt', 'updatedAt']),
    'legacy_question_links': {'oneOf': [
        document({'recordType': {'enum': ['HEAD']}, 'surveyId': OID, 'questionId': S,
                  'currentRevisionId': NID, 'revision': I}, ['recordType', 'surveyId', 'questionId', 'currentRevisionId', 'revision']),
        document({'recordType': {'enum': ['REVISION']}, 'headId': OID, 'surveyId': OID, 'questionId': S,
                  'surveyContentVersion': {'enum': [1]}, 'libraryQuestionId': OID, 'questionVersionId': OID,
                  'contentHash': S, 'previousRevisionId': NID, 'operation': {'enum': ['BIND', 'CORRECT', 'SUSPEND', 'RESUME']},
                  'operationKey': S, 'requestHash': S, 'linkedBy': OID, 'createdAt': D, 'reason': S,
                  'reusePolicyVersion': {'enum': [1]}, 'acknowledgedAt': D},
                 ['recordType', 'headId', 'surveyId', 'questionId', 'surveyContentVersion', 'libraryQuestionId',
                  'questionVersionId', 'contentHash', 'previousRevisionId', 'operation', 'operationKey', 'requestHash',
                  'linkedBy', 'createdAt', 'reason', 'reusePolicyVersion', 'acknowledgedAt'])]},
})


def ensure_runtime_schema(db):
    # Do not call the v1 initializer here: it would transiently downgrade survey validation.
    existing = set(db.list_collection_names())
    for name, schema in RUNTIME_SCHEMAS.items():
        options = dict(validator={'$jsonSchema': schema}, validationLevel='strict', validationAction='error')
        if name in existing:
            db.command('collMod', name, **options)
        else:
            db.create_collection(name, **options)
    # Original indexes, installed without replacing validators.
    from .schema import ensure_indexes
    ensure_indexes(db)
    db.question_items.create_index([('ownerId', 1), ('status', 1), ('updatedAt', -1), ('_id', -1)], name='library_owner')
    db.question_versions.create_index([('libraryQuestionId', 1), ('versionNo', 1)], unique=True, name='version_number')
    db.question_versions.create_index([('libraryQuestionId', 1), ('operationKey', 1)], unique=True, name='version_operation')
    db.question_versions.create_index('parentVersionId', name='version_parent')
    for key in ('questionVersionId', 'libraryQuestionId'):
        db.surveys.create_index([('questions.sourceRef.' + key, 1), ('ownerId', 1), ('status', 1)], name='source_' + key)
    db.access_grants.create_index([('questionVersionId', 1), ('granteeId', 1)], unique=True, name='version_grantee')
    db.access_grants.create_index([('granteeId', 1), ('active', 1), ('questionVersionId', 1)], name='received_versions')
    db.question_banks.create_index([('ownerId', 1), ('status', 1), ('updatedAt', -1), ('_id', -1)], name='bank_owner')
    db.question_bank_items.create_index([('bankId', 1), ('questionVersionId', 1)], unique=True, name='bank_version')
    db.question_bank_items.create_index([('bankId', 1), ('position', 1), ('_id', 1)], name='bank_order')
    db.question_bank_items.create_index([('libraryQuestionId', 1), ('questionVersionId', 1)], name='member_version')
    db.legacy_question_links.create_index([('surveyId', 1), ('questionId', 1)], unique=True, name='legacy_head',
                                         partialFilterExpression={'recordType': 'HEAD'})
    db.legacy_question_links.create_index([('surveyId', 1), ('questionId', 1), ('operationKey', 1)], unique=True,
                                         name='legacy_operation', partialFilterExpression={'recordType': 'REVISION'})
    db.legacy_question_links.create_index([('recordType', 1), ('libraryQuestionId', 1), ('questionVersionId', 1),
                                         ('surveyId', 1), ('questionId', 1)], name='legacy_reverse')
