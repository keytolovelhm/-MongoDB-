import hashlib
import json
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from .domain import walk, normalize_answer, pack_answers, unpack_answers
from .errors import fail
from .repositories import oid, utcnow, wire
from .schema import check_size
from .security import respondent_key
from .survey_service import assert_open, version_check


class AttemptService:
    def __init__(self, store, settings): self.store, self.settings = store, settings

    def key(self, survey, user): return respondent_key(self.settings.secret, survey['_id'], user['_id'])

    def owned(self, user, attempt_id):
        response = self.store.responses.get({'_id': oid(attempt_id)})
        if not response: fail('not_found', '填写记录不存在', 404)
        survey = self.store.surveys.get({'_id': response['surveyId']})
        if not survey: fail('not_found', '问卷不存在', 404)
        if response['respondentKey'] != self.key(survey, user): fail('not_found', '填写记录不存在或无权访问', 404)
        version_check(survey, response)
        return survey, response

    @staticmethod
    def public(survey, response):
        values = unpack_answers(survey['questions'], response['answers'])
        path, _, pending = walk(survey['questions'], values)
        allowed = ['_id', 'surveyId', 'contentVersion', 'participationMode', 'status', 'revision', 'startedAt', 'updatedAt', 'submittedAt', 'admittedAt']
        result = wire({k: response[k] for k in allowed if k in response})
        result.update(answers=[{'questionId': qid, 'value': wire(value)} for qid, value in values.items()],
                      visitedQuestionIds=path, nextQuestionId=pending, readyToSubmit=pending is None)
        return result

    def create(self, user, slug, data):
        survey = self.store.surveys.by_slug(slug)
        version_check(survey)
        key = self.key(survey, user)
        query = {'surveyId': survey['_id'], 'respondentKey': key, 'attemptKey': data.attemptKey}
        existing = self.store.responses.get(query)
        if existing:
            if existing['participationMode'] != data.participationMode: fail('attempt_mode_conflict', '同一填写会话不能改变匿名方式', 409)
            return self.public(survey, existing)
        assert_open(survey)
        if data.participationMode == 'ANONYMOUS' and not survey['anonymousEnabled']:
            fail('anonymous_disabled', '此问卷不允许匿名填写')
        if not survey['allowMultipleSubmissions'] and self.store.responses.get(dict(query, attemptKey={'$exists': True}, status='SUBMITTED')):
            fail('already_submitted', '此问卷每个账号只能提交一次', 409)
        now = utcnow()
        path, _, _ = walk(survey['questions'], {})
        doc = dict(query, _id=ObjectId(), contentVersion=survey['contentVersion'], identityKeyVersion=1,
                   participationMode=data.participationMode, repeatMode='MULTIPLE' if survey['allowMultipleSubmissions'] else 'SINGLE',
                   status='DRAFT', answers=[], visitedQuestionIds=path, revision=0, schemaVersion=1,
                   startedAt=now, updatedAt=now, submittedAt=None)
        if data.participationMode == 'IDENTIFIED': doc['identifiedUserId'] = user['_id']
        try: self.store.responses.insert(doc)
        except DuplicateKeyError:
            doc = self.store.responses.get(query)
            if not doc or doc['participationMode'] != data.participationMode: fail('attempt_conflict', '填写会话冲突，请刷新', 409)
        return self.public(survey, doc)

    def recent(self, user, slug):
        survey = self.store.surveys.by_slug(slug)
        if survey['status'] == 'DRAFT': fail('not_found', '问卷未发布', 404)
        docs = self.store.responses.recent(survey['_id'], self.key(survey, user))
        return {'items': wire([{k: d[k] for k in ['_id', 'status', 'participationMode', 'startedAt', 'submittedAt']} for d in docs])}

    def get(self, user, attempt_id):
        survey, doc = self.owned(user, attempt_id)
        return self.public(survey, doc)

    def answer(self, user, attempt_id, data):
        survey, doc = self.owned(user, attempt_id)
        assert_open(survey)
        if doc['status'] != 'DRAFT': fail('response_frozen', '正式答卷不能修改；允许多次时请新建填写', 409)
        if doc['revision'] != data.revision: fail('revision_conflict', '填写记录已更新，请刷新后重试', 409)
        values = unpack_answers(survey['questions'], doc['answers'])
        old_path, _, _ = walk(survey['questions'], values)
        if data.questionId not in old_path: fail('question_unreachable', '只能回答当前路径中已经到达的题目', field=data.questionId)
        q = next(q for q in survey['questions'] if q['questionId'] == data.questionId)
        values[data.questionId] = normalize_answer(q, data.value)
        path, kept, _ = walk(survey['questions'], values)
        removed = sorted(set(values) - set(kept))
        changes = {'answers': pack_answers(survey['questions'], kept), 'visitedQuestionIds': path, 'updatedAt': utcnow()}
        from .repositories import to_bson
        check_size(to_bson(dict(doc, **changes)))
        changed = self.store.responses.change({'_id': doc['_id'], 'revision': data.revision, 'status': 'DRAFT'}, changes)
        if not changed: fail('revision_conflict', '填写记录已更新，请刷新后重试', 409)
        result = self.public(survey, changed)
        result['removedQuestionIds'] = removed
        return result

    def submit(self, user, attempt_id, revision):
        survey, doc = self.owned(user, attempt_id)
        # Receipt lookup remains idempotent after closure. A submitted response is immutable.
        if doc['status'] == 'SUBMITTED': return self.public(survey, doc)
        if doc['revision'] != revision: fail('revision_conflict', '填写记录已更新，请刷新', 409)
        values = unpack_answers(survey['questions'], doc['answers'])
        path, kept, pending = walk(survey['questions'], values)
        if pending is not None: fail('incomplete', '请完成当前路径并保存后再提交', field=pending)
        if set(kept) != set(values): fail('unreachable_answers', '答卷含不在当前路径上的答案，请重新保存')
        # D09-B: admission check is the boundary, not a cross-document transaction.
        latest = self.store.surveys.get({'_id': survey['_id']})
        admitted = utcnow()
        assert_open(latest, admitted)
        version_check(latest, doc)
        digest = hashlib.sha256(json.dumps(wire({'answers': doc['answers'], 'path': path, 'version': doc['contentVersion']}),
                                           ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        changes = {'status': 'SUBMITTED', 'submittedAt': utcnow(), 'admittedAt': admitted,
                   'updatedAt': utcnow(), 'visitedQuestionIds': path, 'submissionDigest': digest}
        try:
            changed = self.store.responses.change({'_id': doc['_id'], 'revision': revision, 'status': 'DRAFT'}, changes)
        except DuplicateKeyError:
            fail('already_submitted', '此问卷每个账号只能有一份正式答卷', 409)
        if not changed:
            changed = self.store.responses.get({'_id': doc['_id']})
            if not changed or changed['status'] != 'SUBMITTED': fail('revision_conflict', '填写记录已更新，请刷新', 409)
        return self.public(survey, changed)
