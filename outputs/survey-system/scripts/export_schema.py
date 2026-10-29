import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.runtime_schema import RUNTIME_SCHEMAS as SCHEMAS

target = Path(__file__).resolve().parents[1] / 'docs' / 'mongodb-schema.json'
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(SCHEMAS, ensure_ascii=False, indent=2), encoding='utf-8')
print(target.name)
