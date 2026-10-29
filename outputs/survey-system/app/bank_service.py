"""Personal banks with pinned versions. Membership is not an access grant."""
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from .errors import fail
from .repositories import oid, utcnow, wire, Repository


class BankService:
    def __init__(self, store, library):
        self.db, self.library = store.db, library

    def owned(self, user, bank_id):
        bank = self.db.question_banks.find_one({'_id': oid(bank_id), 'ownerId': user['_id']})
        if not bank: fail('not_found', '题库不存在或无权访问', 404)
        return bank

    def create(self, user, data):
        now = utcnow()
        bank = dict(_id=ObjectId(), ownerId=user['_id'], **data.model_dump(), status='ACTIVE', revision=0,
                    createdAt=now, updatedAt=now, schemaVersion=1)
        self.db.question_banks.insert_one(bank)
        return wire(bank)

    def listing(self, user, skip, limit):
        query = {'ownerId': user['_id']}
        return {'items': wire(list(self.db.question_banks.find(query).sort([('updatedAt', -1), ('_id', -1)]).skip(skip).limit(limit))),
                'total': self.db.question_banks.count_documents(query)}

    def update(self, user, bank_id, data):
        bank = self.owned(user, bank_id)
        changed = Repository(self.db.question_banks).change({'_id': bank['_id'], 'revision': data.revision},
                                  dict(data.model_dump(exclude={'revision'}), updatedAt=utcnow()))
        if not changed: fail('revision_conflict', '题库已修改，请刷新', 409)
        return wire(changed)

    def members(self, user, bank_id, skip, limit):
        bank = self.owned(user, bank_id)
        result = []
        query = {'bankId': bank['_id']}
        for member in self.db.question_bank_items.find(query).sort([('position', 1), ('_id', 1)]).skip(skip).limit(limit):
            v = self.library.version(member['questionVersionId'])
            root = self.library.root(member['libraryQuestionId'])
            permitted = root['status'] == 'ACTIVE' and (root['ownerId'] == user['_id'] or bool(
                self.db.access_grants.find_one({'questionVersionId': v['_id'], 'granteeId': user['_id'], 'active': True})))
            result.append(dict(wire(member), available=permitted, name=root['name'], versionNo=v['versionNo'],
                               payload=wire(v['payload']) if permitted else None))
        return {'items': result, 'total': self.db.question_bank_items.count_documents(query), 'bank': wire(bank)}

    def add(self, user, bank_id, data):
        bank = self.owned(user, bank_id)
        if bank['status'] != 'ACTIVE': fail('bank_archived', '题库已归档', 409)
        v = self.library.usable(user, data.versionId)
        now = utcnow()
        m = dict(_id=ObjectId(), bankId=bank['_id'], libraryQuestionId=v['libraryQuestionId'], questionVersionId=v['_id'],
                 position=data.position, revision=0, createdAt=now, updatedAt=now, schemaVersion=1)
        try: self.db.question_bank_items.insert_one(m)
        except DuplicateKeyError: fail('duplicate_member', '该版本已在题库中', 409)
        return wire(m)

    def change(self, user, bank_id, member_id, data):
        bank = self.owned(user, bank_id)
        if bank['status'] != 'ACTIVE': fail('bank_archived', '题库已归档', 409)
        old = self.db.question_bank_items.find_one({'_id': oid(member_id), 'bankId': bank['_id']})
        if not old: fail('not_found', '题库成员不存在', 404)
        v = self.library.usable(user, data.versionId)
        if v['libraryQuestionId'] != old['libraryQuestionId']: fail('version_parent', '更新须选择同题的另一个版本', 422)
        try:
            changed = Repository(self.db.question_bank_items).change({'_id': old['_id'], 'revision': data.revision},
                        {'questionVersionId': v['_id'], 'position': data.position, 'updatedAt': utcnow()})
        except DuplicateKeyError: fail('duplicate_member', '目标版本已在题库中', 409)
        if not changed: fail('revision_conflict', '成员已修改，请刷新', 409)
        return wire(changed)

    def remove(self, user, bank_id, member_id, revision):
        bank = self.owned(user, bank_id)
        result = self.db.question_bank_items.delete_one({'_id': oid(member_id), 'bankId': bank['_id'], 'revision': revision})
        if not result.deleted_count: fail('revision_conflict', '成员不存在或已修改', 409)
        return {'ok': True}
