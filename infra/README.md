# trego. Local infrastructure

PostgreSQL 18 with PostGIS and pgvector matches the major version selected by Aiven Free.
Valkey supplies the local API routing cache and agent cache/sessions. The deployed cache
uses Aiven Valkey. Install Docker with Compose and choose free local ports.

From the repository root, copy `.env.example` to `.env` once and set `POSTGRES_PASSWORD`.
If port 5432 or 6379 is occupied, change `POSTGRES_PORT` or `VALKEY_PORT` in `.env` and use
that port in the host-side client URLs. Both ports bind only to localhost. The local Valkey
cache is disposable and has no persistence volume; PostgreSQL retains saved routes.

```sh
docker compose --env-file .env -f infra/compose.yaml up --build --wait
docker compose --env-file .env -f infra/compose.yaml exec -T valkey valkey-cli ping
docker compose --env-file .env -f infra/compose.yaml exec -T db sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < infra/smoke.sql
```

The SQL smoke test checks a spatial query and a vector distance without changing the database.
It fails if initialization omitted either extension or a calculation returns the wrong result.
GitHub Actions runs the same SQL and verifies Valkey is reachable for PR changes under
`infra/` or to `.github/workflows/infra.yml`. API tests check cache TTL and failure behavior.
The API and tests use the same Valkey 8.1 image line; this does not assert the Aiven service's
engine version. Deploy using the team's Aiven TLS endpoint as described in [the route guide](../api/ROUTES.md#configure-aiven-valkey).

```sh
docker compose --env-file .env -f infra/compose.yaml down
```

The named volume retains data between runs. On its first start with an empty volume, PostgreSQL enables `postgis` and `vector`. Flyway migrations in the `api/` module will create application tables as the API is developed.

## Shared Aiven Free database

Aiven Free provides 1 GB RAM, 1 GB storage and a maximum of 20 PostgreSQL connections.
Reserve six connections for service management when budgeting client pools. Managed
PgBouncer pooling is unavailable on Free. See the [Free plan](https://aiven.io/docs/products/postgresql/concepts/pg-free-tier)
and [connection budget](https://aiven.io/docs/products/postgresql/reference/pg-connection-limits).

Each Java API defaults to a maximum of three Hikari connections, a minimum idle count
of zero, and a 60,000 ms idle timeout. Hikari retires idle connections on its maintenance
schedule, so release can occur slightly later. Three API processes can therefore hold
up to nine pooled connections. Allow extra capacity for Flyway during startup and for
SQL clients. Start shared-database instances one at a time and close unused IDE database
connections. Each replica or JVM has its own pool. These settings apply after restart.

Use the same values from `.env.example` or `api/container.env.example` on each developer's
machine. A higher maximum or minimum idle count overrides this budget. The tradeoff
is that bursts wait for one of three connections, and a request after inactivity may
need to establish a new TLS connection. The Python agent accesses PostgreSQL through
the API and does not need its own PostgreSQL pool.

### Local development resource rules

These rules apply to all three developers and their coding agents whenever a locally
running process can access shared Aiven resources.

1. Use local PostgreSQL and Valkey for ordinary development, automated tests and repeated
   debugging. Connect to Aiven for coordinated integration checks and demonstrations.
   Confirm the effective database and cache targets before starting services or tests.
2. Run only the services needed for the current task. Use one API process per developer
   against shared PostgreSQL and include every additional JVM or replica in the budget.
   Keep Hikari maximum pool size at three, minimum idle at zero and idle timeout at
   60,000 ms for the Free service. Agree a new team budget before raising these values.
3. Coordinate simultaneous Aiven checks. The three API pools have a combined maximum of
   nine connections. Leave capacity for migrations, service management and SQL tools.
   Start shared-database instances sequentially and close unused IDE database sessions.
4. Run automated test suites and load tests against disposable local services. For a live
   Aiven check, use a small, agreed scenario set and bounded concurrency. Stop repeated
   requests when dependency failures appear and inspect the failure before another run.
   Before a local E2E run that uses Aiven, tell the team which shared services it will
   access, the planned concurrency and who will stop the environment afterward. Developers
   must pass these rules to the coding agents that launch or repeat E2E runs on their machines.
5. Reuse valid cache entries and retain configured TTLs. Clear shared cache entries only
   for a specific, coordinated diagnostic. Use local Valkey for cold-cache experiments.
   Shared cache data can include teammates' active chat sessions and rate-limit state.
6. Keep the shared integration dataset small. Coordinate bulk imports, index builds and
   cleanup with the team. Monitor PostgreSQL storage and Valkey memory during live checks.
   Delete only identified disposable test data after checking who still needs it.
7. After testing, stop the API, agent, frontend and temporary containers started for that
   session. Verify their processes have exited and database connections have closed.
   Closing a browser tab alone does not stop the backend. Keep a manual testing session
   running only while its user still needs it, and identify who will stop it.
8. On an OOM alert, pause your requests and inform the team with the timestamp and affected
   service. Check memory, connection counts and logs before resuming. Coordinate recovery
   of the shared service with Murat, including any restart or memory-setting change.

### Memory incident checks

For a memory incident, first record the exact alert, its timestamp, memory metrics and
service logs. Pause application traffic and inspect sessions with read-only SQL in one
client connection. This shows connection counts and open transactions, not RAM usage
per query or the cause of an earlier incident.

```sql
SELECT application_name, state, count(*)
FROM pg_stat_activity
WHERE backend_type = 'client backend'
GROUP BY application_name, state
ORDER BY application_name, state;

SELECT pid, application_name, state, now() - xact_start AS transaction_age
FROM pg_stat_activity
WHERE backend_type = 'client backend'
  AND xact_start < now() - interval '60 seconds'
ORDER BY xact_start;

SHOW work_mem;
SHOW max_connections;
SELECT pg_size_pretty(pg_database_size(current_database()));
```

If the service has already recovered, resume one API with the reduced pool and watch
memory and connection metrics before starting more instances. If it remains unavailable,
use the console's recovery or restart action once after pausing clients, then confirm
service health. Restarting alone does not resolve a recurring memory problem. Investigate
expensive queries and long transactions if memory rises despite a small connection count.
Tune server memory settings only after that diagnosis. Increasing `max_connections`
increases potential resource use. A pool budget alone cannot guarantee that every workload
fits into 1 GB RAM.
