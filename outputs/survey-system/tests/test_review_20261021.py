"""AI code-review regressions; no student review or manual acceptance is claimed."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from bson import ObjectId
import pytest

from app.domain import validate_definition, walk
from app.errors import AppError
from .helpers import definition, question, rule
from .test_api import published, attempt, answer, submit


def numeric_definition(op, first, second):
    return definition([
        question('q1', 'NUMBER', rules=[rule(op, first, 'q2', 0), rule(op, second, 'END', 1)]),
        question('q2', 'TEXT', order=1),
    ]).model_dump()


@pytest.mark.parametrize('op', ['eq', 'gt', 'gte', 'lt', 'lte'])
def test_numeric_equivalent_thresholds_are_duplicate(op):
    with pytest.raises(AppError) as caught:
        validate_definition(numeric_definition(op, '18', '18.0'), publishing=True)
    assert caught.value.code == 'duplicate_condition' and caught.value.field == 'q1'


@pytest.mark.parametrize('first,second', [
    ('18', '1.8e1'), ('+18', '018.000'), ('-0', '+0.0'), ('0.1', '1e-1'),
    ('1234567890123456789012345678901234', '1234567890123456789012345678901234.0'),
])
def test_numeric_equivalent_spellings_are_duplicate(first, second):
    with pytest.raises(AppError) as caught:
        validate_definition(numeric_definition('eq', first, second))
    assert caught.value.code == 'duplicate_condition'


@pytest.mark.parametrize('first,second', [
    (['18', '20'], ['18.0', '2e1']),
    (['-0', '0.1'], ['0.0', '1e-1']),
    (['18', '18'], ['1.8e1', '18.00']),
])
def test_numeric_equivalent_interval_endpoints_are_duplicate(first, second):
    with pytest.raises(AppError) as caught:
        validate_definition(numeric_definition('between', first, second), publishing=True)
    assert caught.value.code == 'duplicate_condition'


@pytest.mark.parametrize('op1,value1,op2,value2', [
    ('eq', '18', 'eq', '18.01'),
    ('gt', '18', 'gte', '18.0'),
    ('eq', '1234567890123456789012345678901234', 'eq', '1234567890123456789012345678901235'),
    ('between', ['1', '2'], 'between', ['2', '3']),
])
def test_distinct_numeric_conditions_keep_priority_semantics(op1, value1, op2, value2):
    data = numeric_definition(op1, value1, value1)
    data['questions'][0]['rules'][1]['condition'] = {'op': op2, 'value': value2}
    validate_definition(data, publishing=True)


def conservative_questions():
    return [question('q1', rules=[rule('eq', 'a', 'q3')]),
            question('q2', 'TEXT', order=1, required=True), question('q3', 'TEXT', order=2)]


def test_new_pending_question_also_prunes_old_later_answer():
    questions = conservative_questions()
    _, saved, _ = walk(questions, {'q1': 'a', 'q3': 'old later answer'})
    path, kept, pending = walk(questions, {**saved, 'q1': 'b'})
    assert (path, kept, pending) == (['q1', 'q2'], {'q1': 'b'}, 'q2')
    path, kept, pending = walk(questions, {**kept, 'q2': 'newly saved'})
    assert pending == 'q3' and 'q3' not in kept


@pytest.mark.integration
@pytest.mark.parametrize('operation', ['create', 'update', 'publish'])
def test_numeric_duplicates_rejected_at_definition_write_boundaries(env, actor, operation):
    owner = actor()
    data = numeric_definition('gte', '18', '18.0')
    if operation == 'create':
        result = owner.call('POST', '/surveys', data, 422)
        assert env.store.db.surveys.count_documents({}) == 0
    else:
        valid = deepcopy(data)
        valid['questions'][0]['rules'].pop()
        draft = owner.call('POST', '/surveys', valid, 201)
        if operation == 'update':
            result = owner.call('PUT', '/surveys/' + draft['id'], dict(data, revision=draft['revision']), 422)
        else:
            # Simulate a draft written by the earlier version, before this validation fix.
            env.store.db.surveys.update_one({'_id': ObjectId(draft['id'])},
                                           {'$set': {'questions': data['questions']}})
            result = owner.call('POST', f"/surveys/{draft['id']}/publish", {'revision': draft['revision']}, 422)
        actual = env.store.db.surveys.find_one({'_id': ObjectId(draft['id'])})
        assert actual['status'] == 'DRAFT' and actual['revision'] == draft['revision']
    assert result['error']['code'] == 'duplicate_condition'


@pytest.mark.integration
def test_legacy_published_rules_keep_v1_interpretation(env, actor):
    owner = actor()
    data = numeric_definition('eq', '18', '18.0')
    original = deepcopy(data['questions'])
    original[0]['rules'].pop()
    survey = published(owner, original)
    # Construct synthetic frozen history that the pre-fix validator could publish.
    env.store.db.surveys.update_one({'_id': ObjectId(survey['id'])}, {'$set': {'questions': data['questions']}})
    saved = answer(owner, attempt(owner, survey), 'q1', '18.00')
    assert saved['nextQuestionId'] == 'q2'  # First priority still wins; later duplicate is not reinterpreted.
    final = submit(owner, answer(owner, saved, 'q2', 'legacy meaning'))
    assert final['status'] == 'SUBMITTED' and final['contentVersion'] == 1
    stored = env.store.db.surveys.find_one({'_id': ObjectId(survey['id'])})
    assert stored['questions'] == data['questions']
    assert stored['schemaVersion'] == stored['contentVersion'] == stored['ruleLanguageVersion'] == 1
    assert owner.call('GET', f"/surveys/{survey['id']}/stats")['responseCount'] == 1
    owner.call('PUT', '/surveys/' + survey['id'], dict(data, revision=survey['revision']), 409)


@pytest.mark.integration
def test_conservative_pruning_response_and_stats_do_not_restore_later_answer(env, actor):
    owner = actor()
    survey = published(owner, conservative_questions())
    saved = answer(owner, answer(owner, attempt(owner, survey), 'q1', 'a'), 'q3', 'old value')
    changed = answer(owner, saved, 'q1', 'b')
    assert changed['removedQuestionIds'] == ['q3'] and changed['nextQuestionId'] == 'q2'
    changed = answer(owner, changed, 'q2', 'new required answer')
    assert changed['nextQuestionId'] == 'q3' and all(a['questionId'] != 'q3' for a in changed['answers'])
    submit(owner, answer(owner, changed, 'q3', None))
    stats = owner.call('GET', f"/surveys/{survey['id']}/stats/q3")
    assert stats['answerCount'] == 0 and stats['reachedCount'] == 1


@pytest.mark.integration
def test_D09B_close_after_final_snapshot_can_precede_admitted_timestamp(env, actor, monkeypatch):
    import app.attempt_service as attempt_module
    import app.survey_service as survey_module

    owner, later = actor(), actor('later')
    survey = published(owner, [question(typ='TEXT')])
    first = answer(owner, attempt(owner, survey), 'q1', 'snapshot already read')
    late = answer(later, attempt(later, survey), 'q1', 'reads closed snapshot')
    user = env.store.db.users.find_one({'_id': ObjectId(owner.user['id'])})
    boundary = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(survey_module, 'utcnow', lambda: boundary)
    monkeypatch.setattr(attempt_module, 'utcnow', lambda: boundary + timedelta(seconds=1))
    original_get = env.store.surveys.get
    snapshots, closed = [], []

    def close_after_final_read(query):
        snapshot = original_get(query)
        if query == {'_id': ObjectId(survey['id'])}:
            snapshots.append(snapshot)
            if len(snapshots) == 2:  # owned() reads once; submit() then reads its final snapshot.
                closed.append(env.s.surveys.close(user, survey['id'], survey['revision']))
        return snapshot

    monkeypatch.setattr(env.store.surveys, 'get', close_after_final_read)
    final = submit(owner, first)
    assert closed[0]['status'] == 'CLOSED' and snapshots[1]['status'] == 'PUBLISHED'
    assert final['status'] == 'SUBMITTED'
    assert datetime.fromisoformat(final['admittedAt']) > datetime.fromisoformat(closed[0]['closedAt'])
    assert submit(later, late, 409)['error']['code'] == 'survey_unavailable'
    assert env.store.db.responses.count_documents({'status': 'SUBMITTED'}) == 1
