"""Question identities, immutable versions, exact-version USE and survey snapshots."""
from copy import deepcopy
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from uuid import uuid4
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from .domain import validate_definition, number
from .errors import fail
from .library_models import Payload
from .repositories import utcnow, oid, wire, Repository
from .schema import check_size
from .security import normalize_username

REUSE_NOTICE = ('复用后，原题作者可查看本卷的固定展示标识、所用版本和状态，并自动获得该版本在全部采用问卷中的汇总；'
                '不会获得他人账号身份、原始答卷或文本。撤销共享仅阻止新采用，既有快照及后续正式回答仍在该范围内。')


def decimal_key(value):
    """Lossless numeric semantics, including 34-digit coefficients; no normalize rounding."""
    d = number(value)
    if not d:
        return '0'
    sign, digits, exponent = d.as_tuple()
    digits = list(digits)
    while digits[-1] == 0:
        digits.pop(); exponent += 1
    return ('-' if sign else '') + ''.join(map(str, digits)) + 'e' + str(exponent)


def payload_of(question):
    return Payload.model_validate({k: question[k] for k in ('title', 'type', 'required', 'options', 'constraints')}).model_dump()


def digest(value):
    return sha256(json.dumps(wire(value), sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def content_hash(payload):
    body = payload_of(payload)
    for key in ('minValue', 'maxValue'):
        if body['constraints'][key] is not None:
            body['constraints'][key] = decimal_key(body['constraints'][key])
    return digest(body)


def validated_payload(payload):
    body = payload.model_dump() if hasattr(payload, 'model_dump') else payload_of(payload)
    validate_definition({'title': '题目', 'questions': [dict(body, questionId='validation', order=0, rules=[])]}, publishing=True)
    return body


def summary_policy(payload, supplied=None):
    policy = supplied.model_dump() if hasattr(supplied, 'model_dump') else deepcopy(supplied)
    if payload['type'] != 'NUMBER':
        if policy and policy['numericCuts']:
            fail('summary_policy', '非数字题不能设置数字分组')
        return {'policyVersion': 1, 'numericCuts': []}
    if policy is None:
        lo, hi = (payload['constraints'].get(k) for k in ('minValue', 'maxValue'))
        if lo is None or hi is None:
            fail('summary_policy', '无有限上下界的数字题请指定固定分组切点')
        with localcontext() as ctx:
            ctx.prec = 100
            low, high = number(lo), number(hi)
            cuts = [str(low + (high - low) * Decimal(i) / 5) for i in range(1, 5)] if low != high else []
        policy = {'policyVersion': 1, 'numericCuts': cuts}
    cuts = [number(v) for v in policy['numericCuts']]
    if any(a >= b for a, b in zip(cuts, cuts[1:])):
        fail('summary_policy', '切点必须严格递增')
    return policy


def acknowledgement(data):
    if data.reusePolicyVersion != 1:
        fail('reuse_policy_changed', '复用告知版本已变化，请重新阅读确认', 409)
    if not data.acknowledged:
        fail('reuse_notice_required', '请阅读并确认复用可见范围', 422)


class LibraryService:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def root(self, item_id):
        root = self.db.question_items.find_one({'_id': oid(item_id)})
        if not root: fail('not_found', '题目不存在或无权访问', 404)
        return root

    def owned(self, user, item_id):
        root = self.root(item_id)
        if root['ownerId'] != user['_id']: fail('not_found', '题目不存在或无权访问', 404)
        return root

    def version(self, version_id):
        v = self.db.question_versions.find_one({'_id': oid(version_id)})
        if not v: fail('not_found', '版本不存在或无权访问', 404)
        return v

    def usable(self, user, version_id):
        v = self.version(version_id); root = self.root(v['libraryQuestionId'])
        if root['status'] != 'ACTIVE': fail('version_unavailable', '题目已归档，不能新采用', 409)
        if root['ownerId'] != user['_id'] and not self.db.access_grants.find_one(
                {'questionVersionId': v['_id'], 'granteeId': user['_id'], 'active': True}):
            fail('not_found', '版本不存在或无权访问', 404)
        return v

    def readable(self, user, version_id):
        v = self.version(version_id)
        if self.root(v['libraryQuestionId'])['ownerId'] == user['_id']:
            return v
        return self.usable(user, version_id)

    def create(self, user, data, derived=None):
        body = validated_payload(data.payload)
        policy = summary_policy(body, data.summaryPolicy)
        now = utcnow(); root_id, version_id = ObjectId(), ObjectId()
        root = dict(_id=root_id, ownerId=user['_id'], name=data.name, status='ACTIVE', headVersionId=version_id,
                    nextVersionNo=2, workingDraft=None, revision=0, createdAt=now, updatedAt=now, schemaVersion=1)
        version = dict(_id=version_id, libraryQuestionId=root_id, versionNo=1, parentVersionId=None,
                       derivedFromVersionId=derived, restoredFromVersionId=None, operation='FORK' if derived else 'CREATE',
                       operationKey=uuid4().hex, requestHash=digest(data.model_dump()), payload=body, summaryPolicy=policy,
                       contentHash=content_hash(body), createdBy=user['_id'], createdAt=now, schemaVersion=1)
        check_size(version)
        # Write version first. An orphan after a failure is inaccessible without a root.
        self.db.question_versions.insert_one(version)
        self.db.question_items.insert_one(root)
        return {'item': wire(root), 'version': wire(version)}

    def listing(self, user, skip, limit):
        query = {'ownerId': user['_id']}
        return {'items': wire(list(self.db.question_items.find(query, {'workingDraft': 0}).sort(
                [('updatedAt', -1), ('_id', -1)]).skip(skip).limit(limit))),
                'total': self.db.question_items.count_documents(query), 'skip': skip, 'limit': limit}

    def received(self, user, skip, limit):
        query = {'granteeId': user['_id'], 'active': True}
        result = []
        for g in self.db.access_grants.find(query).sort('_id', -1).skip(skip).limit(limit):
            v = self.db.question_versions.find_one({'_id': g['questionVersionId']})
            root = self.db.question_items.find_one({'_id': v['libraryQuestionId']}) if v else None
            if root and root['status'] == 'ACTIVE':
                result.append({'version': wire(v), 'name': root['name']})
        return {'items': result, 'total': self.db.access_grants.count_documents(query), 'skip': skip, 'limit': limit}

    def detail(self, user, item_id):
        root = self.owned(user, item_id)
        return wire(root)

    def versions(self, user, item_id, skip, limit):
        self.owned(user, item_id)
        query = {'libraryQuestionId': oid(item_id)}
        return {'items': wire(list(self.db.question_versions.find(query).sort('versionNo', -1).skip(skip).limit(limit))),
                'total': self.db.question_versions.count_documents(query)}

    def update(self, user, item_id, data):
        root = self.owned(user, item_id)
        changed = Repository(self.db.question_items).change({'_id': root['_id'], 'revision': data.revision},
                    {'name': data.name, 'status': data.status, 'updatedAt': utcnow()})
        if not changed: fail('revision_conflict', '题目已修改，请刷新', 409)
        return wire(changed)

    def draft(self, user, item_id, data):
        root = self.owned(user, item_id)
        if root['status'] != 'ACTIVE': fail('version_unavailable', '已归档题目不能编辑', 409)
        base = self.version(data.baseVersionId) if data.baseVersionId else None
        if not base: fail('version_parent', '工作稿必须明确指定已有基线版本', 422)
        if base and base['libraryQuestionId'] != root['_id']: fail('version_parent', '基线必须属于本题', 422)
        body = validated_payload(data.payload)
        draft = {'baseVersionId': base['_id'] if base else None, 'payload': body,
                 'summaryPolicy': summary_policy(body, data.summaryPolicy)}
        check_size(dict(root, workingDraft=draft))
        changed = Repository(self.db.question_items).change({'_id': root['_id'], 'revision': data.revision},
                    {'workingDraft': draft, 'updatedAt': utcnow()})
        if not changed: fail('revision_conflict', '工作稿已修改，请刷新', 409)
        return wire(changed)

    def save(self, user, item_id, data, restore=False):
        root = self.owned(user, item_id)
        fingerprint = digest({'revision': data.revision, 'operation': 'RESTORE' if restore else 'EDIT',
                              'versionId': data.versionId if restore else None})
        existing = self.db.question_versions.find_one({'libraryQuestionId': root['_id'], 'operationKey': data.operationKey})
        if existing:
            if existing['requestHash'] != fingerprint: fail('operation_conflict', '同一操作键不能更换请求', 409)
            return self.saved_result(existing)
        if root['revision'] != data.revision: fail('revision_conflict', '题目已修改，请刷新', 409)
        if root['status'] != 'ACTIVE': fail('version_unavailable', '题目已归档', 409)
        restored = self.version(data.versionId) if restore else None
        if restored and restored['libraryQuestionId'] != root['_id']: fail('version_parent', '只能恢复本题版本', 422)
        draft = root['workingDraft']
        if not restore and not draft: fail('no_working_draft', '请先保存工作稿', 409)
        body = restored['payload'] if restore else draft['payload']
        policy = restored['summaryPolicy'] if restore else draft['summaryPolicy']
        parent = root['headVersionId'] if restore else draft['baseVersionId']
        allocation = self.db.question_items.find_one_and_update({'_id': root['_id']}, {'$inc': {'nextVersionNo': 1}})
        v = dict(_id=ObjectId(), libraryQuestionId=root['_id'], versionNo=allocation['nextVersionNo'],
                 parentVersionId=parent, derivedFromVersionId=None, restoredFromVersionId=restored['_id'] if restore else None,
                 operation='RESTORE' if restore else 'EDIT', operationKey=data.operationKey, requestHash=fingerprint,
                 payload=body, summaryPolicy=policy, contentHash=content_hash(body), createdBy=user['_id'],
                 createdAt=utcnow(), schemaVersion=1)
        check_size(v)
        try:
            self.db.question_versions.insert_one(v)
        except DuplicateKeyError:
            v = self.db.question_versions.find_one({'libraryQuestionId': root['_id'], 'operationKey': data.operationKey})
            if not v or v['requestHash'] != fingerprint: fail('operation_conflict', '版本操作冲突', 409)
            return self.saved_result(v)
        Repository(self.db.question_items).change({'_id': root['_id'], 'revision': data.revision},
                    {'headVersionId': v['_id'], 'workingDraft': None, 'updatedAt': utcnow()})
        return self.saved_result(v)

    def saved_result(self, version):
        # Return persisted BSON precision on both the first response and an idempotent retry.
        version = self.version(version['_id'])
        root = self.root(version['libraryQuestionId'])
        return {'version': wire(version), 'item': wire(root), 'headAdvanced': root['headVersionId'] == version['_id']}

    def fork(self, user, version_id, data):
        from .library_models import ItemCreate, SummaryPolicy
        v = self.usable(user, version_id)
        return self.create(user, ItemCreate(name=data.name, payload=Payload(**v['payload']),
                           summaryPolicy=SummaryPolicy(**v['summaryPolicy'])), derived=v['_id'])

    def grants(self, user, version_id):
        v = self.version(version_id); self.owned(user, v['libraryQuestionId'])
        result = []
        for g in self.db.access_grants.find({'questionVersionId': v['_id']}):
            u = self.db.users.find_one({'_id': g['granteeId']})
            result.append(dict(wire(g), username=u['username'] if u else '已停用账号'))
        return {'items': result}

    def grant(self, user, version_id, data):
        v = self.version(version_id); self.owned(user, v['libraryQuestionId'])
        target = self.db.users.find_one({'usernameNormalized': normalize_username(data.username)})
        if not target: fail('account_not_found', '指定账号不存在', 422)
        if target['_id'] == user['_id']: fail('grant_self', '无需向自己共享', 422)
        now = utcnow(); query = {'questionVersionId': v['_id'], 'granteeId': target['_id']}
        old = self.db.access_grants.find_one(query)
        if not old:
            if data.revision != 0: fail('revision_conflict', '授权修订不匹配', 409)
            g = dict(_id=ObjectId(), **query, grantedBy=user['_id'], active=data.active, revision=1,
                     createdAt=now, updatedAt=now, revokedAt=None if data.active else now, schemaVersion=1)
            try: self.db.access_grants.insert_one(g)
            except DuplicateKeyError: fail('revision_conflict', '授权已创建，请刷新', 409)
        else:
            g = Repository(self.db.access_grants).change(dict(query, revision=data.revision),
                {'active': data.active, 'updatedAt': now, 'revokedAt': None if data.active else now})
            if not g: fail('revision_conflict', '授权已修改，请刷新', 409)
        return wire(g)

    def import_version(self, user, survey_id, data):
        acknowledgement(data)
        survey = self.store.surveys.owned(survey_id, user['_id'])
        if survey['status'] != 'DRAFT': fail('definition_frozen', '只能向草稿导入或替换题目', 409)
        v = self.usable(user, data.versionId)
        questions = deepcopy(survey['questions'])
        if data.replaceQuestionId:
            target = next((q for q in questions if q['questionId'] == data.replaceQuestionId), None)
            if target is None: fail('not_found', '本卷题目不存在', 404)
            target.update(deepcopy(v['payload']))
        else:
            if len(questions) >= 200: fail('question_limit', '问卷最多200题', 422)
            target = dict(deepcopy(v['payload']), questionId=uuid4().hex,
                          order=max((q['order'] for q in questions), default=-1) + 1, rules=[])
            questions.append(target)
        target['sourceRef'] = dict(libraryQuestionId=v['libraryQuestionId'], questionVersionId=v['_id'],
                                  contentHash=v['contentHash'], reusePolicyVersion=1, acknowledgedAt=utcnow())
        validate_definition(dict(survey, questions=questions))
        check_size(dict(survey, questions=questions, schemaVersion=2))
        changed = self.store.surveys.change({'_id': survey['_id'], 'status': 'DRAFT', 'revision': data.revision},
                                          {'questions': questions, 'schemaVersion': 2, 'updatedAt': utcnow()})
        if not changed: fail('revision_conflict', '问卷已修改，请刷新', 409)
        from .survey_service import SurveyService
        return SurveyService.public(changed)

    def save_local(self, user, survey_id, question_id, name, policy=None):
        from .library_models import ItemCreate
        s = self.store.surveys.owned(survey_id, user['_id'])
        q = next((q for q in s['questions'] if q['questionId'] == question_id), None)
        if not q: fail('not_found', '题目不存在', 404)
        # A local save never changes a frozen survey or automatically links its answers.
        source = q.get('sourceRef')
        if source:
            self.usable(user, source['questionVersionId'])
        return self.create(user, ItemCreate(name=name, payload=Payload(**payload_of(q)), summaryPolicy=policy),
                           derived=source['questionVersionId'] if source else None)
