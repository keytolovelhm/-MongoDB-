"""Explicit historical associations; the original survey/response BSON is never written."""
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from .errors import fail
from .repositories import oid, utcnow, wire, Repository
from .library_service import content_hash, digest, acknowledgement


class LegacyService:
    def __init__(self, store, library):
        self.store, self.db, self.library = store, store.db, library

    def source(self, user, survey_id, question_id):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        if survey['schemaVersion'] != 1 or survey['status'] not in ('PUBLISHED', 'CLOSED'):
            fail('legacy_frozen_only', '仅支持已冻结的第一阶段问卷', 409)
        q = next((q for q in survey['questions'] if q['questionId'] == question_id), None)
        if not q: fail('not_found', '题目不存在', 404)
        if 'sourceRef' in q: fail('already_sourced', '已有版本来源，不能重复关联', 409)
        return survey, q

    def current(self, user, survey_id, question_id):
        survey, _ = self.source(user, survey_id, question_id)
        head = self.db.legacy_question_links.find_one({'recordType': 'HEAD', 'surveyId': survey['_id'], 'questionId': question_id})
        revision = self.db.legacy_question_links.find_one({'_id': head['currentRevisionId']}) if head and head['currentRevisionId'] else None
        return {'head': wire(head), 'current': wire(revision)}

    def history(self, user, survey_id, question_id, skip, limit):
        survey, _ = self.source(user, survey_id, question_id)
        query = {'recordType': 'REVISION', 'surveyId': survey['_id'], 'questionId': question_id}
        return {'items': wire(list(self.db.legacy_question_links.find(query).sort('_id', -1).skip(skip).limit(limit))),
                'total': self.db.legacy_question_links.count_documents(query)}

    def bind(self, user, survey_id, question_id, data):
        survey, question = self.source(user, survey_id, question_id)
        fingerprint = digest(data.model_dump())
        query = {'recordType': 'HEAD', 'surveyId': survey['_id'], 'questionId': question_id}
        head = self.db.legacy_question_links.find_one(query)
        if not head:
            if data.expectedLinkRevision != 0: fail('revision_conflict', '关联修订不匹配', 409)
            head = dict(_id=ObjectId(), **query, currentRevisionId=None, revision=0, schemaVersion=1)
            try: self.db.legacy_question_links.insert_one(head)
            except DuplicateKeyError: head = self.db.legacy_question_links.find_one(query)
        previous = self.db.legacy_question_links.find_one({'_id': head['currentRevisionId']}) if head['currentRevisionId'] else None
        existing = self.db.legacy_question_links.find_one({'recordType': 'REVISION', 'surveyId': survey['_id'],
                                                          'questionId': question_id, 'operationKey': data.operationKey})
        if existing:
            if existing['requestHash'] != fingerprint: fail('operation_conflict', '同一操作键不能改变关联请求', 409)
            if head['currentRevisionId'] == existing['_id']: return {'head': wire(head), 'current': wire(existing)}
            if head['revision'] != data.expectedLinkRevision or head['currentRevisionId'] != existing['previousRevisionId']:
                fail('operation_superseded', '该操作已被后续修订替代，不能重放', 409)
        if head['revision'] != data.expectedLinkRevision: fail('revision_conflict', '关联已修改，请刷新', 409)
        if data.operation == 'BIND' and previous: fail('already_linked', '已有记录，请使用纠错操作', 409)
        if data.operation != 'BIND' and (not previous or not data.reason.strip()):
            fail('correction_reason', '纠错需要现有关联和明确原因', 422)
        if data.operation in ('SUSPEND', 'RESUME'):
            if oid(data.versionId) != previous['questionVersionId']: fail('correction_target', '暂停/恢复不能换绑版本', 422)
            if (data.operation == 'RESUME') != (previous['operation'] == 'SUSPEND'):
                fail('correction_state', '当前状态不支持此操作', 409)
        if data.operation == 'SUSPEND':
            v = self.library.version(data.versionId)
        else:
            acknowledgement(data)
            v = self.library.usable(user, data.versionId)
        if content_hash(question) != v['contentHash']:
            fail('content_mismatch', '旧题正文、选项ID或约束与版本不一致；请从旧题另存后关联', 422)
        revision = existing or dict(_id=ObjectId(), recordType='REVISION', headId=head['_id'],
            surveyId=survey['_id'], questionId=question_id, surveyContentVersion=survey['contentVersion'],
            libraryQuestionId=v['libraryQuestionId'], questionVersionId=v['_id'], contentHash=v['contentHash'],
            previousRevisionId=head['currentRevisionId'], operation=data.operation, operationKey=data.operationKey,
            requestHash=fingerprint, linkedBy=user['_id'], createdAt=utcnow(), reason=data.reason.strip(),
            reusePolicyVersion=1, acknowledgedAt=previous['acknowledgedAt'] if data.operation == 'SUSPEND' else utcnow(), schemaVersion=1)
        if not existing:
            try: self.db.legacy_question_links.insert_one(revision)
            except DuplicateKeyError:
                revision = self.db.legacy_question_links.find_one({'recordType': 'REVISION', 'surveyId': survey['_id'],
                    'questionId': question_id, 'operationKey': data.operationKey})
                if revision['requestHash'] != fingerprint: fail('operation_conflict', '关联操作键冲突', 409)
        changed = Repository(self.db.legacy_question_links).change({'_id': head['_id'], 'revision': data.expectedLinkRevision,
                    'currentRevisionId': head['currentRevisionId']}, {'currentRevisionId': revision['_id']})
        if not changed:
            current = self.db.legacy_question_links.find_one({'_id': head['_id']})
            if current['currentRevisionId'] == revision['_id']: return {'head': wire(current), 'current': wire(revision)}
            fail('revision_conflict', '关联已并发修改，候选修订未生效', 409)
        return {'head': wire(changed), 'current': wire(self.db.legacy_question_links.find_one({'_id': revision['_id']}))}
