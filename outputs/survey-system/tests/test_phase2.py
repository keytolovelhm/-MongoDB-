"""Stage-two integration tests use the same real MongoDB fixture as stage one."""
from copy import deepcopy
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from bson import ObjectId, BSON
from pymongo.errors import WriteError
import pytest
from app.library_service import payload_of, content_hash, decimal_key
from app.library_models import VersionSave
from app.runtime_schema import ensure_runtime_schema, RUNTIME_SCHEMAS
from app.survey_service import version_check
from app.errors import AppError
from scripts.history_baseline import restore, verify, canonical, load_fixture
from .helpers import question, definition, rule
from .test_api import attempt, answer, submit, published

pytestmark = pytest.mark.integration


def library(actor, typ='NUMBER', title='年龄', **kwargs):
    q = question(typ=typ, constraints={'minValue': '0', 'maxValue': '120'} if typ == 'NUMBER' else {})
    q['title'] = title
    return actor.call('POST', '/library/questions', {'name': title, 'payload': payload_of(q), **kwargs}, 201)


def share(owner, v, target, active=True, revision=0):
    return owner.call('PUT', f"/library/versions/{v['id']}/shares", {'username': target.user['username'], 'active': active, 'revision': revision})


def imported(actor, version, survey=None, replace=None, **kwargs):
    survey = survey or actor.call('POST', '/surveys', definition([]).model_dump(mode='json'), 201)
    data = dict(versionId=version['id'], revision=survey['revision'], reusePolicyVersion=1, acknowledged=True, **kwargs)
    if replace: data['replaceQuestionId'] = replace
    return actor.call('POST', f"/surveys/{survey['id']}/questions/import", data)


def cross(actor, item, *versions):
    params = '&'.join('versionIds='+v['id'] for v in versions)
    return actor.call('GET', f"/library/questions/{item['id']}/stats?{params}")


def saved_version(actor, item, base, payload=None):
    draft = actor.call('PUT', f"/library/questions/{item['id']}/draft", {'revision': item['revision'],
         'baseVersionId': base['id'], 'payload': payload or base['payload'], 'summaryPolicy': base['summaryPolicy']})
    return actor.call('POST', f"/library/questions/{item['id']}/versions", {'revision': draft['revision'], 'operationKey': uuid4().hex}, 201)


@pytest.mark.parametrize('typ', ['SINGLE', 'MULTI', 'TEXT', 'NUMBER'])
def test_S2_01_create_import_two_instances_and_freeze(actor, env, typ):
    owner = actor(); item = library(owner, typ); version = item['version']
    s = imported(owner, version); s = imported(owner, version, s)
    assert s['schemaVersion'] == 2
    assert len({q['questionId'] for q in s['questions']}) == 2
    assert all(q['sourceRef']['questionVersionId'] == version['id'] for q in s['questions'])
    p = owner.call('POST', f"/surveys/{s['id']}/publish", {'revision': s['revision']})
    before = BSON.encode(env.store.db.surveys.find_one({'_id': ObjectId(s['id'])}))
    updated_payload = deepcopy(version['payload']); updated_payload['title'] += '新版'
    saved_version(owner, item['item'], version, updated_payload)
    assert BSON.encode(env.store.db.surveys.find_one({'_id': ObjectId(s['id'])})) == before
    assert all('sourceRef' not in q for q in owner.call('GET', '/public/'+p['shareSlug'])['questions'])


def test_S2_03_source_server_owned_and_snapshot_body_protected(actor):
    owner = actor(); item = library(owner); s = imported(owner, item['version'])
    dto = {k: s[k] for k in ('title', 'description', 'questions', 'closesAt', 'anonymousEnabled', 'allowMultipleSubmissions', 'revision')}
    owner.call('PUT', '/surveys/'+s['id'], dto, 422)
    dto['questions'][0].pop('sourceRef')
    dto['questions'][0]['title'] = '伪造正文'
    owner.call('PUT', '/surveys/'+s['id'], dto, 409)
    dto['questions'][0]['title'] = item['version']['payload']['title']
    updated = owner.call('PUT', '/surveys/'+s['id'], dto)
    assert updated['questions'][0]['sourceRef']['questionVersionId'] == item['version']['id']
    data = {'revision': updated['revision'], 'versionId': item['version']['id'], 'reusePolicyVersion': 1, 'acknowledged': False}
    owner.call('POST', '/surveys/'+s['id']+'/questions/import', data, 422)


def test_S2_04_05_versions_branch_restore_and_idempotency(actor, env):
    owner = actor(); first = library(owner); v1 = first['version']; root = first['item']
    bson_before = BSON.encode(env.store.db.question_versions.find_one({'_id': ObjectId(v1['id'])}))
    second = saved_version(owner, root, v1)
    branch = saved_version(owner, second['item'], v1)
    assert branch['version']['parentVersionId'] == v1['id']
    data = {'revision': branch['item']['revision'], 'versionId': v1['id'], 'operationKey': uuid4().hex}
    restored = owner.call('POST', '/library/questions/'+root['id']+'/restore', data, 201)
    assert restored['version']['parentVersionId'] == branch['version']['id']
    assert restored['version']['restoredFromVersionId'] == v1['id']
    assert owner.call('POST', '/library/questions/'+root['id']+'/restore', data, 201)['version'] == restored['version']
    owner.call('POST', '/library/questions/'+root['id']+'/restore', dict(data, revision=data['revision']+1), 409)
    assert BSON.encode(env.store.db.question_versions.find_one({'_id': ObjectId(v1['id'])})) == bson_before
    assert owner.call('GET', '/library/questions/'+root['id']+'/versions')['total'] == 4


def test_S2_06_07_share_fork_revoke_and_existing_draft(actor, env):
    a, b, c = actor(), actor('borrower'), actor('outsider')
    item = library(a); v = item['version']
    b.call('GET', '/library/versions/'+v['id'], status=404)
    grant = share(a, v, b)
    s = imported(b, v)
    b.call('GET', '/library/questions/'+item['item']['id'], status=404)
    b.call('PUT', f"/library/versions/{v['id']}/shares", {'username': 'outsider', 'active': True, 'revision': 0}, 404)
    fork = b.call('POST', '/library/versions/'+v['id']+'/fork', {'name': '另存年龄'}, 201)
    assert fork['version']['derivedFromVersionId'] == v['id'] and fork['item']['ownerId'] == b.user['id']
    share(a, v, b, False, grant['revision'])
    b.call('GET', '/library/versions/'+v['id'], status=404)
    b.call('POST', f"/surveys/{s['id']}/questions/import", {'versionId': v['id'], 'revision': s['revision'], 'reusePolicyVersion': 1, 'acknowledged': True}, 404)
    p = b.call('POST', f"/surveys/{s['id']}/publish", {'revision': s['revision']})
    assert p['status'] == 'PUBLISHED'
    usages = a.call('GET', '/library/questions/'+item['item']['id']+'/usages')
    assert usages['total'] == 1
    text = str(usages)
    assert s['id'] not in text and s['shareSlug'] not in text and 'borrower' not in text
    a.call('GET', '/surveys/'+s['id'], status=404)
    c.call('GET', '/library/questions/'+item['item']['id']+'/usages', status=404)
    a.call('GET', '/library/questions/'+fork['item']['id']+'/stats?versionIds='+fork['version']['id'], status=404)


def test_S2_09_replace_keeps_rules_and_rejects_invalid_options(actor):
    owner = actor(); item = library(owner, 'SINGLE'); v1 = item['version']
    s = imported(owner, v1)
    qid = s['questions'][0]['questionId']
    dto = {k: s[k] for k in ('title', 'description', 'questions', 'closesAt', 'anonymousEnabled', 'allowMultipleSubmissions', 'revision')}
    dto['questions'][0].pop('sourceRef'); dto['questions'][0]['rules'] = [rule('eq', 'a')]
    s = owner.call('PUT', '/surveys/'+s['id'], dto)
    body = deepcopy(v1['payload']); body['options'] = body['options'][1:]
    v2 = saved_version(owner, item['item'], v1, body)['version']
    owner.call('POST', '/surveys/'+s['id']+'/questions/import', {'versionId': v2['id'], 'revision': s['revision'],
        'replaceQuestionId': qid, 'reusePolicyVersion': 1, 'acknowledged': True}, 422)
    assert owner.call('GET', '/surveys/'+s['id'])['questions'][0]['rules'] == s['questions'][0]['rules']


def test_S2_11_12_banks_pinned_upgrade_permission_and_remove(actor):
    a, b, c = actor(), actor('borrower'), actor('outsider')
    item = library(a); v1 = item['version']; grant = share(a, v1, b)
    bank = b.call('POST', '/banks', {'name': '学习题库'}, 201)
    member = b.call('POST', '/banks/'+bank['id']+'/items', {'versionId': v1['id']}, 201)
    b.call('POST', '/banks/'+bank['id']+'/items', {'versionId': v1['id']}, 409)
    c.call('GET', '/banks/'+bank['id']+'/items', status=404)
    v2 = saved_version(a, item['item'], v1)['version']; share(a, v2, b)
    member2 = b.call('PATCH', '/banks/'+bank['id']+'/items/'+member['id'], {'revision': member['revision'], 'versionId': v2['id']})
    assert member2['questionVersionId'] == v2['id']
    share(a, v2, b, False, 1)
    current = b.call('GET', '/banks/'+bank['id']+'/items')['items'][0]
    assert not current['available'] and current['payload'] is None
    b.call('DELETE', '/banks/'+bank['id']+'/items/'+member['id'], {'revision': member2['revision']})
    assert b.call('GET', '/banks/'+bank['id']+'/items')['total'] == 0


def test_S2_13_numeric_aggregate_author_auto_and_privacy(actor, env):
    a, b = actor(), actor('borrower'); item = library(a); v = item['version']; share(a, v, b)
    sa = imported(a, v); sa = a.call('POST', '/surveys/'+sa['id']+'/publish', {'revision': sa['revision']})
    # Allow two submissions from a single owner in a second survey rather than bypassing API policies.
    for value, name in [('10', 'own10'), ('20', 'own20')]:
        person = actor(name); x = answer(person, attempt(person, sa), sa['questions'][0]['questionId'], value); submit(person, x)
    sb = imported(b, v); sb = b.call('POST', '/surveys/'+sb['id']+'/publish', {'revision': sb['revision']})
    people = [actor('external'+str(i)) for i in range(5)]
    for i, person in enumerate(people):
        x = answer(person, attempt(person, sb, 'ANONYMOUS' if sb['anonymousEnabled'] else 'IDENTIFIED'), sb['questions'][0]['questionId'], '22')
        submit(person, x)
        result = cross(a, item['item'], v)['versions'][0]
        assert result['own']['answerCount'] == 2 and result['own']['mean'] == '15'
        if i < 4: assert result['foreign'] is None and result['combined'] is None
    result = cross(a, item['item'], v)
    summary = result['versions'][0]
    assert summary['foreignStatus'] == 'AVAILABLE' and summary['combined']['answerCount'] == 7
    assert summary['combined']['mean'] == '20'
    assert 'respondentKey' not in str(result) and 'identifiedUserId' not in str(result)
    assert not result['privacyKConfirmed']
    own_b = cross(b, item['item'], v)
    assert own_b['scope'] == 'OWN' and own_b['versions'][0]['own']['answerCount'] == 5


@pytest.mark.parametrize('access', ['no_grant', 'use_without_adoption', 'other_version_adopted'])
def test_S2_stats_rejects_non_author_without_requested_adoption(actor, access):
    owner, visitor = actor(), actor('stats_visitor')
    first = library(owner, title='仅作者统计的年龄题')
    v1 = first['version']
    v2 = saved_version(owner, first['item'], v1)['version']
    survey = imported(owner, v2)
    survey = owner.call('POST', '/surveys/'+survey['id']+'/publish', {'revision': survey['revision']})
    submit(owner, answer(owner, attempt(owner, survey), survey['questions'][0]['questionId'], '37'))
    before = cross(owner, first['item'], v2)
    assert before['versions'][0]['own']['answerCount'] == 1
    assert before['versions'][0]['own']['mean'] == '37'

    if access != 'no_grant':
        share(owner, v2, visitor)
        # Content USE alone must not grant statistics, even when this version exists and has data.
        assert visitor.call('GET', '/library/versions/'+v2['id'])['id'] == v2['id']
    if access == 'other_version_adopted':
        share(owner, v1, visitor)
        own = imported(visitor, v1)
        own = visitor.call('POST', '/surveys/'+own['id']+'/publish', {'revision': own['revision']})
        submit(visitor, answer(visitor, attempt(visitor, own), own['questions'][0]['questionId'], '11'))
        permitted = cross(visitor, first['item'], v1)
        assert permitted['scope'] == 'OWN' and permitted['versions'][0]['own']['mean'] == '11'

    path = '/library/questions/'+first['item']['id']+'/stats?versionIds='+v2['id']
    requests = [path]
    if access == 'other_version_adopted':
        # An allowed version first must not produce a partial result for a mixed-permission batch.
        requests.append('/library/questions/'+first['item']['id']+'/stats?versionIds='+v1['id']+'&versionIds='+v2['id'])
    for request in requests:
        denied = visitor.call('GET', request, status=404)
        assert set(denied) == {'error'}
        assert set(denied['error']) == {'code', 'message', 'field'}
        assert denied['error']['code'] == 'not_found' and denied['error']['field'] is None
        if access != 'no_grant':
            assert denied['error']['message'] == '无该版本的自有采用实例'
        text = str(denied)
        for private in (first['item']['id'], v1['id'], v2['id'], survey['id'], '仅作者统计的年龄题',
                        '37', 'answerCount', 'mean', 'distribution', 'respondentKey'):
            assert private not in text
    assert cross(owner, first['item'], v2) == before


def test_S2_18_runtime_upgrade_preserves_original_BSON_and_stats(env):
    name = 'survey_history_phase2_'+uuid4().hex
    db = env.store.client[name]
    try:
        before = restore(db)
        fixture = load_fixture()
        ensure_runtime_schema(db); ensure_runtime_schema(db)
        for collection, expected in fixture.items():
            assert canonical(list(db[collection].find().sort('_id', 1))) == canonical(sorted(expected, key=lambda x:x['_id']))
        assert set(db.list_collection_names()) == set(RUNTIME_SCHEMAS)
        from scripts.verify_phase2_history import verify_compatible
        assert verify_compatible(db)['stats'] == before['stats']
        with pytest.raises(ValueError, match='四个'): verify(db)
        for version in (0, 3, 99):
            s = dict(fixture['surveys'][0], schemaVersion=version)
            with pytest.raises(AppError): version_check(s)
        assert before['stats']['questions'][2]['mean'] == '15'
    finally:
        env.store.client.drop_database(name)


def test_S2_19_27_legacy_bind_pause_correct_preserves_BSON(actor, env):
    a, b = actor(), actor('borrower')
    q = question(typ='NUMBER', constraints={'minValue': '18.0', 'maxValue': '120'})
    survey = published(b, [q])
    first = b.call('POST', '/surveys/'+survey['id']+'/questions/q1/save-to-library', {'name': '旧年龄'}, 201)
    v = first['version']
    before = BSON.encode(env.store.db.surveys.find_one({'_id': ObjectId(survey['id'])}))
    link = {'versionId': v['id'], 'operationKey': uuid4().hex, 'expectedLinkRevision': 0, 'reusePolicyVersion': 1, 'acknowledged': True}
    path = '/surveys/'+survey['id']+'/questions/q1/library-link'
    a.call('PUT', path, link, 404)
    first_link = b.call('PUT', path, link)
    assert b.call('PUT', path, link) == first_link
    summary = cross(b, first['item'], v)['versions'][0]
    assert summary['own']['answerCount'] == 0
    pause = dict(link, operationKey=uuid4().hex, operation='SUSPEND', reason='核对来源', expectedLinkRevision=1)
    paused = b.call('POST', path+'/corrections', pause)
    assert paused['head']['revision'] == 2
    b.call('PUT', path, link, 409)
    resume = dict(link, operationKey=uuid4().hex, operation='RESUME', reason='核对一致', expectedLinkRevision=2)
    b.call('POST', path+'/corrections', resume)
    assert b.call('GET', path+'/history')['total'] == 3
    assert BSON.encode(env.store.db.surveys.find_one({'_id': ObjectId(survey['id'])})) == before
    assert content_hash(dict(q, constraints=dict(q['constraints'], minValue='18'))) == content_hash(q)
    assert decimal_key('1234567890123456789012345678901234') != decimal_key('1234567890123456789012345678901235')


def test_S2_schema_rejects_unknown_fields_and_unique_indexes(actor, env):
    a = actor(); item = library(a)
    v = env.store.db.question_versions.find_one()
    with pytest.raises(WriteError): env.store.db.question_versions.insert_one(dict(v, _id=ObjectId(), unexpected=True))
    assert env.store.db.question_versions.index_information()['version_number']['unique']
    assert env.store.db.legacy_question_links.index_information()['legacy_head']['unique']


def test_S2_23_expired_policy_filters_and_empty_foreign_cohort(actor):
    a, b = actor(), actor('borrower'); item = library(a); v = item['version']; share(a, v, b)
    s = imported(b, v)
    base = {'versionId': v['id'], 'revision': s['revision'], 'reusePolicyVersion': 2, 'acknowledged': True}
    b.call('POST', '/surveys/'+s['id']+'/questions/import', base, 409)
    a.call('GET', '/library/questions/'+item['item']['id']+'/stats?versionIds='+v['id']+'&surveyId='+s['id'], status=422)
    result = cross(a, item['item'], v)['versions'][0]
    assert result['foreignStatus'] == 'INSUFFICIENT_SAMPLE' and result['combined'] is None


@pytest.mark.parametrize('typ,values,status', [
    ('NUMBER', ['22']*4, 'INSUFFICIENT_SAMPLE'), ('NUMBER', ['22']*4+['70'], 'PRIVACY_SUPPRESSED'),
    ('NUMBER', ['24']*5, 'AVAILABLE'), ('NUMBER', ['120']*5, 'AVAILABLE'),
    ('SINGLE', ['a']*5, 'AVAILABLE'), ('SINGLE', ['a']*4+['b'], 'PRIVACY_SUPPRESSED'),
    ('MULTI', [['a','b']]*5, 'AVAILABLE'), ('MULTI', [['a','b']]*4+[['a','c']], 'PRIVACY_SUPPRESSED'),
    ('TEXT', ['private text '+str(i) for i in range(5)], 'AVAILABLE')])
def test_S2_24_25_26_privacy_cells_and_text(actor, typ, values, status):
    a, b = actor(), actor('borrower'); item = library(a, typ); v = item['version']; share(a, v, b)
    s = imported(b, v); s = b.call('POST', '/surveys/'+s['id']+'/publish', {'revision': s['revision']})
    for i,value in enumerate(values):
        person = actor('sample'+str(i)); attempt_data = answer(person, attempt(person, s), s['questions'][0]['questionId'], value); submit(person, attempt_data)
    result = cross(a, item['item'], v)['versions'][0]
    assert result['foreignStatus'] == status
    if status == 'AVAILABLE':
        assert result['foreign']['answerCount'] == 5
        if typ == 'MULTI': assert sum(d['count'] for d in result['foreign']['distribution']) == 10
        if typ == 'NUMBER':
            position = 1 if values[0] == '24' else 4
            assert result['foreign']['distribution'][position]['count'] == 5
        if typ == 'TEXT': assert 'private text' not in str(result)
    else: assert result['foreign'] is result['combined'] is None


def test_S2_15_same_account_repeat_and_two_instances_do_not_inflate_threshold(actor):
    a,b = actor(),actor('borrower'); item=library(a);v=item['version'];share(a,v,b)
    s=b.call('POST','/surveys',definition([],allowMultipleSubmissions=True,anonymousEnabled=True).model_dump(mode='json'),201)
    s=imported(b,v,s);s=imported(b,v,s);s=b.call('POST','/surveys/'+s['id']+'/publish',{'revision':s['revision']})
    for i in range(5):
        x=attempt(b,s,'ANONYMOUS');
        for q in s['questions']:x=answer(b,x,q['questionId'],'22')
        final=submit(b,x);assert submit(b,x)['id']==final['id']
    own=cross(b,item['item'],v)['versions'][0]['own']
    assert own['answerCount']==10 and own['responseCount']==5
    result=cross(a,item['item'],v)['versions'][0]
    assert result['foreignStatus']=='INSUFFICIENT_SAMPLE' and result['foreign'] is None


def test_S2_14_16_17_versions_separate_and_empty_answers_excluded(actor):
    a=actor();item=library(a);v1=item['version'];v2=saved_version(a,item['item'],v1)['version']
    s=imported(a,v1);s=imported(a,v2,s);s=a.call('POST','/surveys/'+s['id']+'/publish',{'revision':s['revision']})
    x=attempt(a,s);x=answer(a,x,s['questions'][0]['questionId'],'10');x=answer(a,x,s['questions'][1]['questionId'],None);submit(a,x)
    # A saved but unsubmitted answer cannot enter the aggregate.
    person=actor('drafter');x=attempt(person,s);answer(person,x,s['questions'][0]['questionId'],'99')
    result=cross(a,item['item'],v1,v2,v1)
    assert len(result['versions'])==2
    assert result['versions'][0]['own']['mean']=='10' and result['versions'][0]['own']['answerCount']==1
    assert result['versions'][1]['own']['answerCount']==0


def test_S2_04_concurrent_same_operation_creates_one_version(actor,env):
    a=actor();first=library(a);root=first['item'];v=first['version']
    draft=a.call('PUT',f"/library/questions/{root['id']}/draft",{'revision':root['revision'],'baseVersionId':v['id'],'payload':v['payload'],'summaryPolicy':v['summaryPolicy']})
    data=VersionSave(revision=draft['revision'],operationKey=uuid4().hex)
    user=env.store.db.users.find_one({'_id':ObjectId(a.user['id'])})
    from threading import Barrier
    barrier=Barrier(8)
    def save(_):
        barrier.wait();return env.s.library.save(user,root['id'],data)['version']['id']
    with ThreadPoolExecutor(max_workers=8)as pool:results=list(pool.map(save,range(8)))
    assert len(set(results))==1
    assert env.store.db.question_versions.count_documents({'libraryQuestionId':ObjectId(root['id'])})==2


def test_S2_28_orphan_revision_retry_and_correct_root_counts(actor,env,monkeypatch):
    a=actor();s=published(a,[question(typ='NUMBER',constraints={'minValue':'0','maxValue':'120'})]);x=answer(a,attempt(a,s),'q1','22');submit(a,x)
    first=a.call('POST',f"/surveys/{s['id']}/questions/q1/save-to-library",{'name':'一'},201)
    path=f"/surveys/{s['id']}/questions/q1/library-link"
    body={'versionId':first['version']['id'],'expectedLinkRevision':0,'operationKey':uuid4().hex,'reusePolicyVersion':1,'acknowledged':True}
    from app.repositories import Repository
    original=Repository.change
    def interrupted(repo,query,changes):
        if repo.collection.name=='legacy_question_links': raise AppError('injected_failure','test-only interruption',503)
        return original(repo,query,changes)
    with monkeypatch.context() as context:
        context.setattr(Repository,'change',interrupted)
        a.call('PUT',path,body,503)
    assert cross(a,first['item'],first['version'])['versions'][0]['own']['answerCount']==0
    link=a.call('PUT',path,body)
    assert link['head']['revision']==1
    second=a.call('POST',f"/surveys/{s['id']}/questions/q1/save-to-library",{'name':'二'},201)
    correct=dict(body,versionId=second['version']['id'],operationKey=uuid4().hex,expectedLinkRevision=1,operation='CORRECT',reason='调整目录归属')
    a.call('POST',path+'/corrections',correct)
    assert cross(a,first['item'],first['version'])['versions'][0]['own']['answerCount']==0
    assert cross(a,second['item'],second['version'])['versions'][0]['own']['answerCount']==1
    a.call('PUT',path,body,409)


def test_S2_27_content_mismatch_and_legacy_option_ids(actor):
    a=actor();s=published(a,[question(typ='SINGLE')]);item=library(a,'SINGLE');v=item['version']
    data={'versionId':v['id'],'expectedLinkRevision':0,'operationKey':uuid4().hex,'reusePolicyVersion':1,'acknowledged':True}
    a.call('PUT',f"/surveys/{s['id']}/questions/q1/library-link",data,422)
    saved=a.call('POST',f"/surveys/{s['id']}/questions/q1/save-to-library",{'name':'旧单选'},201)
    a.call('PUT',f"/surveys/{s['id']}/questions/q1/library-link",dict(data,versionId=saved['version']['id'],operationKey=uuid4().hex))


def test_S2_21_index_explain(actor,env):
    a=actor();item=library(a);s=imported(a,item['version'])
    plans={}
    queries=[('question_versions',{'libraryQuestionId':ObjectId(item['item']['id'])},'version_number'),
             ('surveys',{'questions.sourceRef.questionVersionId':ObjectId(item['version']['id'])},'source_questionVersionId')]
    for collection,query,index in queries:
        from bson.codec_options import CodecOptions
        plan=env.store.db.command('explain',{'find':collection,'filter':query,'hint':index},
                                 codec_options=CodecOptions(unicode_decode_error_handler='replace'))
        assert 'IXSCAN' in str(plan['queryPlanner']['winningPlan'])
    # This checks index applicability, not a claim about load-test throughput or automatic plan choice.


def test_S2_demo_data_reproducible_scenarios_and_no_overwrite(env):
    from scripts.seed_phase2_demo import seed
    demo=seed(env.store,env.settings)
    assert demo['synthetic'] and len(demo['accounts'])==9
    assert demo['expected']['normal']['combined']['answerCount']==7
    assert demo['expected']['normal']['combined']['mean']=='20'
    assert demo['expected']['rare']['foreignStatus']=='PRIVACY_SUPPRESSED'
    assert demo['expected']['low']['foreignStatus']=='INSUFFICIENT_SAMPLE'
    assert env.store.db.responses.count_documents({'status':'SUBMITTED'})==12
    with pytest.raises(ValueError,match='覆盖'):seed(env.store,env.settings)


def test_S2_07_revoke_after_admission_keeps_snapshot(actor,env,monkeypatch):
    a,b=actor(),actor('borrower');item=library(a);v=item['version'];share(a,v,b)
    original=env.s.library.usable
    def admitted_then_revoked(user,version_id):
        version=original(user,version_id)
        env.store.db.access_grants.update_one({'questionVersionId':ObjectId(v['id'])},{'$set':{'active':False}})
        return version
    with monkeypatch.context()as context:
        context.setattr(env.s.library,'usable',admitted_then_revoked)
        s=imported(b,v)
    assert s['questions'][0]['sourceRef']['questionVersionId']==v['id']
    b.call('GET','/library/versions/'+v['id'],status=404)
    b.call('POST','/surveys/'+s['id']+'/publish',{'revision':s['revision']})


def test_S2_04_competing_versions_preserve_branch_and_one_head(actor,env,monkeypatch):
    from threading import Barrier
    a=actor();first=library(a);root,v=first['item'],first['version']
    draft=a.call('PUT',f"/library/questions/{root['id']}/draft",{'revision':root['revision'],'baseVersionId':v['id'],'payload':v['payload'],'summaryPolicy':v['summaryPolicy']})
    user=env.store.db.users.find_one({'_id':ObjectId(a.user['id'])});barrier=Barrier(2)
    # The collection object used by attribute lookup is recreated by PyMongo; patch its class only in this test.
    from pymongo.synchronous.collection import Collection
    raw_insert=Collection.insert_one
    def intercepted(collection,document,*args,**kwargs):
        result=raw_insert(collection,document,*args,**kwargs)
        if collection.name=='question_versions' and document['operation']=='EDIT':barrier.wait(timeout=10)
        return result
    with monkeypatch.context()as context:
        context.setattr(Collection,'insert_one',intercepted)
        with ThreadPoolExecutor(max_workers=2)as pool:
            results=list(pool.map(lambda _:env.s.library.save(user,root['id'],VersionSave(revision=draft['revision'],operationKey=uuid4().hex)),range(2)))
    assert len({r['version']['id'] for r in results})==2
    actual=env.store.db.question_items.find_one({'_id':ObjectId(root['id'])})
    assert str(actual['headVersionId']) in {r['version']['id'] for r in results}
    assert actual['revision']==draft['revision']+1
    assert env.store.db.question_versions.count_documents({'libraryQuestionId':ObjectId(root['id'])})==3


def test_S2_28_competing_legacy_corrections_never_double_count(actor,env,monkeypatch):
    from threading import Barrier
    from app.library_models import LinkWrite
    from pymongo.synchronous.collection import Collection
    a=actor();s=published(a,[question(typ='SINGLE')]);x=answer(a,attempt(a,s),'q1','a');submit(a,x)
    items=[a.call('POST',f"/surveys/{s['id']}/questions/q1/save-to-library",{'name':'根'+str(i)},201) for i in range(3)]
    initial=LinkWrite(versionId=items[0]['version']['id'],expectedLinkRevision=0,operationKey=uuid4().hex,reusePolicyVersion=1,acknowledged=True)
    user=env.store.db.users.find_one({'_id':ObjectId(a.user['id'])});env.s.legacy.bind(user,s['id'],'q1',initial)
    before=BSON.encode(env.store.db.surveys.find_one({'_id':ObjectId(s['id'])}))
    responses=[BSON.encode(d) for d in env.store.db.responses.find().sort('_id',1)]
    barrier=Barrier(2);raw_insert=Collection.insert_one
    def intercepted(collection,document,*args,**kwargs):
        result=raw_insert(collection,document,*args,**kwargs)
        if collection.name=='legacy_question_links' and document.get('operation')=='CORRECT':barrier.wait(timeout=10)
        return result
    def correct(item):
        try:
            env.s.legacy.bind(user,s['id'],'q1',LinkWrite(versionId=item['version']['id'],expectedLinkRevision=1,
                operationKey=uuid4().hex,operation='CORRECT',reason='并发纠错用例',reusePolicyVersion=1,acknowledged=True))
            return 'ok'
        except AppError as exc:return exc.status
    with monkeypatch.context()as context:
        context.setattr(Collection,'insert_one',intercepted)
        with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(correct,items[1:]))
    assert sorted(map(str,results))==['409','ok']
    counts=[cross(a,item['item'],item['version'])['versions'][0]['own']['answerCount'] for item in items]
    assert sum(counts)==1 and counts[0]==0
    assert BSON.encode(env.store.db.surveys.find_one({'_id':ObjectId(s['id'])}))==before
    assert [BSON.encode(d) for d in env.store.db.responses.find().sort('_id',1)]==responses


@pytest.mark.parametrize('cuts', [['24','24.0'], ['50','20'], ['NaN'], ['1e99999']])
def test_S2_26_invalid_fixed_cuts_rejected(actor,cuts):
    a=actor()
    data={'name':'边界题','payload':payload_of(question(typ='NUMBER')),'summaryPolicy':{'numericCuts':cuts}}
    a.call('POST','/library/questions',data,422)


def test_S2_archive_read_history_no_new_use_and_bank_metadata(actor):
    a=actor();item=library(a);v=item['version'];s=imported(a,v)
    archived=a.call('PATCH','/library/questions/'+item['item']['id'],{'revision':item['item']['revision'],'name':'年龄归档','status':'ARCHIVED'})
    assert a.call('GET','/library/versions/'+v['id'])['id']==v['id']
    a.call('POST','/surveys/'+s['id']+'/questions/import',{'revision':s['revision'],'versionId':v['id'],'reusePolicyVersion':1,'acknowledged':True},409)
    assert cross(a,archived,v)['versions'][0]['own']['answerCount']==0
    bank=a.call('POST','/banks',{'name':'我的题库'},201)
    a.call('PATCH','/banks/'+bank['id'],{'revision':0,'name':'归档题库','description':'说明','status':'ARCHIVED'})
    assert a.call('GET','/banks/'+bank['id'])['status']=='ARCHIVED'
    a.call('POST','/banks/'+bank['id']+'/items',{'versionId':v['id']},409)


def test_S2_demo_cli_after_empty_runtime_initialization(env,tmp_path):
    import subprocess,sys,os
    from pathlib import Path
    name='survey_demo_stage2_'+uuid4().hex
    db=env.store.client[name]
    try:
        ensure_runtime_schema(db)
        command=[sys.executable,'-B','scripts/seed_phase2_demo.py','--uri',env.settings.mongo_uri,
                 '--database',name,'--output',str(tmp_path/'demo.json')]
        process_env={**os.environ,'APP_SECRET':env.settings.secret,'PYTHONUTF8':'1'}
        result=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],env=process_env,capture_output=True,text=True,encoding='utf-8',timeout=45)
        assert result.returncode==0,result.stdout+result.stderr
        import json
        assert json.loads((tmp_path/'demo.json').read_text(encoding='utf-8'))['expected']['normal']['combined']['mean']=='20'
        retry=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],env=process_env,capture_output=True,text=True,encoding='utf-8',timeout=15)
        assert retry.returncode==2 and '拒绝覆盖' in retry.stderr
        assert db.responses.count_documents({'status':'SUBMITTED'})==12
    finally:
        env.store.client.drop_database(name)


def test_S2_parent_required_and_save_snapshot_tracks_fork(actor):
    a,b=actor(),actor('borrower');item=library(a);v=item['version'];grant=share(a,v,b)
    a.call('PUT',f"/library/questions/{item['item']['id']}/draft",{'revision':0,'baseVersionId':None,'payload':v['payload'],'summaryPolicy':v['summaryPolicy']},422)
    s=imported(b,v);qid=s['questions'][0]['questionId']
    fork=b.call('POST',f"/surveys/{s['id']}/questions/{qid}/save-to-library",{'name':'从自有快照另存'},201)
    assert fork['version']['operation']=='FORK' and fork['version']['derivedFromVersionId']==v['id']
    share(a,v,b,False,grant['revision'])
    b.call('POST',f"/surveys/{s['id']}/questions/{qid}/save-to-library",{'name':'不可绕过撤销'},404)
