from .domain import ANSWER_FIELDS
from .errors import fail
from .repositories import wire
from .survey_service import version_check


class StatsService:
    def __init__(self, store): self.store = store

    @staticmethod
    def query(survey): return {'surveyId': survey['_id'], 'status': 'SUBMITTED', 'contentVersion': survey['contentVersion']}

    def question(self, survey, q):
        collection = self.store.db.responses
        query = self.query(survey)
        field = ANSWER_FIELDS[q['type']]
        base = [{'$match': query}, {'$unwind': '$answers'},
                {'$match': {'answers.questionId': q['questionId'], f'answers.{field}': {'$exists': True}}}]
        count = list(collection.aggregate(base + [{'$group': {'_id': None, 'answerCount': {'$sum': 1}, 'people': {'$addToSet': '$respondentKey'},
                    **({'mean': {'$avg': '$answers.numberValue'}} if q['type'] == 'NUMBER' else {})}}]))
        total = count[0] if count else {'answerCount': 0, 'people': [], 'mean': None}
        result = {'questionId': q['questionId'], 'title': q['title'], 'type': q['type'], 'answerCount': total['answerCount'],
                  'respondentCount': len(total['people']), 'reachedCount': collection.count_documents(dict(query, visitedQuestionIds=q['questionId']))}
        if q['type'] in ('SINGLE', 'MULTI'):
            steps = [{'$unwind': '$answers.selectedOptionIds'}] if q['type'] == 'MULTI' else []
            counts = {r['_id']: r for r in collection.aggregate(base + steps + [{'$group': {
                '_id': f'$answers.{field}', 'count': {'$sum': 1}, 'people': {'$addToSet': '$respondentKey'}}}])}
            result['options'] = [{'optionId': o['optionId'], 'label': o['label'], 'count': counts.get(o['optionId'], {}).get('count', 0),
                                  'respondentCount': len(counts.get(o['optionId'], {}).get('people', []))} for o in q['options']]
        if q['type'] == 'NUMBER': result['mean'] = wire(total['mean'])
        return result

    def all(self, user, survey_id):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        version_check(survey)
        query = self.query(survey)
        participants = list(self.store.db.responses.aggregate([{'$match': query}, {'$group': {'_id': '$respondentKey'}}, {'$count': 'count'}]))
        return {'surveyId': str(survey['_id']), 'contentVersion': survey['contentVersion'],
                'responseCount': self.store.db.responses.count_documents(query),
                'respondentCount': participants[0]['count'] if participants else 0,
                'questions': [self.question(survey, q) for q in survey['questions']]}

    def one(self, user, survey_id, question_id):
        survey, question = self.owned_question(user, survey_id, question_id)
        return self.question(survey, question)

    def owned_question(self, user, survey_id, question_id):
        survey = self.store.surveys.owned(survey_id, user['_id'])
        version_check(survey)
        q = next((q for q in survey['questions'] if q['questionId'] == question_id), None)
        if not q: fail('not_found', '题目不存在', 404)
        return survey, q

    def answers(self, user, survey_id, question_id, skip, limit):
        survey, q = self.owned_question(user, survey_id, question_id)
        field = ANSWER_FIELDS[q['type']]
        pipeline = [{'$match': self.query(survey)}, {'$unwind': '$answers'},
                    {'$match': {'answers.questionId': question_id, f'answers.{field}': {'$exists': True}}}]
        counts = list(self.store.db.responses.aggregate(pipeline + [{'$count': 'n'}]))
        rows = self.store.db.responses.aggregate(pipeline + [{'$sort': {'submittedAt': -1, '_id': -1}}, {'$skip': skip}, {'$limit': limit},
                 {'$project': {'_id': 1, 'submittedAt': 1, 'participationMode': 1, 'identifiedUserId': 1, 'answers': 1}}])
        items = []
        for row in rows:
            item = {'responseId': str(row['_id']), 'submittedAt': wire(row['submittedAt']),
                    'participationMode': row['participationMode'], 'value': wire(row['answers'][field])}
            if row['participationMode'] == 'IDENTIFIED': item['identifiedUserId'] = str(row['identifiedUserId'])
            items.append(item)
        return {'items': items, 'total': counts[0]['n'] if counts else 0, 'skip': skip, 'limit': limit}
