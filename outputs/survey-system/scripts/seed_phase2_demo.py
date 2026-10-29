"""Create synthetic multi-account examples in an explicitly named, empty demo database."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from uuid import uuid4
from pymongo import MongoClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.repositories import Store
from app.auth_service import AuthService
from app.survey_service import SurveyService
from app.attempt_service import AttemptService
from app.library_service import LibraryService
from app.bank_service import BankService
from app.legacy_service import LegacyService
from app.usage_service import UsageService
from app.library_stats import LibraryStats
from app.runtime_schema import RUNTIME_SCHEMAS
from app.models import Credentials, SurveyWrite, AttemptCreate, AnswerWrite
from app.library_models import (ItemCreate, Payload, GrantWrite, ImportVersion, DraftWrite, VersionSave,
                                BankWrite, MemberWrite, LinkWrite, ForkVersion)

PASSWORD='Demo-only-12345'


def seed(store,settings):
    db=store.db
    if any(db[n].count_documents({},limit=1) for n in db.list_collection_names()):
        raise ValueError('拒绝覆盖：演示数据库必须没有任何业务文档')
    auth=AuthService(store,settings);surveys=SurveyService(store);attempts=AttemptService(store,settings)
    library=LibraryService(store);banks=BankService(store,library);legacy=LegacyService(store,library)
    usage=UsageService(store,library,settings);stats=LibraryStats(store,library,usage)
    people={}
    for name in ['demo_author','demo_borrower','demo_outsider',*[f'demo_fill{i:02}' for i in range(1,7)]]:
        auth.register(Credentials(username=name,password=PASSWORD))
        people[name]=db.users.find_one({'username':name})
    a,b=people['demo_author'],people['demo_borrower']
    def create(name,typ='NUMBER'):
        return library.create(a,ItemCreate(name=name,payload=Payload(title=name,type=typ,
            options=[{'optionId':o,'label':label} for o,label in [('a','选项A'),('b','选项B')]] if typ in ('SINGLE','MULTI') else [],
            constraints={'minValue':'0','maxValue':'120','integerOnly':True} if typ=='NUMBER' else {})))
    normal=create('演示：年龄（可展示汇总）');rare=create('演示：年龄（稀有分组抑制）');low=create('演示：年龄（4组抑制）')
    text=create('演示：学习反馈','TEXT');single=create('演示：是否学习编程','SINGLE');multi=create('演示：感兴趣的方向','MULTI')
    for item in [normal,rare,low,text,single,multi]:
        library.grant(a,item['version']['id'],GrantWrite(username='demo_borrower',active=True,revision=0))
    def survey(owner,title,items):
        s=surveys.create(owner,SurveyWrite(title=title,anonymousEnabled=True,allowMultipleSubmissions=True))
        for item in items:
            s=library.import_version(owner,s['id'],ImportVersion(revision=s['revision'],versionId=item['version']['id'],reusePolicyVersion=1,acknowledged=True))
        return surveys.publish(owner,s['id'],s['revision'])
    own=survey(a,'作者问卷：年龄基线',[normal])
    external=survey(b,'借用者问卷：五组合成回答',[normal,rare,text,single,multi])
    small=survey(b,'借用者问卷：四组合成回答',[low])
    def fill(user,s,values,mode='ANONYMOUS'):
        x=attempts.create(user,s['shareSlug'],AttemptCreate(attemptKey=uuid4().hex,participationMode=mode))
        for q,value in zip(s['questions'],values):
            x=attempts.answer(user,x['id'],AnswerWrite(revision=x['revision'],questionId=q['questionId'],value=value))
        return attempts.submit(user,x['id'],x['revision'])
    for i,value in enumerate(['10','20'],1):fill(people[f'demo_fill{i:02}'],own,[value])
    for i in range(1,6):
        fill(people[f'demo_fill{i:02}'],external,['22','22' if i<5 else '70',f'合成反馈{i}','a',['a','b']])
        if i<5:fill(people[f'demo_fill{i:02}'],small,['22'])
    first=normal['version'];root=normal['item']
    body=deepcopy(first['payload']);body['title']='演示：请填写年龄（新版表述）'
    draft=library.draft(a,root['id'],DraftWrite(revision=root['revision'],baseVersionId=first['id'],payload=Payload(**body)))
    second=library.save(a,root['id'],VersionSave(revision=draft['revision'],operationKey='demo-age-version-two'))
    fork=library.fork(b,first['id'],ForkVersion(name='借用者另存的年龄题'))
    bank=banks.create(a,BankWrite(name='演示题库',description='v1与v2固定共存；更新不会改动问卷'))
    for v in [first,second['version']]:banks.add(a,bank['id'],MemberWrite(versionId=v['id']))
    bank_b=banks.create(b,BankWrite(name='借用题库'))
    banks.add(b,bank_b['id'],MemberWrite(versionId=first['id']))
    # A separate schema=1 frozen survey demonstrates explicit associations without touching phase-one fixtures.
    old=surveys.create(b,SurveyWrite(title='合成旧格式问卷：关联与纠错',anonymousEnabled=True,questions=[
        {'questionId':'legacy_age','order':0,'title':'合成历史年龄','type':'NUMBER','constraints':{'minValue':'0','maxValue':'120'}}]))
    old=surveys.publish(b,old['id'],old['revision']);fill(people['demo_fill06'],old,['18'])
    old_item=library.save_local(b,old['id'],'legacy_age','合成旧题目录')
    legacy.bind(b,old['id'],'legacy_age',LinkWrite(versionId=old_item['version']['id'],expectedLinkRevision=0,
        operationKey='demo-legacy-explicit-bind',reusePolicyVersion=1,acknowledged=True))
    expected={name:stats.all(a,item['item']['id'],[item['version']['id']])['versions'][0]
              for name,item in [('normal',normal),('rare',rare),('low',low)]}
    assert expected['normal']['combined']['mean']=='20'
    assert expected['rare']['foreignStatus']=='PRIVACY_SUPPRESSED'
    assert expected['low']['foreignStatus']=='INSUFFICIENT_SAMPLE'
    return {'synthetic':True,'database':db.name,'password':PASSWORD,'accounts':list(people),
            'surveys':{n:{'id':s['id'],'title':s['title'],'path':'/survey/'+s['shareSlug']}
                       for n,s in [('own',own),('external',external),('small',small),('legacy',old)]},
            'normalItemId':root['id'],'normalV1':first['id'],'normalV2':second['version']['id'],
            'forkId':fork['item']['id'],'expected':expected,
            'notice':'全部账号、填写、复用告知和关联均为AI脚本合成，未记作人工验收。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri',default='mongodb://127.0.0.1:27030')
    parser.add_argument('--database',required=True)
    parser.add_argument('--output',default='.runtime/phase2-demo.json')
    args=parser.parse_args()
    if not re.fullmatch(r'survey_demo_stage2_[A-Za-z0-9_]{1,40}',args.database):
        parser.error('请使用全新的survey_demo_stage2_开头的专属演示库')
    with MongoClient(args.uri,serverSelectionTimeoutMS=3000)as client:
        db=client[args.database];existing=set(db.list_collection_names())
        if existing-set(RUNTIME_SCHEMAS) or any(db[n].count_documents({},limit=1) for n in existing):
            parser.error('拒绝覆盖已有数据，请指定另一个空演示库（允许已初始化但无业务文档）')
    base=Settings.from_env()  # Keep the same private local key for subsequent browser filling.
    store=Store(Settings(args.uri,args.database,base.secret,base.secure_cookie,base.session_hours))
    try:result=seed(store,Settings(args.uri,args.database,base.secret))
    finally:store.close()
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('合成数据已创建：',args.database,'；账号密码及预期结果见',output)


if __name__=='__main__':main()
