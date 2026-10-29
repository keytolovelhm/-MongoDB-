"""Read-only check of the untouched v1 fixture in a ten-collection runtime database."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.history_baseline import load_fixture, canonical, BASELINE
from app.runtime_schema import RUNTIME_SCHEMAS
from app.repositories import Surveys
from app.stats_service import StatsService


def verify_compatible(db):
    fixture = load_fixture()
    if set(db.list_collection_names()) != set(RUNTIME_SCHEMAS):
        raise ValueError('扩展库集合必须与明确的十集合清单一致')
    for name, expected in fixture.items():
        if canonical(list(db[name].find().sort('_id', 1))) != canonical(sorted(expected, key=lambda d:d['_id'])):
            raise ValueError(name+'原始BSON与第一阶段基线不同')
    survey = fixture['surveys'][0]
    store = SimpleNamespace(db=db, surveys=Surveys(db.surveys))
    stats = StatsService(store).all({'_id':survey['ownerId']}, str(survey['_id']))
    if stats != json.loads((BASELINE/'expected-stats.json').read_text(encoding='utf-8')):
        raise ValueError('旧问卷统计发生变化')
    return {'baseline':'phase1-history-v1','collections':10,'originalBSON':'exact match','stats':stats}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri', default='mongodb://127.0.0.1:27030')
    parser.add_argument('--database', required=True)
    args=parser.parse_args()
    with MongoClient(args.uri,tz_aware=True,serverSelectionTimeoutMS=3000) as client:
        print(json.dumps(verify_compatible(client[args.database]),ensure_ascii=False,indent=2))
