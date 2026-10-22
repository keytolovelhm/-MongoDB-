"""Pure definition, answer and forward-routing logic. No HTTP or database I/O."""
from decimal import Decimal, InvalidOperation
import re
from bson.decimal128 import Decimal128
from .errors import fail


def number(value, field='number') -> Decimal:
    # Accept canonical decimal strings only. Never pass JSON floats through binary rounding.
    if not isinstance(value, str) or len(value) > 100 or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value, flags=re.ASCII):
        fail('number_format', '数字必须是有限十进制数字字符串', field=field)
    try:
        result = Decimal(value)
        if not result.is_finite():
            raise ValueError()
        # The BSON constructor traps inexact input and decimal128 overflow.
        Decimal128(result)
        return result
    except (InvalidOperation, ValueError, ArithmeticError):
        fail('number_precision', '数字超过Decimal128支持的精度或范围', field=field)


def validate_definition(survey, publishing=False):
    if not survey['title'].strip():
        fail('title_empty', '问卷标题不能为空', field='title')
    questions = survey['questions']
    if publishing and not questions:
        fail('no_questions', '至少添加一道题才能发布', field='questions')
    ordered = sorted(questions, key=lambda q: q['order'])
    ids = [q['questionId'] for q in ordered]
    if len(ids) != len(set(ids)) or len({q['order'] for q in ordered}) != len(ordered):
        fail('duplicate_question', '题目ID和顺序不能重复', field='questions')
    positions = {q: i for i, q in enumerate(ids)}
    all_rules = set()
    for q in ordered:
        field = q['questionId']
        if field == 'END' or not q['title'].strip():
            fail('question_invalid', '题目ID不能为END，题干不能为空', field=field)
        opts = q['options']
        option_ids = {o['optionId'] for o in opts}
        if len(option_ids) != len(opts) or any(not o['label'].strip() for o in opts):
            fail('option_invalid', '选项ID不能重复，选项内容不能为空', field=field)
        if q['type'] in ('SINGLE', 'MULTI'):
            if not opts:
                fail('no_options', '选择题至少需要一个选项', field=field)
        elif opts:
            fail('unexpected_options', '填空题不能包含选项', field=field)
        c = q['constraints']
        meaningful = {k for k, v in c.items() if v is not None and not (k == 'integerOnly' and v is False)}
        allowed = {'MULTI': {'minSelections', 'maxSelections'}, 'TEXT': {'minLength', 'maxLength'},
                   'NUMBER': {'minValue', 'maxValue', 'integerOnly'}, 'SINGLE': set()}[q['type']]
        if meaningful - allowed:
            fail('constraint_type', '该题型使用了不适用的约束', field=field)
        for low, high in [('minSelections', 'maxSelections'), ('minLength', 'maxLength')]:
            if c.get(low) is not None and c.get(high) is not None and c[low] > c[high]:
                fail('constraint_range', '最小限制不能大于最大限制', field=field)
        if q['type'] == 'MULTI' and any(c.get(k) is not None and c[k] > len(opts) for k in ['minSelections', 'maxSelections']):
            fail('selection_range', '选择数量限制不能超过选项总数', field=field)
        if q['required'] and ((q['type'] == 'MULTI' and c.get('maxSelections') == 0)
                              or (q['type'] == 'TEXT' and c.get('maxLength') == 0)):
            fail('no_required_answer', '必答题的最大选择数或最大文本长度不能为0', field=field)
        if q['type'] == 'NUMBER':
            lo = number(c['minValue'], field) if c.get('minValue') is not None else None
            hi = number(c['maxValue'], field) if c.get('maxValue') is not None else None
            if lo is not None and hi is not None and lo > hi:
                fail('number_range', '最小值不能大于最大值', field=field)
            if c['integerOnly'] and lo is not None and hi is not None:
                from decimal import ROUND_CEILING, ROUND_FLOOR
                if lo.to_integral_value(rounding=ROUND_CEILING) > hi.to_integral_value(rounding=ROUND_FLOOR):
                    fail('no_integer', '该区间不包含任何整数', field=field)
        priorities, seen_conditions = set(), set()
        for rule in q['rules']:
            if rule['ruleId'] in all_rules or rule['priority'] in priorities:
                fail('duplicate_rule', '规则ID和同一题内的优先级不能重复', field=field)
            all_rules.add(rule['ruleId']); priorities.add(rule['priority'])
            target = rule['target']
            if target != 'END' and (target not in positions or positions[target] <= positions[field]):
                fail('jump_target', '跳转目标必须是后续题目或END', field=field)
            cond = rule['condition']; op, value = cond['op'], cond['value']
            if q['type'] == 'SINGLE':
                valid = op == 'eq' and isinstance(value, str) and value in option_ids
            elif q['type'] == 'MULTI':
                valid = op in ('contains_any', 'contains_all', 'set_equals') and isinstance(value, list) and bool(value) and len(value) == len(set(value)) and set(value) <= option_ids
            elif q['type'] == 'NUMBER':
                valid = op in ('eq', 'gt', 'gte', 'lt', 'lte', 'between')
                if valid and op == 'between':
                    valid = isinstance(value, list) and len(value) == 2
                    if valid:
                        valid = number(value[0], field) <= number(value[1], field)
                elif valid:
                    valid = isinstance(value, str)
                    if valid: number(value, field)
            else:
                valid = False
            if not valid:
                fail('condition_invalid', '跳转条件与题型或参数不匹配', field=field)
            if q['type'] == 'NUMBER':
                # Decimal equality/hash preserves exact numeric meaning without context rounding.
                signature = (op, tuple(number(v, field) for v in value) if isinstance(value, list) else number(value, field))
            else:
                signature = (op, tuple(sorted(value)) if isinstance(value, list) else value)
            if signature in seen_conditions:
                fail('duplicate_condition', '重复条件会使后续规则永不生效', field=field)
            seen_conditions.add(signature)
    return ordered


def normalize_answer(q, value):
    qid = q['questionId']; typ = q['type']; c = q['constraints']
    empty = (value is None or (typ in ('TEXT', 'NUMBER') and isinstance(value, str) and not value.strip())
             or (typ == 'MULTI' and isinstance(value, list) and not value))
    if empty:
        if q['required']:
            fail('required', '此题必须回答', field=qid)
        return None
    options = {o['optionId'] for o in q['options']}
    if typ == 'SINGLE':
        if not isinstance(value, str) or value not in options:
            fail('single_invalid', '请选择本题的一个有效选项', field=qid)
    elif typ == 'MULTI':
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            fail('multi_type', '多选答案必须是选项ID数组', field=qid)
        if len(value) != len(set(value)) or not set(value) <= options:
            fail('multi_invalid', '选项无效或重复', field=qid)
        if c.get('minSelections') is not None and len(value) < c['minSelections']:
            fail('multi_min', f"至少选择{c['minSelections']}项", field=qid)
        if c.get('maxSelections') is not None and len(value) > c['maxSelections']:
            fail('multi_max', f"最多选择{c['maxSelections']}项", field=qid)
        value = sorted(value)
    elif typ == 'TEXT':
        if not isinstance(value, str):
            fail('text_type', '文本答案必须是字符串', field=qid)
        value = value.strip()
        if len(value) > 10000:
            fail('text_size', '文本不能超过10000码点', field=qid)
        if c.get('minLength') is not None and len(value) < c['minLength']:
            fail('text_min', f"至少输入{c['minLength']}个字符", field=qid)
        if c.get('maxLength') is not None and len(value) > c['maxLength']:
            fail('text_max', f"最多输入{c['maxLength']}个字符", field=qid)
    else:
        value = number(value, qid)
        if c['integerOnly'] and value != value.to_integral_value():
            fail('integer_required', '必须输入整数', field=qid)
        if c.get('minValue') is not None and value < number(c['minValue'], qid):
            fail('number_min', f"不能小于{c['minValue']}", field=qid)
        if c.get('maxValue') is not None and value > number(c['maxValue'], qid):
            fail('number_max', f"不能大于{c['maxValue']}", field=qid)
    return value


def matches(condition, value):
    op, expected = condition['op'], condition['value']
    if value is None:
        return False
    if isinstance(value, Decimal):
        if op == 'between': return number(expected[0]) <= value <= number(expected[1])
        other = number(expected)
        return {'eq': value == other, 'gt': value > other, 'gte': value >= other,
                'lt': value < other, 'lte': value <= other}[op]
    if op == 'eq': return value == expected
    actual, wanted = set(value), set(expected)
    return {'contains_any': bool(actual & wanted), 'contains_all': wanted <= actual,
            'set_equals': actual == wanted}[op]


def next_id(questions, q, value):
    for rule in sorted(q['rules'], key=lambda r: r['priority']):
        if matches(rule['condition'], value): return rule['target']
    index = next(i for i, item in enumerate(questions) if item['questionId'] == q['questionId'])
    return questions[index + 1]['questionId'] if index + 1 < len(questions) else 'END'


def walk(questions, values):
    """Stop at the first unanswered question. An explicit optional skip is stored as None."""
    lookup = {q['questionId']: q for q in questions}
    path, kept = [], {}
    current = questions[0]['questionId'] if questions else 'END'
    while current != 'END':
        if current in path or current not in lookup:
            fail('definition_corrupt', '问卷路径定义无效', 409)
        path.append(current)
        if current not in values:
            return path, kept, current
        q = lookup[current]
        kept[current] = normalize_answer(q, str(values[current]) if isinstance(values[current], Decimal) else values[current])
        current = next_id(questions, q, kept[current])
    return path, kept, None


ANSWER_FIELDS = {'SINGLE': 'selectedOptionId', 'MULTI': 'selectedOptionIds', 'TEXT': 'textValue', 'NUMBER': 'numberValue'}


def pack_answers(questions, values):
    return [dict(questionId=q['questionId'], **({ANSWER_FIELDS[q['type']]: values[q['questionId']]} if values[q['questionId']] is not None else {}))
            for q in questions if q['questionId'] in values]


def unpack_answers(questions, answers):
    types = {q['questionId']: q['type'] for q in questions}
    return {a['questionId']: a.get(ANSWER_FIELDS[types[a['questionId']]]) for a in answers}
