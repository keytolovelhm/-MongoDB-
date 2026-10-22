import argparse
import uvicorn
from app.config import load_env

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    load_env()
    uvicorn.run('app.main:app', host=args.host, port=args.port)
