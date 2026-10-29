"""Stage-two HTTP endpoints; reuse the existing session, CSRF and error handling."""
from fastapi import Depends, Query, Request
from .library_models import (ItemCreate, ItemUpdate, DraftWrite, VersionSave, Restore, GrantWrite, ImportVersion,
                             ForkVersion, BankWrite, BankUpdate, MemberWrite, MemberUpdate, LinkWrite, SummaryPolicy)
from .models import Model, Revision
from .library_service import REUSE_NOTICE
from .errors import fail
from pydantic import Field


class SaveLocal(Model):
    name: str = Field(min_length=1, max_length=200)
    summaryPolicy: SummaryPolicy | None = None


def install_routes(app, current_user, write_user, service_dependency):
    from fastapi import APIRouter
    router = APIRouter(prefix='/api', tags=['question-library'])

    @router.get('/library/policy')
    def policy(user=Depends(current_user)):
        return {'reusePolicyVersion': 1, 'notice': REUSE_NOTICE, 'privacyK': 5, 'privacyKConfirmed': False}

    @router.get('/library/questions')
    def listing(skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
                user=Depends(current_user), s=Depends(service_dependency)):
        return s.library.listing(user, skip, limit)

    @router.post('/library/questions', status_code=201)
    def create(data: ItemCreate, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.create(user, data)

    @router.get('/library/shared-with-me')
    def received(skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
                 user=Depends(current_user), s=Depends(service_dependency)):
        return s.library.received(user, skip, limit)

    @router.get('/library/questions/{item_id}')
    def detail(item_id: str, user=Depends(current_user), s=Depends(service_dependency)):
        return s.library.detail(user, item_id)

    @router.patch('/library/questions/{item_id}')
    def item_update(item_id: str, data: ItemUpdate, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.update(user, item_id, data)

    @router.put('/library/questions/{item_id}/draft')
    def draft(item_id: str, data: DraftWrite, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.draft(user, item_id, data)

    @router.get('/library/questions/{item_id}/versions')
    def versions(item_id: str, skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
                 user=Depends(current_user), s=Depends(service_dependency)):
        return s.library.versions(user, item_id, skip, limit)

    @router.post('/library/questions/{item_id}/versions', status_code=201)
    def save(item_id: str, data: VersionSave, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.save(user, item_id, data)

    @router.post('/library/questions/{item_id}/restore', status_code=201)
    def restore(item_id: str, data: Restore, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.save(user, item_id, data, restore=True)

    @router.get('/library/versions/{version_id}')
    def version(version_id: str, user=Depends(current_user), s=Depends(service_dependency)):
        from .repositories import wire
        return wire(s.library.readable(user, version_id))

    @router.post('/library/versions/{version_id}/fork', status_code=201)
    def fork(version_id: str, data: ForkVersion, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.fork(user, version_id, data)

    @router.get('/library/versions/{version_id}/shares')
    def grants(version_id: str, user=Depends(current_user), s=Depends(service_dependency)):
        return s.library.grants(user, version_id)

    @router.put('/library/versions/{version_id}/shares')
    def grant(version_id: str, data: GrantWrite, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.grant(user, version_id, data)

    @router.get('/library/questions/{item_id}/usages')
    def usages(item_id: str, skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
               user=Depends(current_user), s=Depends(service_dependency)):
        return s.usage.listing(user, item_id, skip, limit)

    @router.get('/library/questions/{item_id}/stats')
    def stats(item_id: str, request: Request, versionIds: list[str] = Query(min_length=1, max_length=20),
              user=Depends(current_user), s=Depends(service_dependency)):
        if set(request.query_params) - {'versionIds'}:
            fail('fixed_stat_scope', '统计只允许选择确切版本，不接受问卷、日期或动态分组筛选', 422)
        return s.cross_stats.all(user, item_id, versionIds)

    @router.post('/surveys/{survey_id}/questions/import')
    def import_version(survey_id: str, data: ImportVersion, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.import_version(user, survey_id, data)

    @router.post('/surveys/{survey_id}/questions/{question_id}/replace-version')
    def replace(survey_id: str, question_id: str, data: ImportVersion, user=Depends(write_user), s=Depends(service_dependency)):
        if data.replaceQuestionId not in (None, question_id): fail('question_mismatch', '替换目标不一致', 422)
        return s.library.import_version(user, survey_id, data.model_copy(update={'replaceQuestionId': question_id}))

    @router.post('/surveys/{survey_id}/questions/{question_id}/save-to-library', status_code=201)
    def save_local(survey_id: str, question_id: str, data: SaveLocal, user=Depends(write_user), s=Depends(service_dependency)):
        return s.library.save_local(user, survey_id, question_id, data.name, data.summaryPolicy)

    @router.get('/banks')
    def banks(skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
              user=Depends(current_user), s=Depends(service_dependency)):
        return s.banks.listing(user, skip, limit)

    @router.post('/banks', status_code=201)
    def bank_create(data: BankWrite, user=Depends(write_user), s=Depends(service_dependency)):
        return s.banks.create(user, data)

    @router.get('/banks/{bank_id}')
    def bank_get(bank_id: str, user=Depends(current_user), s=Depends(service_dependency)):
        from .repositories import wire
        return wire(s.banks.owned(user, bank_id))

    @router.patch('/banks/{bank_id}')
    def bank_update(bank_id: str, data: BankUpdate, user=Depends(write_user), s=Depends(service_dependency)):
        return s.banks.update(user, bank_id, data)

    @router.get('/banks/{bank_id}/items')
    def members(bank_id: str, skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
                user=Depends(current_user), s=Depends(service_dependency)):
        return s.banks.members(user, bank_id, skip, limit)

    @router.post('/banks/{bank_id}/items', status_code=201)
    def member_add(bank_id: str, data: MemberWrite, user=Depends(write_user), s=Depends(service_dependency)):
        return s.banks.add(user, bank_id, data)

    @router.patch('/banks/{bank_id}/items/{member_id}')
    def member_update(bank_id: str, member_id: str, data: MemberUpdate, user=Depends(write_user), s=Depends(service_dependency)):
        return s.banks.change(user, bank_id, member_id, data)

    @router.delete('/banks/{bank_id}/items/{member_id}')
    def member_remove(bank_id: str, member_id: str, data: Revision, user=Depends(write_user), s=Depends(service_dependency)):
        return s.banks.remove(user, bank_id, member_id, data.revision)

    @router.get('/surveys/{survey_id}/questions/{question_id}/library-link')
    def link_get(survey_id: str, question_id: str, user=Depends(current_user), s=Depends(service_dependency)):
        return s.legacy.current(user, survey_id, question_id)

    @router.put('/surveys/{survey_id}/questions/{question_id}/library-link')
    def link_bind(survey_id: str, question_id: str, data: LinkWrite, user=Depends(write_user), s=Depends(service_dependency)):
        if data.operation != 'BIND': fail('correction_endpoint', '请使用纠错接口', 422)
        return s.legacy.bind(user, survey_id, question_id, data)

    @router.post('/surveys/{survey_id}/questions/{question_id}/library-link/corrections')
    def link_correct(survey_id: str, question_id: str, data: LinkWrite, user=Depends(write_user), s=Depends(service_dependency)):
        if data.operation == 'BIND': fail('correction_endpoint', '纠错接口不接受初次关联', 422)
        return s.legacy.bind(user, survey_id, question_id, data)

    @router.get('/surveys/{survey_id}/questions/{question_id}/library-link/history')
    def link_history(survey_id: str, question_id: str, skip: int = Query(0, ge=0, le=1000000), limit: int = Query(20, ge=1, le=100),
                     user=Depends(current_user), s=Depends(service_dependency)):
        return s.legacy.history(user, survey_id, question_id, skip, limit)

    app.include_router(router)
