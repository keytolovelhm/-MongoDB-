"""Real MongoDB aggregation by exact immutable version, with bounded disclosure."""
from decimal import Decimal, localcontext
from bson.decimal128 import Decimal128, create_decimal128_context
from .domain import number
from .errors import fail
from .repositories import oid

# Proposed operational parameter, not a student-confirmed final privacy decision.
PRIVACY_K = 5
PRIVACY_POLICY_VERSION = 1


def empty():
    return {'answerCount': 0, 'responseCount': 0, 'sum': Decimal(0), 'groupCount': 0, 'cells': {}}


def add_summary(target, value):
    with localcontext(create_decimal128_context()):
        target['sum'] += value['sum']
    for k in ('answerCount', 'responseCount', 'groupCount'): target[k] += value[k]
    for key, cell in value['cells'].items():
        result = target['cells'].setdefault(key, {'count': 0, 'groups': 0})
        result['count'] += cell['count']; result['groups'] += cell['groups']


class LibraryStats:
    def __init__(self, store, library, usage):
        self.db, self.library, self.usage = store.db, library, usage

    def aggregate_survey(self, survey, questions, version):
        typ = version['payload']['type']
        field = {'SINGLE': 'selectedOptionId', 'MULTI': 'selectedOptionIds', 'NUMBER': 'numberValue', 'TEXT': 'textValue'}[typ]
        pipeline = [
            {'$match': {'surveyId': survey['_id'], 'status': 'SUBMITTED', 'contentVersion': survey['contentVersion']}},
            {'$unwind': '$answers'},
            {'$match': {'answers.questionId': {'$in': questions}, 'answers.' + field: {'$exists': True}}},
            {'$match': {'$expr': {'$in': ['$answers.questionId', '$visitedQuestionIds']}}},
            {'$group': {'_id': {'responseId': '$_id', 'questionId': '$answers.questionId'},
                        'respondent': {'$first': '$respondentKey'}, 'value': {'$first': '$answers.' + field}}},
        ]
        totals = [{'$group': {'_id': None, 'count': {'$sum': 1}, 'sum': {'$sum': '$value' if typ == 'NUMBER' else 0}}}]
        facets = {'totals': totals, 'responses': [{'$group': {'_id': '$_id.responseId'}}, {'$count': 'count'}],
                  'groups': [{'$group': {'_id': '$respondent'}}, {'$count': 'count'}]}
        if typ != 'TEXT':
            cell_pipeline = []
            if typ == 'MULTI': cell_pipeline.append({'$unwind': '$value'})
            if typ == 'NUMBER':
                cuts = [Decimal128(number(v)) for v in version['summaryPolicy']['numericCuts']]
                cell = {'$switch': {'branches': [{'case': {'$lt': ['$value', cut]}, 'then': i} for i, cut in enumerate(cuts)],
                                    'default': len(cuts)}} if cuts else 0
            else:
                cell = '$value'
            # Group twice: count answers and distinct within-survey respondents per cell.
            cell_pipeline += [{'$group': {'_id': {'cell': cell, 'respondent': '$respondent'}, 'count': {'$sum': 1}}},
                              {'$group': {'_id': '$_id.cell', 'count': {'$sum': '$count'}, 'groups': {'$sum': 1}}}]
            facets['cells'] = cell_pipeline
        result = list(self.db.responses.aggregate(pipeline + [{'$facet': facets}], allowDiskUse=True))[0]
        total = result['totals'][0] if result['totals'] else {'count': 0, 'sum': Decimal128('0')}
        raw_sum = total['sum']
        return {'answerCount': total['count'], 'responseCount': result['responses'][0]['count'] if result['responses'] else 0,
                'groupCount': result['groups'][0]['count'] if result['groups'] else 0,
                'sum': raw_sum.to_decimal() if isinstance(raw_sum, Decimal128) else Decimal(raw_sum),
                'cells': {str(c['_id']): {'count': c['count'], 'groups': c['groups']} for c in result.get('cells', [])}}

    @staticmethod
    def public(summary, version):
        payload = version['payload']; typ = payload['type']
        result = {'answerCount': summary['answerCount'], 'responseCount': summary['responseCount'], 'mean': None, 'distribution': []}
        if typ == 'NUMBER':
            with localcontext(create_decimal128_context()):
                result['mean'] = str(summary['sum'] / summary['answerCount']) if summary['answerCount'] else None
            cuts = version['summaryPolicy']['numericCuts']
            result['distribution'] = [{'lower': cuts[i-1] if i else None, 'upper': cuts[i] if i < len(cuts) else None,
                                       'count': summary['cells'].get(str(i), {}).get('count', 0)} for i in range(len(cuts)+1)]
        elif typ in ('SINGLE', 'MULTI'):
            result['distribution'] = [{'optionId': o['optionId'], 'label': o['label'],
                                      'count': summary['cells'].get(o['optionId'], {}).get('count', 0)} for o in payload['options']]
        return result

    def all(self, user, item_id, version_ids):
        root = self.library.root(item_id)
        author = root['ownerId'] == user['_id']
        versions = [self.library.version(v) for v in dict.fromkeys(version_ids)]
        if not versions or len(versions) > 20: fail('version_range', '请选择1至20个确切版本', 422)
        if any(v['libraryQuestionId'] != root['_id'] for v in versions): fail('not_found', '版本不属于本题', 404)
        instances = self.usage.instances(user, root)
        available = {v['_id'] for s, q, v, paused in instances}
        # USE permits content reuse only. It does not admit arbitrary foreign statistics.
        if not author and any(v['_id'] not in available for v in versions):
            fail('not_found', '无该版本的自有采用实例', 404)
        results = []
        for version in versions:
            own, foreign = empty(), empty()
            sources = {}
            foreign_sources = len({s['_id'] for s, q, v, _ in instances
                                   if v['_id'] == version['_id'] and s['ownerId'] != user['_id']})
            for survey, q, v, _ in instances:
                if v['_id'] == version['_id'] and survey['status'] != 'DRAFT':
                    entry = sources.setdefault(survey['_id'], (survey, []))
                    entry[1].append(q['questionId'])
            for survey, question_ids in sources.values():
                is_own = survey['ownerId'] == user['_id']
                add_summary(own if is_own else foreign, self.aggregate_survey(survey, question_ids, version))
            status = 'NO_FOREIGN_SOURCES' if not foreign_sources else (
                'INSUFFICIENT_SAMPLE' if foreign['groupCount'] < PRIVACY_K else (
                    'PRIVACY_SUPPRESSED' if any(c['count'] and c['groups'] < PRIVACY_K for c in foreign['cells'].values()) else 'AVAILABLE'))
            combined = empty(); add_summary(combined, own); add_summary(combined, foreign)
            result = {'versionId': str(version['_id']), 'versionNo': version['versionNo'], 'type': version['payload']['type'],
                      'own': self.public(own, version), 'foreignStatus': status,
                      'foreign': self.public(foreign, version) if status == 'AVAILABLE' else None,
                      'combined': self.public(combined, version) if status in ('AVAILABLE', 'NO_FOREIGN_SOURCES') else None}
            results.append(result)
        return {'scope': 'AUTHOR_ALL' if author else 'OWN', 'privacyPolicyVersion': PRIVACY_POLICY_VERSION,
                'privacyK': PRIVACY_K, 'privacyKConfirmed': False, 'versions': results}
