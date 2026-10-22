import shutil
from uuid import uuid4
from bson import Decimal128
from pymongo.errors import WriteError, DuplicateKeyError
import pytest
from scripts.generate_history_baseline import build
from scripts.history_baseline import BASELINE, load_fixture, restore, verify, canonical, safe_database
from app.domain import walk, unpack_answers
from app.repositories import from_bson
from app.security import verify_password


def test_deterministic_fixture_and_valid_paths():
    fixture = load_fixture()
    assert canonical(fixture) == canonical(build())
    questions = fixture['surveys'][0]['questions']
    for raw in fixture['responses']:
        response = from_bson(raw)
        values = unpack_answers(questions, response['answers'])
        path, kept, pending = walk(questions, values)
        assert path == response['visitedQuestionIds'] and set(kept) == set(values)
        assert (pending is None) == (response['status'] == 'SUBMITTED')
        assert 'identifiedUserId' not in raw
    assert fixture['sessions'] == []
    assert not verify_password(fixture['users'][0]['passwordHash'], 'any-password')


def test_tampered_fixture_rejected(tmp_path):
    shutil.copytree(BASELINE, tmp_path / 'fixture')
    path = tmp_path / 'fixture' / 'responses.json'
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='SHA256'):
        load_fixture(tmp_path / 'fixture')


@pytest.mark.parametrize('name', ['questionnaire_stage1', 'admin', 'survey_history_', 'survey_history_x.y'])
def test_restore_requires_dedicated_database(name):
    with pytest.raises(ValueError):
        safe_database(name)


def test_restore_and_readonly_verify(application):
    name = 'survey_history_test_' + uuid4().hex
    db = application.store.client[name]
    try:
        result = restore(db)
        assert result['collections'] == dict(users=1, surveys=1, responses=4, sessions=0)
        assert result['stats']['responseCount'] == 3 and result['stats']['respondentCount'] == 2
        assert result['stats']['questions'][2]['mean'] == '15'
        assert isinstance(db.responses.find_one({'answers.numberValue': {'$exists': True}})['answers'][2]['numberValue'], Decimal128)
        assert {i['name'] for i in db.responses.list_indexes()} >= {'single_submission', 'attempt_idempotency', 'submitted_stats'}
        assert all(db.get_collection(n).options()['validationLevel'] == 'strict' for n in ['users', 'surveys', 'responses', 'sessions'])
        with pytest.raises(ValueError, match='覆盖'):
            restore(db)
        assert verify(db) == result
        duplicate = db.responses.find_one()
        duplicate.pop('_id')
        with pytest.raises(DuplicateKeyError):
            db.responses.insert_one(duplicate)
        with pytest.raises(WriteError):
            db.responses.update_one({}, {'$set': {'contentVersion': 99}})
        assert verify(db) == result
        db.responses.update_one({}, {'$set': {'revision': 99}})
        with pytest.raises(ValueError, match='responses'):
            verify(db)
    finally:
        assert name.startswith('survey_history_test_') and len(name) == len('survey_history_test_') + 32
        application.store.client.drop_database(name)
