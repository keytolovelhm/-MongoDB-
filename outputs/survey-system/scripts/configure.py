"""Generate local configuration without printing or embedding a default secret."""
import argparse
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--mongo-uri', default='mongodb://127.0.0.1:27017')
parser.add_argument('--database', default='questionnaire_stage1')
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / '.env'
if path.exists():
    print('已有.env，保留原配置与密钥。需要调整时请编辑文件。')
else:
    path.write_text(f'MONGO_URI={args.mongo_uri}\nMONGO_DATABASE={args.database}\nAPP_SECRET={secrets.token_urlsafe(48)}\nSECURE_COOKIE=false\n', encoding='utf-8')
    print('本地.env已生成。保留APP_SECRET以维持匿名去重身份，不要提交或公开此文件。')
