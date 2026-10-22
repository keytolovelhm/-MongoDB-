"""Restore only to an explicitly named empty history DB; verification is read-only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from bson import json_util
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schema import ensure_schema
from app.repositories import Surveys
from app.stats_service import StatsService

BASELINE = Path(__file__).resolve().parents[1] / 'data' / 'phase1-history-v1'
COLLECTIONS = ('users', 'surveys', 'responses', 'sessions')


def canonical(value):
    return json_util.dumps(value, json_options=json_util.CANONICAL_JSON_OPTIONS,
                           sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def load_fixture(folder=BASELINE):
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['baseline'] != 'phase1-history-v1' or set(manifest['collections']) != set(COLLECTIONS):
        raise ValueError('历史基线清单不匹配')
    fixture = {}
    for name in COLLECTIONS:
        raw = (folder / (name + '.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest['collections'][name]['sha256']:
            raise ValueError(f'{name}文件SHA256不匹配')
        fixture[name] = json_util.loads(raw.decode('utf-8'))
        if len(fixture[name]) != manifest['collections'][name]['count']:
            raise ValueError(f'{name}数量不匹配')
    return fixture


def safe_database(name):
    if not re.fullmatch(r'survey_history_[A-Za-z0-9_]{1,40}', name):
        raise ValueError('必须显式使用专属survey_history_开头的数据库名')


def verify(db, folder=BASELINE):
    fixture = load_fixture(folder)
    if set(db.list_collection_names()) != set(COLLECTIONS):
        raise ValueError('数据库必须恰好包含四个基线集合')
    for name, docs in fixture.items():
        actual = list(db[name].find().sort('_id', 1))
        expected = sorted(docs, key=lambda d: d['_id'])
        if canonical(actual) != canonical(expected):
            raise ValueError(f'{name}的BSON类型或文档内容与基线不同')
    store = SimpleNamespace(db=db, surveys=Surveys(db.surveys))
    survey = fixture['surveys'][0]
    stats = StatsService(store).all({'_id': survey['ownerId']}, str(survey['_id']))
    expected_stats = json.loads((Path(folder) / 'expected-stats.json').read_text(encoding='utf-8'))
    if stats != expected_stats:
        raise ValueError('历史统计与预期结果不同')
    return {'baseline': 'phase1-history-v1', 'database': db.name, 'collections': {n: len(d) for n, d in fixture.items()},
            'bsonContent': 'exact match', 'stats': stats}


def restore(db, folder=BASELINE):
    safe_database(db.name)
    fixture = load_fixture(folder)  # Check hashes before touching MongoDB.
    if db.list_collection_names():
        raise ValueError('拒绝覆盖已有集合；请指定全新的专属数据库名')
    ensure_schema(db)
    for name, docs in fixture.items():
        if docs:
            db[name].insert_many(docs, ordered=True)
    # No drop/overwrite/rollback. Leave any failed restore for diagnosis.
    return verify(db, folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'restore', 'verify'])
    parser.add_argument('--uri', default='mongodb://127.0.0.1:27030')
    parser.add_argument('--database')
    args = parser.parse_args()
    if args.action == 'check':
        fixture = load_fixture()
        print(json.dumps({'baseline': 'phase1-history-v1', 'fileHashes': 'verified',
                          'collections': {n: len(d) for n, d in fixture.items()}}, ensure_ascii=False, indent=2))
        return
    if not args.database:
        parser.error('restore/verify必须显式指定--database')
    safe_database(args.database)
    with MongoClient(args.uri, tz_aware=True, serverSelectionTimeoutMS=3000) as client:
        result = (restore if args.action == 'restore' else verify)(client[args.database])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
