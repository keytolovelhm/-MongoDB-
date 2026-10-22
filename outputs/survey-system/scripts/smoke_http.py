"""Real TCP HTTP startup and optional shipped-JavaScript DOM integration checks."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
import time
from uuid import uuid4
import httpx
from pymongo import MongoClient
import uvicorn

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.main import create_app


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mongod',default='mongod');parser.add_argument('--data-dir',required=True)
    parser.add_argument('--report-dir',default='docs/test-results/smoke-01')
    parser.add_argument('--node');parser.add_argument('--jsdom-module')
    args=parser.parse_args();project=Path(__file__).resolve().parents[1]
    report=(project/args.report_dir).resolve();report.mkdir(parents=True,exist_ok=True)
    data=Path(args.data_dir).resolve();data.mkdir(parents=True,exist_ok=True)
    db_port,port=free_port(),free_port();uri=f'mongodb://127.0.0.1:{db_port}';base=f'http://127.0.0.1:{port}'
    process=subprocess.Popen([args.mongod,'--dbpath',str(data),'--port',str(db_port),'--bind_ip','127.0.0.1','--logpath',str(data/'mongo.log')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    client=MongoClient(uri,serverSelectionTimeoutMS=1000,connectTimeoutMS=500)
    server=thread=None;database='survey_smoke_'+uuid4().hex;checks=[]
    try:
        for _ in range(20):
            try:client.admin.command('ping');break
            except Exception:
                if process.poll() is not None:raise RuntimeError('独立MongoDB启动失败')
                time.sleep(.2)
        else:raise RuntimeError('MongoDB连接超时')
        settings=Settings(uri,database,'smoke-test-secret-'+uuid4().hex)
        server=uvicorn.Server(uvicorn.Config(create_app(settings),host='127.0.0.1',port=port,log_level='warning'))
        thread=Thread(target=server.run,daemon=True);thread.start()
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        else:raise RuntimeError('HTTP服务启动失败')
        # Local verification must connect to loopback directly, not inherit an HTTP proxy.
        with httpx.Client(base_url=base,timeout=10,trust_env=False) as http:
            health=http.get('/api/health')
            assert health.status_code==200, (health.status_code,health.text[:500])
            assert health.json()['status']=='ok';checks.append('real TCP health endpoint')
            assert '问卷工作台' in http.get('/').text;checks.append('HTML served with UTF-8')
            for file in ['app.js','core.js','editor.js','filler.js','stats.js','style.css']:
                assert http.get('/static/'+file).status_code==200
            checks.append('all frontend static assets served')
            data_user={'username':'http_'+uuid4().hex[:8],'password':'HTTP-test-password-123'}
            assert http.post('/api/auth/register',json=data_user).status_code==201
            login=http.post('/api/auth/login',json=data_user);assert login.status_code==200
            token=login.json()['csrfToken'];http.headers['X-CSRF-Token']=token
            assert http.get('/api/auth/me').status_code==200;checks.append('HTTP cookie login and CSRF')
            payload={'title':'HTTP启动验证','questions':[{'questionId':'q1','order':0,'title':'数字','type':'NUMBER','required':True}]}
            created=http.post('/api/surveys',json=payload);assert created.status_code==201,created.text
            survey=created.json();published=http.post('/api/surveys/'+survey['id']+'/publish',json={'revision':survey['revision']});assert published.status_code==200
            started=http.post('/api/public/'+survey['shareSlug']+'/attempts',json={'attemptKey':uuid4().hex});assert started.status_code==201
            attempt=started.json();saved=http.put('/api/attempts/'+attempt['id']+'/answer',json={'revision':attempt['revision'],'questionId':'q1','value':'0.1'});assert saved.status_code==200
            final=http.post('/api/attempts/'+attempt['id']+'/submit',json={'revision':saved.json()['revision']});assert final.status_code==200
            result=http.get('/api/surveys/'+survey['id']+'/stats').json();assert result['responseCount']==1 and result['questions'][0]['mean']=='0.1'
            checks.append('create publish fill submit statistics over TCP')
            spec=http.get('/openapi.json').json();(report/'openapi.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
            checks.append('OpenAPI export')
        if args.node:
            environment={**os.environ,'NODE_NO_WARNINGS':'0','NODE_USE_ENV_PROXY':'0'}
            if args.jsdom_module:environment['JSDOM_MODULE']=Path(args.jsdom_module).resolve().as_uri()
            result=subprocess.run([args.node,'--experimental-vm-modules',str(project/'tests/frontend/smoke.mjs'),base,str(report/'frontend-dom.json')],env=environment,cwd=project,capture_output=True,text=True,encoding='utf-8',timeout=60)
            (report/'frontend-output.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            print(result.stdout,flush=True)
            if result.returncode:raise RuntimeError('前端DOM验证失败，见frontend-output.txt')
        (report/'http-smoke.json').write_text(json.dumps({'passed':len(checks),'failed':0,'checks':checks,'mongoVersion':client.server_info()['version']},ensure_ascii=False,indent=2),encoding='utf-8')
        print('HTTP_SMOKE_PASSED',len(checks),flush=True)
        return 0
    except Exception as exc:
        (report/'http-smoke-failure.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'error':str(exc)},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    finally:
        if server:server.should_exit=True
        if thread:thread.join(timeout=10)
        if process.poll() is None:
            assert database.startswith('survey_smoke_')
            client.drop_database(database)
            try:client.admin.command('shutdown',force=True,timeoutSecs=3)
            except Exception:pass
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
        client.close()


if __name__=='__main__':sys.exit(main())
