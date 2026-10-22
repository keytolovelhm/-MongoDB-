import secrets
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from .domain import validate_definition
from .errors import fail
from .repositories import utcnow, wire
from .schema import check_size


def effective_status(survey, now=None):
    if survey['status'] == 'PUBLISHED' and survey['closesAt'] and survey['closesAt'] <= (now or utcnow()): return 'EXPIRED'
    return survey['status']


def assert_open(survey, now=None):
    if effective_status(survey, now) != 'PUBLISHED':
        fail('survey_unavailable', '问卷尚未发布、已关闭或已截止', 409)


def version_check(survey, response=None):
    if survey['schemaVersion'] != 1 or survey['contentVersion'] != 1 or survey['ruleLanguageVersion'] != 1:
        fail('unsupported_version', '当前程序不支持该问卷版本', 409)
    if response and (response['schemaVersion'] != 1 or response['contentVersion'] != survey['contentVersion'] or response['identityKeyVersion'] != 1):
        fail('unsupported_version', '答卷版本与问卷定义不兼容', 409)


class SurveyService:
    def __init__(self, store): self.store = store

    @staticmethod
    def public(survey):
        result = wire(survey)
        result['effectiveStatus'] = effective_status(survey)
        return result

    def create(self, user, data):
        definition = data.model_dump()
        definition['questions'] = validate_definition(definition)
        now = utcnow()
        doc = dict(definition, _id=ObjectId(), ownerId=user['_id'], shareSlug=secrets.token_urlsafe(12), status='DRAFT',
                   contentVersion=1, ruleLanguageVersion=1, revision=0, schemaVersion=1,
                   createdAt=now, updatedAt=now, publishedAt=None, closedAt=None)
        check_size(doc)
        # Collision is extremely unlikely, but never silently accept duplicate public URLs.
        for _ in range(3):
            try:
                self.store.surveys.insert(doc)
                return self.public(doc)
            except DuplicateKeyError: doc['shareSlug'] = secrets.token_urlsafe(12)
        fail('slug_collision', '无法分配分享链接，请重试', 503)

    def get(self, user, survey_id): return self.public(self.store.surveys.owned(survey_id, user['_id']))

    def listing(self, user, skip, limit):
        docs, total = self.store.surveys.listing(user['_id'], skip, limit)
        return {'items': [self.public(d) for d in docs], 'total': total, 'skip': skip, 'limit': limit}

    def update(self, user, survey_id, data):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        if survey['status'] != 'DRAFT': fail('definition_frozen', '发布后题目、规则与参与策略已冻结', 409)
        definition = data.model_dump(exclude={'revision'})
        definition['questions'] = validate_definition(definition)
        check_size(dict(survey, **definition))
        changed = self.store.surveys.change({'_id': survey['_id'], 'ownerId': user['_id'], 'revision': data.revision, 'status': 'DRAFT'},
                                           dict(definition, updatedAt=utcnow()))
        if not changed: fail('revision_conflict', '问卷已被修改，请刷新后重试', 409)
        return self.public(changed)

    def publish(self, user, survey_id, revision):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        version_check(survey)
        if survey['status'] != 'DRAFT': fail('state_conflict', '只有草稿可以发布', 409)
        validate_definition(survey, publishing=True)
        now = utcnow()
        if survey['closesAt'] and survey['closesAt'] <= now: fail('deadline_past', '截止时间必须晚于发布时间', field='closesAt')
        changed = self.store.surveys.change({'_id': survey['_id'], 'revision': revision, 'status': 'DRAFT'},
                                           {'status': 'PUBLISHED', 'publishedAt': now, 'updatedAt': now})
        if not changed: fail('revision_conflict', '问卷已被修改，请刷新', 409)
        return self.public(changed)

    def close(self, user, survey_id, revision):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        if survey['status'] == 'CLOSED': return self.public(survey)
        if survey['status'] != 'PUBLISHED': fail('state_conflict', '只有已发布问卷可以关闭', 409)
        now = utcnow()
        changed = self.store.surveys.change({'_id': survey['_id'], 'revision': revision, 'status': 'PUBLISHED'},
                                           {'status': 'CLOSED', 'closedAt': now, 'updatedAt': now})
        if not changed: fail('revision_conflict', '问卷已被修改，请刷新', 409)
        return self.public(changed)

    def deadline(self, user, survey_id, data):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        if effective_status(survey) in ('CLOSED', 'EXPIRED'): fail('state_conflict', '不支持重开或延长已结束的问卷', 409)
        if data.closesAt and data.closesAt <= utcnow(): fail('deadline_past', '新截止时间必须晚于当前时间', field='closesAt')
        changed = self.store.surveys.change({'_id': survey['_id'], 'revision': data.revision, 'status': survey['status'], 'closesAt': survey['closesAt']},
                                           {'closesAt': data.closesAt, 'updatedAt': utcnow()})
        if not changed: fail('revision_conflict', '问卷已被修改，请刷新', 409)
        return self.public(changed)

    def for_filling(self, slug):
        survey = self.store.surveys.by_slug(slug)
        version_check(survey)
        if survey['status'] == 'DRAFT': fail('not_found', '问卷不存在或未发布', 404)
        result = self.public(survey)
        result.pop('ownerId', None)
        # Authenticated respondents can still interpret their saved answers after closure.
        # Write endpoints independently enforce assert_open; no editing permission is granted.
        return result
