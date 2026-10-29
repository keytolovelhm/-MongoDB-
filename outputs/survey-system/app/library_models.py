"""Request DTOs. Source references and acknowledgement timestamps are server-owned."""
from typing import Literal
from pydantic import Field
from .models import Model, Option, Constraints, Revision


class Payload(Model):
    title: str = Field(min_length=1, max_length=1000)
    type: Literal['SINGLE', 'MULTI', 'TEXT', 'NUMBER']
    required: bool = False
    options: list[Option] = Field(default_factory=list, max_length=100)
    constraints: Constraints = Field(default_factory=Constraints)


class SummaryPolicy(Model):
    policyVersion: Literal[1] = 1
    numericCuts: list[str] = Field(default_factory=list, max_length=19)


class ItemCreate(Model):
    name: str = Field(min_length=1, max_length=200)
    payload: Payload
    summaryPolicy: SummaryPolicy | None = None


class DraftWrite(Revision):
    baseVersionId: str | None = None
    payload: Payload
    summaryPolicy: SummaryPolicy | None = None


class VersionSave(Revision):
    operationKey: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')


class Restore(VersionSave):
    versionId: str


class ItemUpdate(Revision):
    name: str = Field(min_length=1, max_length=200)
    status: Literal['ACTIVE', 'ARCHIVED'] = 'ACTIVE'


class GrantWrite(Model):
    username: str = Field(min_length=3, max_length=40)
    active: bool
    revision: int = Field(ge=0)


class Acknowledged(Model):
    reusePolicyVersion: int = Field(ge=1)
    acknowledged: bool


class ImportVersion(Acknowledged, Revision):
    versionId: str
    replaceQuestionId: str | None = None


class ForkVersion(Model):
    name: str = Field(min_length=1, max_length=200)


class BankWrite(Model):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=2000)


class BankUpdate(BankWrite, Revision):
    status: Literal['ACTIVE', 'ARCHIVED'] = 'ACTIVE'


class MemberWrite(Model):
    versionId: str
    position: int = Field(default=0, ge=0, le=1000000)


class MemberUpdate(MemberWrite, Revision):
    pass


class LinkWrite(Acknowledged):
    versionId: str
    expectedLinkRevision: int = Field(ge=0)
    operationKey: str = Field(pattern=r'^[A-Za-z0-9_-]{8,80}$')
    operation: Literal['BIND', 'CORRECT', 'SUSPEND', 'RESUME'] = 'BIND'
    reason: str = Field(default='', max_length=1000)
