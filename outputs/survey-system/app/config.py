from dataclasses import dataclass
from pathlib import Path
import os


def load_env(path: Path | None = None) -> None:
    path = path or Path(__file__).resolve().parents[1] / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    database: str
    secret: str
    secure_cookie: bool = False
    session_hours: int = 12

    @classmethod
    def from_env(cls):
        load_env()
        secret = os.getenv('APP_SECRET', '')
        if len(secret) < 32:
            raise RuntimeError('请先运行 python scripts/configure.py 生成本地配置，APP_SECRET至少32字符')
        return cls(os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017'),
                   os.getenv('MONGO_DATABASE', 'questionnaire_stage1'), secret,
                   os.getenv('SECURE_COOKIE', 'false').lower() == 'true')
