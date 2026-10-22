from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4
import json
import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128
from pymongo.errors import WriteError, DuplicateKeyError, AutoReconnect
from app.errors import AppError
from app.models import AttemptCreate, AnswerWrite, Credentials
from app.repositories import utcnow, wire
from app.schema import ensure_schema
from .helpers import question, definition, rule

pytestmark=pytest.mark.integration


def published(owner,questions=None,**options):
    survey=owner.call('POST','/surveys',definition(questions,**options).model_dump(mode='json'),201)
    return owner.call('POST',f"/surveys/{survey['id']}/publish",{'revision':survey['revision']})


def attempt(actor,survey,mode='IDENTIFIED',key=None):
    return actor.call('POST',f"/public/{survey['shareSlug']}/attempts",{'attemptKey':key or uuid4().hex,'participationMode':mode},201)


def answer(actor,a,qid,value,status=200):
    return actor.call('PUT',f"/attempts/{a['id']}/answer",{'revision':a['revision'],'questionId':qid,'value':value},status)


def submit(actor,a,status=200):return actor.call('POST',f"/attempts/{a['id']}/submit",{'revision':a['revision']},status)


def test_T01_auth_password_duplicate_logout_and_csrf(env,actor):
    alice=actor()
    doc=env.store.db.users.find_one()
    assert doc['passwordHash'].startswith('$argon2id$') and 'password' not in doc
    assert 'passwordHash' not in json.dumps(alice.user)
    assert env.client.post('/api/auth/register',json={'username':'ALICE','password':'Other-password'}).status_code==409
    assert env.client.post('/api/auth/login',json={'username':'alice','password':'Wrong-password'}).status_code==401
    assert env.client.post('/api/surveys',json={'title':'x'},headers={'Cookie':alice.headers['Cookie']}).status_code==403
    assert env.client.post('/api/auth/login',json={'username':'alice','password':'Test-password-123'},headers={'Origin':'https://evil.example'}).status_code==403
    assert alice.call('GET','/auth/me')['user']['username']=='alice'
    alice.call('POST','/auth/logout')
    alice.call('GET','/auth/me',status=401)


def test_T02_owner_isolation_and_T06_sharing(env,actor):
    alice,bob=actor(),actor('bob')
    s=published(alice)
    assert bob.call('GET','/surveys')['total']==0
    for suffix in ['', '/stats','/stats/q1','/stats/q1/answers']:
        bob.call('GET','/surveys/'+s['id']+suffix,status=404)
    bob.call('POST',f"/surveys/{s['id']}/close",{'revision':s['revision']},404)
    assert bob.call('GET','/public/'+s['shareSlug'])['id']==s['id']
    env.client.cookies.clear();assert env.client.get('/api/public/'+s['shareSlug']).status_code==401
    assert env.client.get('/survey/'+s['shareSlug']).status_code==200
    bob.call('GET','/public/invalid',status=404)
    bob.call('GET','/surveys/not-an-objectid',status=404)


def test_T03_T04_editor_ids_revision_freeze(env,actor):
    owner=actor();data=definition([]).model_dump(mode='json')
    s=owner.call('POST','/surveys',data,201)
    owner.call('POST',f"/surveys/{s['id']}/publish",{'revision':0},422)
    data.update(questions=[question('stable','TEXT')],revision=s['revision'])
    changed=owner.call('PUT','/surveys/'+s['id'],data)
    assert changed['questions'][0]['questionId']=='stable'
    owner.call('PUT','/surveys/'+s['id'],data,409)
    s=owner.call('POST',f"/surveys/{s['id']}/publish",{'revision':changed['revision']})
    data['revision']=s['revision'];owner.call('PUT','/surveys/'+s['id'],data,409)
    assert owner.call('GET','/surveys')['total']==1
    draft=owner.call('POST','/surveys',definition([]).model_dump(mode='json'),201)
    owner.call('GET','/public/'+draft['shareSlug'],status=404)
    invalid=definition().model_dump(mode='json');invalid['title']='  '
    owner.call('POST','/surveys',invalid,422)


def test_T05_deadline_close_and_closed_receipt(env,actor):
    owner=actor();s=published(owner,[question(typ='TEXT')])
    a=answer(owner,attempt(owner,s),'q1','saved')
    closed=owner.call('PATCH',f"/surveys/{s['id']}/deadline",{'revision':s['revision'],'closesAt':(utcnow()+timedelta(hours=1)).isoformat()})
    owner.call('PATCH',f"/surveys/{s['id']}/deadline",{'revision':closed['revision'],'closesAt':'2020-01-01T00:00:00Z'},422)
    owner.call('PATCH',f"/surveys/{s['id']}/deadline",{'revision':closed['revision'],'closesAt':'2030-01-01T00:00:00'},422)
    final=submit(owner,a)
    closed=owner.call('POST',f"/surveys/{s['id']}/close",{'revision':closed['revision']})
    assert closed['status']=='CLOSED'
    assert submit(owner,a)['id']==final['id']
    owner.call('PATCH',f"/surveys/{s['id']}/deadline",{'revision':closed['revision'],'closesAt':None},409)
    attempt_data={'attemptKey':uuid4().hex,'participationMode':'IDENTIFIED'}
    owner.call('POST',f"/public/{s['shareSlug']}/attempts",attempt_data,409)


def test_expired_draft_cannot_save_or_submit(env,actor):
    owner=actor();s=published(owner,[question(typ='TEXT')])
    a=answer(owner,attempt(owner,s),'q1','saved')
    env.store.db.surveys.update_one({'_id':ObjectId(s['id'])},{'$set':{'closesAt':utcnow()-timedelta(seconds=1)}})
    assert owner.call('GET','/public/'+s['shareSlug'])['effectiveStatus']=='EXPIRED'
    answer(owner,a,'q1','late',409);submit(owner,a,409)
    assert owner.call('GET',f"/attempts/{a['id']}")['answers'][0]['value']=='saved'


def test_T07_T11_value_validation_is_server_side(env,actor):
    owner=actor();s=published(owner,[question('single',required=True),question('multi','MULTI',1,True,{'minSelections':2,'maxSelections':2}),
        question('text','TEXT',2,True,{'minLength':2,'maxLength':4}),question('number','NUMBER',3,True,{'minValue':'0','maxValue':'120','integerOnly':True})])
    a=attempt(owner,s)
    for invalid in [None,[],['a'],True,'unknown']:answer(owner,a,'single',invalid,422)
    a=answer(owner,a,'single','a')
    for invalid in [['a'],['a','a'],['a','b','c'],['a','foreign']]:answer(owner,a,'multi',invalid,422)
    a=answer(owner,a,'multi',['b','a'])
    for invalid in ['a','abcde','   ',True]:answer(owner,a,'text',invalid,422)
    a=answer(owner,a,'text',' 中🙂 ')
    for invalid in [True,'-1','121','1.5','NaN',0]:answer(owner,a,'number',invalid,422)
    a=answer(owner,a,'number','0');final=submit(owner,a)
    doc=env.store.db.responses.find_one({'_id':ObjectId(final['id'])})
    assert doc['answers'][-1]['numberValue']==Decimal128('0')


def test_T12_T17_route_priority_recompute_skip_and_hidden_rejection(env,actor):
    owner=actor();qs=[question('q1',rules=[rule('eq','a','q4')]),question('q2','MULTI',1,True,rules=[rule('contains_all',['a','b'],'q4',0),rule('contains_any',['a'],'q3',1)]),
        question('q3','NUMBER',2,True,{'integerOnly':True},[rule('gte','18','q4')]),question('q4','TEXT',3)]
    s=published(owner,qs)
    a=attempt(owner,s);answer(owner,a,'q3','20',422);submit(owner,a,422)
    a=answer(owner,a,'q1','b');a=answer(owner,a,'q2',['a']);a=answer(owner,a,'q3','18');a=answer(owner,a,'q4','last')
    changed=answer(owner,a,'q1','a')
    assert changed['removedQuestionIds']==['q2','q3']
    assert changed['visitedQuestionIds']==['q1','q4'] and changed['readyToSubmit']
    answer(owner,changed,'q2',['a'],422)
    final=submit(owner,changed)
    assert [a['questionId'] for a in final['answers']]==['q1','q4']
    stats=owner.call('GET',f"/surveys/{s['id']}/stats")
    assert stats['questions'][1]['answerCount']==0 and stats['questions'][2]['mean'] is None


def test_T18_anonymous_hidden_and_repeat_mode_enforced(env,actor):
    owner,other=actor(),actor('other')
    s=published(owner,[question(typ='TEXT')],anonymousEnabled=True)
    a=answer(other,attempt(other,s,'ANONYMOUS'),'q1','hello');submit(other,a)
    stored=env.store.db.responses.find_one()
    assert 'identifiedUserId' not in stored and 'respondentKey' in stored
    raw=json.dumps(owner.call('GET',f"/surveys/{s['id']}/stats/q1/answers"))
    assert 'respondentKey' not in raw and 'identifiedUserId' not in raw and other.user['id'] not in raw
    owner.call('GET',f"/attempts/{a['id']}",status=404)
    other.call('POST',f"/public/{s['shareSlug']}/attempts",{'attemptKey':uuid4().hex,'participationMode':'IDENTIFIED'},409)
    s2=published(owner,[question(typ='TEXT')])
    other.call('POST',f"/public/{s2['shareSlug']}/attempts",{'attemptKey':uuid4().hex,'participationMode':'ANONYMOUS'},422)


def test_T19_T20_T21_restore_optimistic_lock_and_idempotency(env,actor):
    owner=actor();s=published(owner,[question(typ='TEXT')],anonymousEnabled=True)
    key=uuid4().hex;a=attempt(owner,s,key=key)
    assert attempt(owner,s,key=key)['id']==a['id']
    owner.call('POST',f"/public/{s['shareSlug']}/attempts",{'attemptKey':key,'participationMode':'ANONYMOUS'},409)
    saved=answer(owner,a,'q1','saved')
    answer(owner,a,'q1','old tab',409)
    loaded=owner.call('GET',f"/attempts/{a['id']}");assert loaded['answers'][0]['value']=='saved'
    owner.call('POST',f"/attempts/{a['id']}/submit",{'revision':saved['revision'],'answers':[]},422)
    final=submit(owner,saved);assert submit(owner,saved)['id']==final['id']
    answer(owner,final,'q1','overwrite',409)
    assert env.store.db.responses.count_documents({'status':'SUBMITTED'})==1
    assert owner.call('GET',f"/public/{s['shareSlug']}/my-attempts")['items'][0]['id']==a['id']


def test_T24_T26_statistics_known_values_and_pagination(env,actor):
    owner,u1,u2=actor(),actor('userone'),actor('usertwo')
    qs=[question('single'),question('multi','MULTI',1),question('numeric','NUMBER',2),question('text','TEXT',3)]
    s=published(owner,qs,allowMultipleSubmissions=True,anonymousEnabled=True)
    empty=owner.call('GET',f"/surveys/{s['id']}/stats")
    assert empty['responseCount']==0 and empty['questions'][2]['mean'] is None
    for person,sc,mc,n in [(u1,'a',['a','b'],'10'),(u1,'a',['a'],'20'),(u2,'b',['b'],None)]:
        a=attempt(person,s,'ANONYMOUS')
        for qid,value in [('single',sc),('multi',mc),('numeric',n),('text','输入<script>alert(1)</script>')]:a=answer(person,a,qid,value)
        submit(person,a)
    draft=attempt(u2,s);answer(u2,draft,'single','d')
    stats=owner.call('GET',f"/surveys/{s['id']}/stats")
    assert stats['responseCount']==3 and stats['respondentCount']==2
    single,multi,numeric,_=stats['questions']
    assert [(x['count'],x['respondentCount']) for x in single['options']]==[(2,1),(1,1),(0,0),(0,0)]
    assert [x['count'] for x in multi['options']]==[2,2,0,0]
    assert Decimal(numeric['mean'])==15 and numeric['answerCount']==2
    one=owner.call('GET',f"/surveys/{s['id']}/stats/numeric");assert one['mean']==numeric['mean']
    rows=owner.call('GET',f"/surveys/{s['id']}/stats/text/answers?limit=2&skip=0")
    assert rows['total']==3 and len(rows['items'])==2
    assert len(owner.call('GET',f"/surveys/{s['id']}/stats/text/answers?limit=2&skip=2")['items'])==1
    assert 'respondentKey' not in json.dumps(rows)


def test_T22_fifty_people_concurrent_real_mongo(env,actor):
    owner=actor();s=published(owner,[question(typ='TEXT',required=True)])
    survey=env.store.surveys.get({'_id':ObjectId(s['id'])})
    template=env.store.db.users.find_one();people=[]
    for i in range(50):
        user={**template,'_id':ObjectId(),'username':f'parallel{i}','usernameNormalized':f'parallel{i}'}
        env.store.users.insert(user);people.append(user)
    barrier=Barrier(50)
    def worker(pair):
        i,user=pair;barrier.wait(timeout=20)
        a=env.s.attempts.create(user,s['shareSlug'],AttemptCreate(attemptKey=uuid4().hex))
        a=env.s.attempts.answer(user,a['id'],AnswerWrite(revision=a['revision'],questionId='q1',value=f'answer-{i}'))
        return env.s.attempts.submit(user,a['id'],a['revision'])
    with ThreadPoolExecutor(max_workers=50) as pool:results=list(pool.map(worker,enumerate(people)))
    assert len({r['id'] for r in results})==50
    assert {r['answers'][0]['value'] for r in results}=={f'answer-{i}' for i in range(50)}
    assert env.store.db.responses.count_documents({'surveyId':survey['_id'],'status':'SUBMITTED'})==50
    stats=env.s.stats.all(template,s['id']);assert stats['responseCount']==stats['respondentCount']==50


def test_T23_single_person_two_concurrent_sessions(env,actor,monkeypatch):
    owner=actor();s=published(owner,[question(typ='TEXT')]);user=env.store.db.users.find_one()
    a,b=[answer(owner,attempt(owner,s),'q1','value') for _ in range(2)]
    original=env.store.responses.change;barrier=Barrier(2)
    def synchronized(query,changes):
        if changes.get('status')=='SUBMITTED':barrier.wait(timeout=10)
        return original(query,changes)
    monkeypatch.setattr(env.store.responses,'change',synchronized)
    def submit_one(doc):
        try:return env.s.attempts.submit(user,doc['id'],doc['revision'])['status']
        except AppError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(submit_one,[a,b]))
    assert sorted(result)==['SUBMITTED','already_submitted']
    assert env.store.db.responses.count_documents({'status':'SUBMITTED'})==1


def test_T27_D09B_admitted_before_close_can_commit_after_close(env,actor,monkeypatch):
    owner,bob=actor(),actor('bob');s=published(owner,[question(typ='TEXT')]);user=env.store.db.users.find_one({'_id':ObjectId(owner.user['id'])})
    a=answer(owner,attempt(owner,s),'q1','admitted');late=answer(bob,attempt(bob,s),'q1','late')
    original=env.store.responses.change;closed=[]
    def close_between_admission_and_write(query,changes):
        if changes.get('status')=='SUBMITTED' and not closed:
            closed.append(env.s.surveys.close(user,s['id'],s['revision']))
        return original(query,changes)
    monkeypatch.setattr(env.store.responses,'change',close_between_admission_and_write)
    final=submit(owner,a)
    assert closed[0]['status']=='CLOSED' and final['status']=='SUBMITTED' and 'admittedAt' in final
    assert submit(bob,late,409)['error']['code']=='survey_unavailable'
    assert env.store.db.responses.count_documents({'status':'SUBMITTED'})==1


def test_T28_schema_reinitialization_preserves_stage1_baseline(env,actor):
    owner=actor();s=published(owner,[question(typ='NUMBER')]);a=answer(owner,attempt(owner,s),'q1','0.1');final=submit(owner,a)
    before=owner.call('GET',f"/surveys/{s['id']}/stats")
    ensure_schema(env.store.db)
    assert owner.call('GET',f"/surveys/{s['id']}/stats")==before
    assert owner.call('GET',f"/attempts/{a['id']}")['answers']==final['answers']
    assert set(env.store.db.list_collection_names())=={'users','surveys','responses','sessions'}


def test_T30_real_database_schema_indexes_expired_session(env,actor,monkeypatch):
    owner=actor();user=env.store.db.users.find_one()
    bad={**user,'_id':ObjectId(),'usernameNormalized':'bad','createdAt':'not a BSON Date'}
    with pytest.raises(WriteError) as caught:env.store.db.users.insert_one(bad)
    assert caught.value.code==121
    with pytest.raises(DuplicateKeyError):env.store.db.users.insert_one({**user,'_id':ObjectId()})
    assert env.store.db.responses.index_information()['single_submission']['unique']
    import app.auth_service as auth_module
    monkeypatch.setattr(auth_module,'utcnow',lambda:utcnow()+timedelta(days=2))
    assert env.store.db.sessions.count_documents({})==1
    owner.call('GET','/auth/me',status=401)


def test_health_openapi_request_limit_and_db_error(env,actor,monkeypatch):
    assert env.client.get('/api/health').json()['status']=='ok'
    assert env.client.get('/openapi.json').json()['info']['version']=='1.0.0'
    assert env.client.get('/static/app.js').status_code==200
    assert env.client.post('/api/auth/login',content='x'*(2*1024*1024+1)).status_code==413
    owner=actor()
    def unavailable(_):raise AutoReconnect('injected test outage')
    monkeypatch.setattr(env.s.auth,'authenticate',unavailable)
    result=owner.call('GET','/auth/me',status=503)
    assert result['error']['code']=='database_unavailable' and 'injected' not in str(result)


def test_closed_definition_supports_readonly_saved_answers(env,actor):
    owner=actor();s=published(owner,[question(typ='TEXT')]);a=answer(owner,attempt(owner,s),'q1','仍可查看')
    owner.call('POST',f"/surveys/{s['id']}/close",{'revision':s['revision']})
    public=owner.call('GET','/public/'+s['shareSlug'])
    assert public['effectiveStatus']=='CLOSED' and public['questions'][0]['questionId']=='q1'
    assert owner.call('GET',f"/attempts/{a['id']}")['answers'][0]['value']=='仍可查看'
    submit(owner,a,409)
