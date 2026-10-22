"""Generate deterministic, entirely synthetic phase-one BSON history (no real data)."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys
from bson import ObjectId, json_util

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models import Question
from app.domain import validate_definition, walk, pack_answers
from app.repositories import to_bson, wire


def build():
    stamp = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    owner = ObjectId('100000000000000000000001')
    survey_id = ObjectId('200000000000000000000001')
    def q(qid, order, title, typ, **kwargs):
        return Question(questionId=qid, order=order, title=title, type=typ, **kwargs).model_dump()
    questions = [
        q('q_route', 0, '填写路径', 'SINGLE', required=True,
          options=[{'optionId': 'full', 'label': '完整'}, {'optionId': 'short', 'label': '简短'}],
          rules=[{'ruleId': 'route_short', 'priority': 0,
                  'condition': {'op': 'eq', 'value': 'short'}, 'target': 'q_score'}]),
        q('q_tools', 1, '工具偏好', 'MULTI',
          options=[{'optionId': 'x', 'label': '工具X'}, {'optionId': 'y', 'label': '工具Y'},
                   {'optionId': 'z', 'label': '工具Z'}], constraints={'minSelections': 1, 'maxSelections': 2}),
        q('q_score', 2, '示例评分', 'NUMBER', constraints={'minValue': '0', 'maxValue': '100'}),
        q('q_note', 3, '合成备注', 'TEXT', required=True, constraints={'maxLength': 50}),
    ]
    survey = dict(_id=survey_id, ownerId=owner, shareSlug='phase1-history-v1', title='阶段一合成历史问卷',
                  description='仅用于兼容性回归，无真实个人信息', anonymousEnabled=True,
                  allowMultipleSubmissions=True, status='CLOSED', closesAt=None, questions=questions,
                  schemaVersion=1, contentVersion=1, ruleLanguageVersion=1, revision=2,
                  createdAt=stamp, updatedAt=stamp + timedelta(days=1), publishedAt=stamp,
                  closedAt=stamp + timedelta(days=1))
    validate_definition(survey, publishing=True)
    cases = [
        ('p1', {'q_route': 'full', 'q_tools': ['x', 'y'], 'q_score': '10', 'q_note': '合成备注甲'}, True),
        ('p1', {'q_route': 'short', 'q_score': '20', 'q_note': '合成备注乙'}, True),
        ('p2', {'q_route': 'full', 'q_tools': ['y'], 'q_score': None, 'q_note': '合成备注丙'}, True),
        ('p3', {'q_route': 'full'}, False),
    ]
    responses = []
    for index, (pseudonym, values, submitted) in enumerate(cases, 1):
        path, kept, pending = walk(questions, values)
        assert (pending is None) == submitted
        answers = pack_answers(questions, kept)
        now = stamp + timedelta(minutes=index)
        doc = dict(_id=ObjectId(f'30000000000000000000000{index}'), surveyId=survey_id,
                   contentVersion=1, schemaVersion=1, identityKeyVersion=1,
                   respondentKey=hashlib.sha256(('synthetic-history-only:' + pseudonym).encode()).hexdigest(),
                   participationMode='ANONYMOUS', repeatMode='MULTIPLE', attemptKey=f'baseline_attempt_{index}',
                   status='SUBMITTED' if submitted else 'DRAFT', answers=answers,
                   visitedQuestionIds=path, revision=len(kept) + int(submitted), startedAt=now,
                   updatedAt=now, submittedAt=now if submitted else None)
        if submitted:
            doc['admittedAt'] = now
            doc['submissionDigest'] = hashlib.sha256(json.dumps(wire(dict(answers=answers, path=path, version=1)),
                                                               ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        responses.append(to_bson(doc))
    return {'users': [dict(_id=owner, username='synthetic_owner', usernameNormalized='synthetic_owner',
                           passwordHash='DISABLED_SYNTHETIC_HISTORY_ACCOUNT', createdAt=stamp, schemaVersion=1)],
            'surveys': [survey], 'responses': responses, 'sessions': []}


def main():
    folder = Path(__file__).resolve().parents[1] / 'data' / 'phase1-history-v1'
    folder.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, docs in build().items():
        raw = (json_util.dumps(docs, json_options=json_util.CANONICAL_JSON_OPTIONS,
                               ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        (folder / (name + '.json')).write_bytes(raw)
        records[name] = {'count': len(docs), 'sha256': hashlib.sha256(raw).hexdigest()}
    manifest = dict(baseline='phase1-history-v1', format='MongoDB Canonical Extended JSON',
                    synthetic=True, versions=dict(schemaVersion=1, contentVersion=1, ruleLanguageVersion=1,
                                                   identityKeyVersion=1), collections=records)
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Generated deterministic synthetic history:', folder)


if __name__ == '__main__':
    main()
