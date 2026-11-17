"""Recover idle pooled connections before sending any application command."""

from redis.asyncio import Redis
from redis.asyncio.connection import AbstractConnection, ConnectionPool
from redis.exceptions import AuthenticationError, ConnectionError, TimeoutError


class HealthyConnectionPool(ConnectionPool):
    async def ensure_connection(self, connection: AbstractConnection) -> None:
        for attempt in range(2):
            try:
                await super().ensure_connection(connection)
                # redis-py's normal health check uses the command retry policy,
                # which stays zero. Recover a failed pre-command probe here only.
                await connection.check_health()
                return
            except AuthenticationError:
                raise
            except (ConnectionError, TimeoutError):
                await connection.disconnect()
                if attempt:
                    raise


def from_url(url: str, **kwargs) -> Redis:
    # Retain redis-py's URL/TLS parsing, verification defaults and pool ownership.
    return Redis.from_pool(HealthyConnectionPool.from_url(url, **kwargs))
