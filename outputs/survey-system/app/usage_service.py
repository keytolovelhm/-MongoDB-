"""Resolve each instance once, including only the pointed-to legacy revision."""
from .library_service import content_hash
from .repositories import wire
from .security import keyed
from .survey_service import effective_status
from .errors import fail


class UsageService:
    def __init__(self, store, library, settings):
        self.db, self.library, self.secret = store.db, library, settings.secret

    def instances(self, user, root, include_suspended=False):
        author = root['ownerId'] == user['_id']
        query = {'questions.sourceRef.libraryQuestionId': root['_id']}
        if not author: query['ownerId'] = user['_id']
        candidates = {}
        for survey in self.db.surveys.find(query):
            for q in survey['questions']:
                ref = q.get('sourceRef')
                if ref and ref['libraryQuestionId'] == root['_id']:
                    candidates[(survey['_id'], q['questionId'])] = (survey, q, ref, False)
        # Lookup is one immutable revision by _id per HEAD. Never inspect old revisions as effective links.
        pipeline = [{'$match': {'recordType': 'HEAD'}},
                    {'$lookup': {'from': 'legacy_question_links', 'localField': 'currentRevisionId',
                                 'foreignField': '_id', 'as': 'current'}},
                    {'$unwind': '$current'}, {'$match': {'current.libraryQuestionId': root['_id']}}]
        for head in self.db.legacy_question_links.aggregate(pipeline):
            revision = head['current']  # This pointer was read once for this query.
            if (revision['headId'] != head['_id'] or revision['surveyId'] != head['surveyId']
                    or revision['questionId'] != head['questionId']): continue
            survey = self.db.surveys.find_one({'_id': head['surveyId']})
            if not survey or (not author and survey['ownerId'] != user['_id']): continue
            q = next((q for q in survey['questions'] if q['questionId'] == head['questionId']), None)
            if not q or survey['schemaVersion'] != 1 or survey['status'] == 'DRAFT': continue
            if revision['surveyContentVersion'] != survey['contentVersion']: continue
            key = (survey['_id'], q['questionId'])
            if key in candidates:
                # Conflicting references are excluded, never attributed twice.
                if candidates[key] is None or candidates[key][2]['questionVersionId'] != revision['questionVersionId']:
                    candidates[key] = None
                continue
            if revision['operation'] == 'SUSPEND' and not include_suspended: continue
            if revision['operation'] not in ('BIND', 'CORRECT', 'RESUME', 'SUSPEND'): continue
            candidates[key] = (survey, q, revision, revision['operation'] == 'SUSPEND')
        valid = []
        for item in candidates.values():
            if item is None: continue
            survey, q, ref, suspended = item
            v = self.db.question_versions.find_one({'_id': ref['questionVersionId'], 'libraryQuestionId': root['_id']})
            if v and ref['contentHash'] == v['contentHash'] == content_hash(q):
                valid.append((survey, q, v, suspended))
        if not author and not valid and not self.db.access_grants.find_one(
                {'granteeId': user['_id'], 'active': True, 'questionVersionId': {'$in': list(
                    self.db.question_versions.distinct('_id', {'libraryQuestionId': root['_id']}))}}):
            fail('not_found', '题目不存在或无权访问', 404)
        return valid

    def listing(self, user, item_id, skip, limit):
        root = self.library.root(item_id)
        items = self.instances(user, root, include_suspended=True)
        grouped = {}
        for survey, q, v, suspended in items:
            key = survey['_id']
            if key not in grouped:
                own = survey['ownerId'] == user['_id']
                grouped[key] = {'displayId': keyed(self.secret, 'usage-display-v1', f"{root['_id']}:{survey['_id']}")[:20],
                                'title': survey['title'] if own else None, 'status': effective_status(survey), 'instances': []}
            grouped[key]['instances'].append({'questionId': q['questionId'] if survey['ownerId'] == user['_id'] else None,
                  'versionId': str(v['_id']), 'versionNo': v['versionNo'], 'linkStatus': 'SUSPENDED' if suspended else 'ACTIVE'})
        result = sorted(grouped.values(), key=lambda x: x['displayId'])
        return {'items': result[skip:skip+limit], 'total': len(result), 'scope': 'AUTHOR_ALL' if root['ownerId'] == user['_id'] else 'OWN'}
