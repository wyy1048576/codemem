from auth.sessions import create_session, revoke_session
from auth.users import get_user_by_id


def login(request):
    user = get_user_by_id(request.user_id)
    return {"token": create_session(user.id)}


def logout(request):
    revoke_session(request.token)
    return {"ok": True}
