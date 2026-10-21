"""Session storage."""

import secrets

from . import db


def new_token():
    return secrets.token_hex(16)


def create_session(user_id):
    """Open a new session for a user and return its id."""
    token = new_token()
    db.sessions.insert(token, Session(token, user_id))
    return token


def revoke_session(session_id):
    db.sessions.delete(session_id)


class Session:
    def __init__(self, sid, user_id):
        self.sid = sid
        self.user_id = user_id
