from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


Id = str


class Credentials(Model):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class Option(Model):
    optionId: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    label: str = Field(min_length=1, max_length=500)


class Constraints(Model):
    minSelections: int | None = Field(default=None, ge=0, le=100)
    maxSelections: int | None = Field(default=None, ge=0, le=100)
    minLength: int | None = Field(default=None, ge=0, le=10000)
    maxLength: int | None = Field(default=None, ge=0, le=10000)
    minValue: str | None = Field(default=None, max_length=100)
    maxValue: str | None = Field(default=None, max_length=100)
    integerOnly: bool = False


class Condition(Model):
    op: Literal['eq', 'contains_any', 'contains_all', 'set_equals', 'gt', 'gte', 'lt', 'lte', 'between']
    value: str | list[str]


class Rule(Model):
    ruleId: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    priority: int = Field(ge=0, le=100000)
    condition: Condition
    target: str = Field(min_length=1, max_length=64)


class Question(Model):
    questionId: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    order: int = Field(ge=0, le=100000)
    title: str = Field(min_length=1, max_length=1000)
    type: Literal['SINGLE', 'MULTI', 'TEXT', 'NUMBER']
    required: bool = False
    options: list[Option] = Field(default_factory=list, max_length=100)
    constraints: Constraints = Field(default_factory=Constraints)
    rules: list[Rule] = Field(default_factory=list, max_length=50)


class Deadline(Model):
    closesAt: datetime | None = None

    @field_validator('closesAt', mode='before')
    @classmethod
    def parse_time(cls, value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError('截止时间需要ISO格式且包含时区')
        if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
            raise ValueError('截止时间必须包含时区')
        return value


class SurveyWrite(Deadline):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=5000)
    anonymousEnabled: bool = False
    allowMultipleSubmissions: bool = False
    questions: list[Question] = Field(default_factory=list, max_length=200)


class SurveyUpdate(SurveyWrite):
    revision: int = Field(ge=0)


class Revision(Model):
    revision: int = Field(ge=0)


class DeadlineUpdate(Deadline):
    revision: int = Field(ge=0)


class AttemptCreate(Model):
    attemptKey: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')
    participationMode: Literal['IDENTIFIED', 'ANONYMOUS'] = 'IDENTIFIED'


class AnswerWrite(Revision):
    questionId: str = Field(min_length=1, max_length=64)
    value: Any
