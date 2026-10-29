from types import SimpleNamespace
from uuid import uuid4
import os
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.fixture(scope='session')
def application():
    database='survey_test_'+uuid4().hex
    settings=Settings(os.getenv('MONGO_TEST_URI','mongodb://127.0.0.1:27028'),database,'test-key-only-'+'x'*48)
    app=create_app(settings)
    with TestClient(app) as client:
        yield SimpleNamespace(app=app,client=client,store=app.state.store,s=app.state.services,settings=settings)
        assert database.startswith('survey_test_') and len(database)==44
        # Only this randomly named test database is dropped; never application or user databases.
        app.state.store.client.drop_database(database)


@pytest.fixture
def env(application):
    assert application.store.db.name.startswith('survey_test_')
    from app.runtime_schema import RUNTIME_SCHEMAS
    for name in RUNTIME_SCHEMAS:application.store.db[name].delete_many({})
    application.client.cookies.clear()
    return application


class Actor:
    def __init__(self,env,name):
        self.env=env
        data={'username':name,'password':'Test-password-123'}
        r=env.client.post('/api/auth/register',json=data);assert r.status_code==201,r.text
        self.user=r.json()
        r=env.client.post('/api/auth/login',json=data);assert r.status_code==200,r.text
        self.headers={'X-CSRF-Token':r.json()['csrfToken'],'Cookie':'survey_session='+r.cookies['survey_session']}

    def call(self,method,path,data=None,status=200):
        r=self.env.client.request(method,'/api'+path,headers=self.headers,**({'json':data} if data is not None else {}))
        assert r.status_code==status,r.text
        return r.json()


@pytest.fixture
def actor(env):return lambda name='alice':Actor(env,name)
