from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from app.domain import number, normalize_answer, validate_definition, walk, matches
from app.errors import AppError
from app.survey_service import effective_status, assert_open, version_check
from .helpers import question, definition, rule


@pytest.mark.parametrize('raw,expected', [('0','0'),('-1.25','-1.25'),('1e3','1000'),('13800138000','13800138000'),('.5','0.5')])
def test_decimal_exact(raw, expected): assert number(raw) == Decimal(expected)


@pytest.mark.parametrize('value',[True,False,1,1.5,'NaN','Infinity','1e99999','12345678901234567890123456789012345',{},'1,000','１２','-'])
def test_decimal_rejects_invalid_and_inexact(value):
    with pytest.raises(AppError): number(value)


@pytest.mark.parametrize('value,ok',[('-1',False),('0',True),('120',True),('121',False),('1.5',False),('1.0',True)])
def test_integer_range(value,ok):
    q=question(typ='NUMBER',required=True,constraints={'integerOnly':True,'minValue':'0','maxValue':'120'})
    if ok: assert normalize_answer(q,value)==Decimal(value)
    else:
        with pytest.raises(AppError): normalize_answer(q,value)


@pytest.mark.parametrize('value,ok', [(['a'],False),(['a','b'],True),(['a','b','c'],True),(['a','b','c','d'],False),(['a','a'],False),(['foreign','a'],False),(True,False)])
def test_multi_bounds_and_duplicates(value,ok):
    q=question(typ='MULTI',required=True,constraints={'minSelections':2,'maxSelections':3})
    if ok: assert normalize_answer(q,value)==value
    else:
        with pytest.raises(AppError): normalize_answer(q,value)


def test_exact_selection_and_optional_skip():
    q=question(typ='MULTI',constraints={'minSelections':2,'maxSelections':2})
    assert normalize_answer(q,[]) is None
    assert normalize_answer(q,['b','a'])==['a','b']
    with pytest.raises(AppError):normalize_answer(q,['a','b','c'])


@pytest.mark.parametrize('text,ok',[('a',False),('中文',True),('中文🙂',True),('abcd',True),('abcde',False),('  中文  ',True),('   ',False)])
def test_text_codepoints_and_whitespace(text,ok):
    q=question(typ='TEXT',required=True,constraints={'minLength':2,'maxLength':4})
    if ok:assert normalize_answer(q,text)==text.strip()
    else:
        with pytest.raises(AppError): normalize_answer(q,text)


@pytest.mark.parametrize('op,expected,value,result',[
    ('contains_any',['a','b'],['b'],True),('contains_all',['a','b'],['a'],False),
    ('contains_all',['a','b'],['b','a','c'],True),('set_equals',['a','b'],['b','a'],True),
    ('set_equals',['a','b'],['a','b','c'],False),('gte','18',Decimal('18'),True),
    ('gt','18',Decimal('18'),False),('lt','18',Decimal('17.9'),True),('lte','18',Decimal('18'),True),
    ('eq','0.1',Decimal('0.10'),True),('between',['0.1','0.3'],Decimal('0.3'),True),
    ('between',['0.1','0.3'],Decimal('0.31'),False)])
def test_rule_semantics(op,expected,value,result): assert matches({'op':op,'value':expected},value) is result


def test_priority_jump_and_clear_old_branch():
    qs=[question('q1',order=0,rules=[rule('eq','a','q3')]), question('q2','TEXT',order=1,required=True),question('q3','TEXT',order=2)]
    validate_definition(definition(qs).model_dump(),True)
    path,kept,pending=walk(qs,{'q1':'b','q2':'旧分支','q3':'仍可达'})
    assert path==['q1','q2','q3'] and pending is None
    path,kept,pending=walk(qs,{**kept,'q1':'a'})
    assert path==['q1','q3'] and kept=={'q1':'a','q3':'仍可达'} and pending is None


def test_multi_first_match_and_end():
    qs=[question('q1','MULTI',rules=[rule('contains_any',['a'],'q2',10),rule('contains_all',['a','b'],'END',1)]),question('q2','TEXT',order=1,required=True)]
    validate_definition(definition(qs).model_dump(),True)
    assert walk(qs,{'q1':['b','a']})==(['q1'],{'q1':['a','b']},None)
    assert walk(qs,{'q1':['a']})[2]=='q2'


@pytest.mark.parametrize('mutation',[
    lambda d:d['questions'].append(deepcopy(d['questions'][0])),
    lambda d:d['questions'][0].update(title='  '),
    lambda d:d['questions'][0].update(options=[]),
    lambda d:d['questions'][0]['options'].append(deepcopy(d['questions'][0]['options'][0])),
    lambda d:d['questions'][0]['constraints'].update(minLength=3),
    lambda d:d['questions'][0].update(rules=[rule('eq','a','missing')]),
    lambda d:d['questions'][0].update(rules=[rule('eq','a','q1')]),
    lambda d:d['questions'][1].update(rules=[rule('eq','a','q1')]),
    lambda d:d['questions'][0].update(rules=[rule('eq','a','q2'),rule('eq','b','END')]),
    lambda d:d['questions'][0].update(rules=[rule('eq','a','q2',1),rule('eq','a','END',2)]),
    lambda d:d['questions'][0].update(rules=[rule('contains_any',['a'],'END')]),
])
def test_bad_definitions_rejected(mutation):
    data=definition([question('q1'),question('q2',order=1)]).model_dump();mutation(data)
    with pytest.raises(AppError):validate_definition(data,True)


@pytest.mark.parametrize('typ,constraints', [('MULTI',{'minSelections':3,'maxSelections':2}),('MULTI',{'maxSelections':5}),
    ('TEXT',{'minLength':5,'maxLength':4}),('NUMBER',{'minValue':'10','maxValue':'1'}),
    ('NUMBER',{'minValue':'0.1','maxValue':'0.9','integerOnly':True})])
def test_impossible_constraints(typ,constraints):
    with pytest.raises(AppError):validate_definition(definition([question(typ=typ,constraints=constraints)]).model_dump(),True)


def test_missing_optional_is_a_pending_step_and_required_skip_is_legal():
    qs=[question('q1',rules=[rule('eq','a','q3')]),question('q2','TEXT',1,True),question('q3','TEXT',2)]
    assert walk(qs,{'q1':'a'})[2]=='q3'
    assert walk(qs,{'q1':'a','q3':None})[2] is None


def test_deadline_inclusive_and_version_guard():
    now=datetime(2026,10,17,tzinfo=timezone.utc)
    doc={'status':'PUBLISHED','closesAt':now,'schemaVersion':1,'contentVersion':1,'ruleLanguageVersion':1}
    assert effective_status(doc,now)=='EXPIRED'
    with pytest.raises(AppError):assert_open(doc,now)
    with pytest.raises(AppError):version_check(dict(doc,contentVersion=2))


@pytest.mark.parametrize('typ,value',[('SINGLE',[]),('TEXT',[]),('NUMBER',[]),('MULTI','')])
def test_optional_wrong_empty_type_is_not_a_skip(typ,value):
    with pytest.raises(AppError):normalize_answer(question(typ=typ,required=False),value)


@pytest.mark.parametrize('typ,constraints',[('MULTI',{'maxSelections':0}),('TEXT',{'maxLength':0})])
def test_required_question_cannot_have_zero_capacity(typ,constraints):
    with pytest.raises(AppError):validate_definition(definition([question(typ=typ,required=True,constraints=constraints)]).model_dump(),True)
