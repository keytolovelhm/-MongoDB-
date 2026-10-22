import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.repositories import Store

store = Store(Settings.from_env())
print('四集合Schema和必要索引已初始化；未清空原数据。')
store.close()
