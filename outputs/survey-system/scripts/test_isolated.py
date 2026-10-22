"""Run tests against a fresh local MongoDB in the same process group.

Useful in execution sandboxes with per-command loopback isolation; also works on normal Windows.
No existing MongoDB service, configuration or application database is modified.
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from pymongo import MongoClient


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mongod',default='mongod')
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--report-dir',default='docs/test-results')
    parser.add_argument('pytest_args',nargs='*')
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]
    data=Path(args.data_dir).resolve();data.mkdir(parents=True,exist_ok=True)
    report=(project/args.report_dir).resolve();report.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    command=[args.mongod,'--dbpath',str(data),'--port',str(port),'--bind_ip','127.0.0.1','--logpath',str(data/'mongod.log')]
    process=subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    uri=f'mongodb://127.0.0.1:{port}'
    client=MongoClient(uri,serverSelectionTimeoutMS=1000,connectTimeoutMS=500)
    try:
        for _ in range(20):
            try:client.admin.command('ping');break
            except Exception:
                if process.poll() is not None:raise RuntimeError('临时MongoDB启动失败，请查看mongod.log')
                time.sleep(.2)
        else:raise RuntimeError('临时MongoDB连接超时')
        print('MongoDB',client.server_info()['version'],'standalone; temporary port',port,flush=True)
        environment={**os.environ,'MONGO_TEST_URI':uri,'PYTHONUTF8':'1','COVERAGE_FILE':str(report/'.coverage')}
        cmd=[sys.executable,'-m','pytest','-v','--junitxml='+str(report/'junit.xml'),
             '--cov=app','--cov-report=term-missing','--cov-report=json:'+str(report/'coverage.json'),*args.pytest_args]
        with (report/'pytest-output.txt').open('w',encoding='utf-8') as out:
            testing=subprocess.Popen(cmd,cwd=project,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
            for line in testing.stdout:print(line,end='',flush=True);out.write(line);out.flush()
            result=testing.wait()
        return result
    finally:
        # Terminate only the process created above, never a discovered user service.
        client.close()
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':sys.exit(main())
