import os

CONSTANT = 1


def top(a, b):
    return a + b


async def fetch(url):
    return url


@decorator(
    "multi-line",
)
def decorated():
    square = lambda x: x * x
    return square(2)


class SessionManager:
    timeout = 30

    def revoke_session(self, user):
        def helper(s):
            return s.close()

        for s in self.sessions(user):
            helper(s)

    class Config:
        def load(self):
            return {}

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
