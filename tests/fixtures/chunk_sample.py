"""Sample module for chunker tests."""

import functools
from db import sessions

MAX_AGE = 3600
configure_logging()


def plain(a, b=1):
    """Add things.

    More detail here.
    """
    return helper(a) + db.sessions.delete(b)


@functools.lru_cache(maxsize=None)
@trace
def decorated(x):
    return x


async def fetch(url: str) -> bytes:
    data = await client.get(url)
    return data


class SessionManager(Base):
    timeout = 30

    def expire_old(self, now):
        def is_old(s):
            return s.age(now) > self.timeout

        return [s for s in self.all() if is_old(s)]

    @property
    def count(self):
        return len(self.all())

    @count.setter
    def count(self, value):
        raise AttributeError("read only")


if __name__ == "__main__":
    main()
