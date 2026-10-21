"""Tiny in-memory stand-in for a database."""


class Table:
    def __init__(self):
        self.rows = {}

    def insert(self, key, value):
        self.rows[key] = value

    def delete(self, key):
        self.rows.pop(key, None)

    def find(self, **filters):
        return [r for r in self.rows.values() if all(getattr(r, k) == v for k, v in filters.items())]


sessions = Table()
users = Table()
