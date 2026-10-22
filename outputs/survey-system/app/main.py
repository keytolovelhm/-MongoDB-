from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import hmac
import logging
from fastapi import FastAPI, Request, Response, Depends, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError
from .config import Settings
from .errors import AppError, fail
from .models import Credentials, SurveyWrite, SurveyUpdate, Revision, DeadlineUpdate, AttemptCreate, AnswerWrite
from .repositories import Store
from .auth_service import AuthService
from .survey_service import SurveyService
from .attempt_service import AttemptService
from .stats_service import StatsService
from .security import csrf_token

cookie = APIKeyCookie(name='survey_session', auto_error=False)
STATIC = Path(__file__).parent / 'static'


def services(request: Request): return request.app.state.services


def current_user(request: Request, raw: str | None = Depends(cookie)):
    return services(request).auth.authenticate(raw)


def write_user(request: Request, user=Depends(current_user), token: str | None = Header(default=None, alias='X-CSRF-Token')):
    expected = csrf_token(request.app.state.settings.secret, request.cookies.get('survey_session', ''))
    if not token or not hmac.compare_digest(token, expected): fail('csrf_invalid', '请求校验失败，请刷新页面', 403)
    return user


def create_app(settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app):
        cfg = settings or Settings.from_env()
        store = Store(cfg)
        app.state.settings, app.state.store = cfg, store
        app.state.services = SimpleNamespace(auth=AuthService(store, cfg), surveys=SurveyService(store),
                                              attempts=AttemptService(store, cfg), stats=StatsService(store))
        try: yield
        finally: store.close()

    app = FastAPI(title='MongoDB 问卷系统', version='1.0.0', lifespan=lifespan,
                  description='阶段一。登录后填写；匿名仅对创建者隐藏身份。写接口须带会话Cookie及X-CSRF-Token。D09-B按服务端受理检查时刻判定。')

    @app.exception_handler(AppError)
    async def business_error(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message, 'field': exc.field}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg'], 'type': e['type']} for e in exc.errors()]
        return JSONResponse({'error': {'code': 'request_invalid', 'message': '请求格式或字段不合法', 'fields': fields}}, status_code=422)

    @app.exception_handler(PyMongoError)
    async def database_error(request, exc):
        logging.getLogger('survey').error('MongoDB operation failed: %s', type(exc).__name__)
        return JSONResponse({'error': {'code': 'database_unavailable', 'message': '数据库操作暂不可用，请重试；本次未确认保存成功'}}, status_code=503)

    @app.middleware('http')
    async def request_guard(request, call_next):
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'error': {'code': 'origin_invalid', 'message': '不允许跨站修改'}}, status_code=403)
            if len(await request.body()) > 2 * 1024 * 1024:
                return JSONResponse({'error': {'code': 'request_too_large', 'message': '请求不能超过2 MiB'}}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.url.path == '/' or request.url.path.startswith('/survey/'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.get('/api/health', tags=['system'])
    def health(request: Request):
        request.app.state.store.client.admin.command('ping')
        return {'status': 'ok', 'version': '1.0.0', 'schemaVersion': 1}

    @app.post('/api/auth/register', status_code=201, tags=['auth'])
    def register(data: Credentials, request: Request): return services(request).auth.register(data)

    @app.post('/api/auth/login', tags=['auth'])
    def login(data: Credentials, request: Request, response: Response):
        user, raw = services(request).auth.login(data)
        cfg = request.app.state.settings
        response.set_cookie('survey_session', raw, max_age=cfg.session_hours * 3600, httponly=True, samesite='lax', secure=cfg.secure_cookie)
        return {'user': user, 'csrfToken': csrf_token(cfg.secret, raw)}

    @app.get('/api/auth/me', tags=['auth'])
    def me(request: Request, user=Depends(current_user)):
        return {'user': services(request).auth.public(user), 'csrfToken': csrf_token(request.app.state.settings.secret, request.cookies['survey_session'])}

    @app.post('/api/auth/logout', tags=['auth'])
    def logout(request: Request, response: Response, user=Depends(write_user)):
        services(request).auth.logout(request.cookies['survey_session'])
        response.delete_cookie('survey_session')
        return {'ok': True}

    @app.get('/api/surveys', tags=['surveys'])
    def listing(request: Request, skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
        return services(request).surveys.listing(user, skip, limit)

    @app.post('/api/surveys', status_code=201, tags=['surveys'])
    def create(data: SurveyWrite, request: Request, user=Depends(write_user)):
        return services(request).surveys.create(user, data)

    @app.get('/api/surveys/{survey_id}', tags=['surveys'])
    def get(survey_id: str, request: Request, user=Depends(current_user)):
        return services(request).surveys.get(user, survey_id)

    @app.put('/api/surveys/{survey_id}', tags=['surveys'])
    def update(survey_id: str, data: SurveyUpdate, request: Request, user=Depends(write_user)):
        return services(request).surveys.update(user, survey_id, data)

    @app.post('/api/surveys/{survey_id}/publish', tags=['surveys'])
    def publish(survey_id: str, data: Revision, request: Request, user=Depends(write_user)):
        return services(request).surveys.publish(user, survey_id, data.revision)

    @app.post('/api/surveys/{survey_id}/close', tags=['surveys'])
    def close(survey_id: str, data: Revision, request: Request, user=Depends(write_user)):
        return services(request).surveys.close(user, survey_id, data.revision)

    @app.patch('/api/surveys/{survey_id}/deadline', tags=['surveys'])
    def deadline(survey_id: str, data: DeadlineUpdate, request: Request, user=Depends(write_user)):
        return services(request).surveys.deadline(user, survey_id, data)

    @app.get('/api/public/{slug}', tags=['filling'])
    def public_survey(slug: str, request: Request, user=Depends(current_user)):
        return services(request).surveys.for_filling(slug)

    @app.get('/api/public/{slug}/my-attempts', tags=['filling'])
    def recent(slug: str, request: Request, user=Depends(current_user)):
        return services(request).attempts.recent(user, slug)

    @app.post('/api/public/{slug}/attempts', status_code=201, tags=['filling'])
    def attempt_create(slug: str, data: AttemptCreate, request: Request, user=Depends(write_user)):
        return services(request).attempts.create(user, slug, data)

    @app.get('/api/attempts/{attempt_id}', tags=['filling'])
    def attempt_get(attempt_id: str, request: Request, user=Depends(current_user)):
        return services(request).attempts.get(user, attempt_id)

    @app.put('/api/attempts/{attempt_id}/answer', tags=['filling'])
    def answer(attempt_id: str, data: AnswerWrite, request: Request, user=Depends(write_user)):
        return services(request).attempts.answer(user, attempt_id, data)

    @app.post('/api/attempts/{attempt_id}/submit', tags=['filling'])
    def submit(attempt_id: str, data: Revision, request: Request, user=Depends(write_user)):
        return services(request).attempts.submit(user, attempt_id, data.revision)

    @app.get('/api/surveys/{survey_id}/stats', tags=['statistics'])
    def statistics(survey_id: str, request: Request, user=Depends(current_user)):
        return services(request).stats.all(user, survey_id)

    @app.get('/api/surveys/{survey_id}/stats/{question_id}', tags=['statistics'])
    def question_stats(survey_id: str, question_id: str, request: Request, user=Depends(current_user)):
        return services(request).stats.one(user, survey_id, question_id)

    @app.get('/api/surveys/{survey_id}/stats/{question_id}/answers', tags=['statistics'])
    def answers(survey_id: str, question_id: str, request: Request, skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
        return services(request).stats.answers(user, survey_id, question_id, skip, limit)

    app.mount('/static', StaticFiles(directory=STATIC, check_dir=False), name='static')

    @app.get('/', include_in_schema=False)
    @app.get('/survey/{slug}', include_in_schema=False)
    def page(): return FileResponse(STATIC / 'index.html')

    return app


app = create_app()
