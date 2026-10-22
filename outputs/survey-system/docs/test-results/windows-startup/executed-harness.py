"""Automated startup acceptance; executes actual launcher with controlled Uvicorn stop.
No human browser interaction or real Ctrl+C is claimed.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Thread
import time
import httpx
from pymongo import MongoClient
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs' / 'survey-system'
FRESH = ROOT / 'work' / 'fresh-windows' / '中文 空格 三次' / 'survey-system'
REPORT = SOURCE / 'docs' / 'test-results' / 'windows-startup'
MONGOD = r'D:\MongoDB\Server\6.0\bin\mongod.exe'
REPORT.mkdir(parents=True, exist_ok=True)
assert not FRESH.exists(), 'Use a new scratch location; never overwrite an existing run'
shutil.copytree(SOURCE, FRESH, ignore=shutil.ignore_patterns('.env', '.venv', '.runtime', '__pycache__', '.pytest_cache', '.coverage'))
sys.path.insert(0, str(FRESH))
import run_local


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


db_port, port = free_port(), free_port()
checks = []
database = 'questionnaire_stage1'
for key in ['APP_SECRET', 'MONGO_URI', 'MONGO_DATABASE', 'SECURE_COOKIE']:
    os.environ.pop(key, None)
original_run = uvicorn.run


def bounded_web(app, **kwargs):
    server = uvicorn.Server(uvicorn.Config(app, **kwargs, log_level='warning'))
    errors = []
    def probe():
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.05)
            else:
                raise RuntimeError('Web startup timeout')
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=5) as client:
                assert client.get('/api/health').json()['status'] == 'ok'
                assert '问卷工作台' in client.get('/').text
                for asset in ['app.js', 'core.js', 'editor.js', 'filler.js', 'stats.js', 'style.css']:
                    assert client.get('/static/' + asset).status_code == 200
                creds = {'username': 'startup_probe', 'password': 'Synthetic-Startup-123'}
                if len(checks) == 0:
                    assert client.post('/api/auth/register', json=creds).status_code == 201
                login = client.post('/api/auth/login', json=creds)
                assert login.status_code == 200
                client.headers['X-CSRF-Token'] = login.json()['csrfToken']
                if len(checks) == 0:
                    survey = client.post('/api/surveys', json={'title': '启动持久化验证', 'questions': []})
                    assert survey.status_code == 201
                else:
                    assert client.get('/api/surveys').json()['total'] == 1
        except BaseException as exc:
            errors.append(repr(exc))
        finally:
            server.should_exit = True
    thread = Thread(target=probe, daemon=True)
    thread.start()
    server.run()
    thread.join(timeout=15)
    assert not thread.is_alive() and not errors, errors


try:
    uvicorn.run = bounded_web
    sys.argv = ['run_local.py', '--mongod', MONGOD, '--db-port', str(db_port), '--port', str(port)]
    # Deliberately launch from outside project directory.
    os.chdir(ROOT / 'work')
    run_local.main()
    env_hash = hashlib.sha256((FRESH / '.env').read_bytes()).hexdigest()
    checks.append('fresh .env creation, independent MongoDB, actual TCP HTML/assets/register/login/create from Unicode+space path')
    run_local.main()
    assert hashlib.sha256((FRESH / '.env').read_bytes()).hexdigest() == env_hash
    checks.append('restart preserves .env, secret, account and saved survey')

    other_data = ROOT / 'work' / 'fresh-windows' / 'other-mongo'
    other_data.mkdir()
    other = subprocess.Popen([MONGOD, '--dbpath', str(other_data), '--port', str(db_port),
                              '--bind_ip', '127.0.0.1', '--logpath', str(other_data / 'mongo.log')],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    client = MongoClient(f'mongodb://127.0.0.1:{db_port}', serverSelectionTimeoutMS=1000)
    try:
        for _ in range(30):
            try:
                assert run_local.mongo_pid(client) == other.pid
                break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError('Reference MongoDB startup timeout')
        try:
            run_local.main()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Occupied MongoDB port was not rejected')
        assert other.poll() is None and client.admin.command('ping')['ok'] == 1
        checks.append('occupied database port is rejected and existing MongoDB remains alive')
        for script_args in [
            ['scripts/init_db.py'],
            ['scripts/history_baseline.py', 'restore', '--uri', f'mongodb://127.0.0.1:{db_port}', '--database', 'survey_history_cli_v1'],
            ['scripts/history_baseline.py', 'verify', '--uri', f'mongodb://127.0.0.1:{db_port}', '--database', 'survey_history_cli_v1'],
        ]:
            result = subprocess.run([sys.executable, *script_args], cwd=FRESH, env=os.environ,
                                    capture_output=True, encoding='utf-8', timeout=15)
            assert result.returncode == 0, result.stderr
            if len(script_args) > 1:
                parsed = json.loads(result.stdout)
                assert parsed['stats']['responseCount'] == 3
                filename = 'cli-' + script_args[1] + '.json'
            else:
                filename = 'init-db.txt'
            (REPORT / filename).write_text(result.stdout, encoding='utf-8')
        checks.append('README init_db and history restore/verify CLI commands succeed against separate database')
    finally:
        # This process was created above with the same Popen handle and verified PID.
        if other.poll() is None:
            other.terminate()
            other.wait(timeout=10)
        client.close()
    (REPORT / 'result.json').write_text(json.dumps({'passed': len(checks), 'failed': 0,
        'checks': checks, 'python': sys.version, 'mongoVersion': '6.0.27',
        'method': 'Fresh venv; actual launcher, real MongoDB/TCP; controlled Uvicorn exit wrapper',
        'limitations': 'Existing installed Python/MongoDB, not fresh Windows VM. No human browser/Ctrl+C test.'},
        ensure_ascii=False, indent=2), encoding='utf-8')
finally:
    uvicorn.run = original_run
