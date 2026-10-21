from auth.sessions import revoke_session
from auth.users import disable_user


class FakeUser:
    def __init__(self, uid, session_ids):
        self.id = uid
        self.active = True
        self.session_ids = session_ids


def test_disabled_user_loses_sessions():
    user = FakeUser(1, ["s1", "s2"])
    disable_user(user)
    assert not user.active
    assert user.session_ids == []
    revoke_session("s1")  # revoking twice is a no-op
