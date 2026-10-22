"""One-command standalone MongoDB + web server for local coursework demonstration."""
import argparse
from pathlib import Path
import os
import subprocess
import sys
import time
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError
from bson.codec_options import CodecOptions
import uvicorn


def mongo_pid(client):
    # MongoDB 6 on Windows can emit non-UTF8 text in diagnostic serverStatus fields.
    # Decode only this diagnostic command tolerantly; business data stays strict UTF-8.
    return client.admin.command('serverStatus', codec_options=CodecOptions(unicode_decode_error_handler='replace')).get('pid')


def main():
    parser=argparse.ArgumentParser(description='启动独立本地MongoDB和网页，不修改已有MongoDB服务')
    parser.add_argument('--mongod',default='mongod')
    parser.add_argument('--db-port',type=int,default=27030)
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--data-dir',default=str(Path(__file__).parent/'.runtime'/'mongo'))
    args=parser.parse_args()
    project=Path(__file__).resolve().parent
    data=Path(args.data_dir).resolve();data.mkdir(parents=True,exist_ok=True)
    uri=f'mongodb://127.0.0.1:{args.db_port}'
    if not (project/'.env').exists():
        subprocess.run([sys.executable,str(project/'scripts'/'configure.py'),'--mongo-uri',uri],check=True)
    # The child mongod and this web server share the same local execution context.
    process=subprocess.Popen([args.mongod,'--dbpath',str(data),'--port',str(args.db_port),'--bind_ip','127.0.0.1',
                              '--logpath',str(data/'mongo.log')],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    client=MongoClient(uri,serverSelectionTimeoutMS=1000,connectTimeoutMS=500)
    owned = False
    try:
        for _ in range(20):
            if process.poll() is not None:raise RuntimeError('MongoDB启动失败，端口可能被占用；请查看独立数据目录的mongo.log')
            try:
                client.admin.command('ping')
                if mongo_pid(client) != process.pid:
                    raise RuntimeError('端口上的MongoDB进程不属于本启动器，请更换--db-port')
                owned = True
                break
            except ServerSelectionTimeoutError:time.sleep(.2)
        else:raise RuntimeError('MongoDB启动超时')
        # Check ownership again: never use an already-listening user service after our child fails.
        if process.poll() is not None:raise RuntimeError('新建MongoDB未持续运行')
        os.environ['MONGO_URI']=uri
        print(f'本地问卷系统 http://127.0.0.1:{args.port}；MongoDB {args.db_port}；Ctrl+C结束',flush=True)
        uvicorn.run('app.main:app',host='127.0.0.1',port=args.port)
    finally:
        if process.poll() is None:
            try:
                # Confirm PID, including on exit: a port can be reused by another process.
                if owned and mongo_pid(client) == process.pid:
                    client.admin.command('shutdown',force=True,timeoutSecs=3)
            except AutoReconnect:pass
            except Exception:pass
            if not owned:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
        client.close()


if __name__=='__main__':main()
