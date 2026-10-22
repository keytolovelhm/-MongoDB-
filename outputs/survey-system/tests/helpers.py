from uuid import uuid4
from app.models import Question, SurveyWrite


def question(qid='q1', typ='SINGLE', order=0, required=False, constraints=None, rules=None):
    return Question(questionId=qid, order=order, title=qid, type=typ, required=required,
        options=[{'optionId': x, 'label': x.upper()} for x in ['a', 'b', 'c', 'd']] if typ in ('SINGLE', 'MULTI') else [],
        constraints=constraints or {}, rules=rules or []).model_dump()


def rule(op, value, target='END', priority=0, rid=None):
    return {'ruleId': rid or uuid4().hex, 'priority': priority, 'condition': {'op': op, 'value': value}, 'target': target}


def definition(questions=None, **kwargs):
    return SurveyWrite(title='测试问卷', questions=questions if questions is not None else [question()], **kwargs)
