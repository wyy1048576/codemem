from . import db
from .sessions import revoke_session


def disable_user(user):
    user.active = False
    for sid in list(user.session_ids):
        revoke_session(sid)
        user.session_ids.remove(sid)
    db.users.insert(user.id, user)


def get_user_by_id(user_id):
    return db.users.rows.get(user_id)
