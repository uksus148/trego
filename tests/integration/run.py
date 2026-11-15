#!/usr/bin/env python3
"""Disposable actual-service acceptance; no developer .env or live provider access."""

import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "api/target/fixture-e2e"
CORPUS = json.loads((ROOT / "docs/contracts/baseline.examples.json").read_text())
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with HTTP.open(req, timeout=90) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=str(ROOT / "agent/.venv/bin/python"))
    parser.add_argument("--editor", action="store_true", help="Include the saved-route editor browser scenario.")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    # Allowlist instead of stripping a growing list of cloud-secret variable names.
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "JAVA_HOME", "TMPDIR", "SYSTEMROOT", "PLAYWRIGHT_BROWSERS_PATH"}}
    env.update({"NO_PROXY": "127.0.0.1,localhost", "PYTHONDONTWRITEBYTECODE": "1"})
    containers, processes, logs, ors_calls = [], [], [], []

    def run(command, **kwargs):
        return subprocess.run(command, cwd=ROOT, env=kwargs.pop("env", env), check=True, text=True, **kwargs)

    def capture(command):
        return run(command, stdout=subprocess.PIPE).stdout.strip()

    def start(name, command, extra=None, cwd=ROOT):
        log = (OUT / f"{name}.log").open("w")
        logs.append(log)
        proc = subprocess.Popen(command, cwd=cwd, env={**env, **(extra or {})}, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        processes.append(proc)
        return proc

    def ready(url, proc):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert proc.poll() is None, f"Service stopped during startup; inspect {OUT}"
            try:
                request(url)
                return
            except (OSError, ValueError):
                time.sleep(.2)
        raise AssertionError("Service readiness deadline exceeded")

    class Ors(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/v2/directions/foot-hiking/geojson", self.path
            # Spring's HTTP client streams JSON using HTTP/1.1 chunked transfer.
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                chunks = []
                while True:
                    size = int(self.rfile.readline().split(b";")[0], 16)
                    if size == 0:
                        assert self.rfile.readline() == b"\r\n"
                        break
                    chunks.append(self.rfile.read(size))
                    assert self.rfile.read(2) == b"\r\n"
                raw = b"".join(chunks)
            else:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
            body = json.loads(raw)
            assert set(body) == {"coordinates", "elevation", "instructions", "units"}
            assert body["units"] == "m" and body["elevation"] is True and body["instructions"] is False
            ors_calls.append(body)
            result = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": CORPUS["route"]["geojson"],
                      "properties": {"summary": {"distance": 7500, "duration": 5400, "ascent": 600}}}]}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    ors = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ors)
    threading.Thread(target=ors.serve_forever, daemon=True).start()
    source_files = capture(["git", "ls-files", "--cached", "--others", "--exclude-standard"]).splitlines()
    source_digest = hashlib.sha256()
    for name in sorted(source_files):
        if name.startswith(("api/src/", "agent/src/", "frontend/src/", "tests/integration/", "docs/contracts/")):
            source_digest.update(name.encode() + b"\0" + (ROOT / name).read_bytes() + b"\0")
    evidence = {"profile": "synthetic-fixture-v1", "revision": capture(["git", "rev-parse", "HEAD"]),
                "sourceTreeSha256": source_digest.hexdigest(),
                "worktreeDiffSha256": hashlib.sha256(capture(["git", "diff", "HEAD"]).encode()).hexdigest(),
                "externalProviders": "strict fixtures; not live acceptance", "result": "failed"}
    try:
        print("Building canonical PostgreSQL18/PostGIS/pgvector and actual API", flush=True)
        # A previous feature branch can leave obsolete migrations/classes in target.
        # Keep the build log outside target until clean completes.
        with tempfile.TemporaryFile(mode="w+") as build:
            try:
                run(["docker", "build", "-t", "trego-fixture-postgres", "infra/postgres"], stdout=build, stderr=subprocess.STDOUT)
                run(["mvn", "-B", "-ntp", "-f", "api/pom.xml", "-DskipTests", "clean", "package"], stdout=build, stderr=subprocess.STDOUT)
            finally:
                OUT.mkdir(parents=True, exist_ok=True)
                build.seek(0)
                (OUT / "build.log").write_text(build.read())
        for image, internal, extras in [
            ("trego-fixture-postgres", 5432, ["-e", "POSTGRES_DB=fixture", "-e", "POSTGRES_USER=fixture", "-e", "POSTGRES_PASSWORD=fixture-only"]),
            ("valkey/valkey:8.1-alpine", 6379, []),
        ]:
            container = capture(["docker", "run", "--rm", "-d", "-p", f"127.0.0.1::{internal}", *extras, image])
            containers.append(container)
        db, cache = containers
        db_port = capture(["docker", "port", db, "5432"]).rsplit(":", 1)[1]
        cache_port = capture(["docker", "port", cache, "6379"]).rsplit(":", 1)[1]
        for _ in range(120):
            probe = subprocess.run(["docker", "exec", db, "pg_isready", "-U", "fixture", "-d", "fixture"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if probe.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise AssertionError("Disposable PostgreSQL did not become ready")
        api_port, agent_port, frontend_port = port(), port(), port()
        api_url, agent_url, frontend_url = [f"http://127.0.0.1:{p}" for p in (api_port, agent_port, frontend_port)]
        valkey_url = f"redis://127.0.0.1:{cache_port}/0"
        fixture_url = f"http://127.0.0.1:{ors.server_port}"
        catalog = json.loads((ROOT / "api/src/test/resources/media/catalog-fixture.json").read_text())
        catalog["entries"][0]["identity"] = {"type": "node", "id": CORPUS["osmIds"][1]}
        (OUT / "catalog.json").write_text(json.dumps(catalog))
        jar = ROOT / "api/target/api-0.0.1-SNAPSHOT.jar"
        api = start("api", ["java", "-jar", str(jar), "--spring.config.import=", f"--server.port={api_port}",
                    "--server.address=127.0.0.1", f"--spring.datasource.url=jdbc:postgresql://127.0.0.1:{db_port}/fixture",
                    "--spring.datasource.username=fixture", "--spring.datasource.password=fixture-only",
                    f"--spring.data.redis.url={valkey_url}", f"--routing.ors.base-url={fixture_url}",
                    "--routing.ors.api-key=fixture-only", f"--api.cors.allowed-origins={frontend_url}",
                    "--media.enabled=true", "--media.auto-discovery-enabled=false", f"--media.catalog=file:{OUT / 'catalog.json'}",
                    f"--media.nominatim-base-url={fixture_url}", f"--media.wikidata-url={fixture_url}/wikidata", f"--media.commons-url={fixture_url}/commons"])
        ready(api_url + "/api/places?bbox=19,48,21,50", api)
        agent = start("agent", [args.python, "-m", "uvicorn", "fixture_agent:app", "--host", "127.0.0.1", "--port", str(agent_port)],
                      {"PYTHONPATH": str(ROOT / "agent/src") + os.pathsep + str(ROOT / "tests/integration"),
                       "E2E_API_PORT": str(api_port), "E2E_VALKEY_URL": valkey_url, "E2E_FRONTEND_URL": frontend_url})
        ready(agent_url + "/openapi.json", agent)
        vite = start("frontend", ["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"), str(ROOT / "frontend"),
                     "--config", str(ROOT / "tests/integration/vite.config.ts"), "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
                     {"VITE_USE_MOCKS": "false", "VITE_API_BASE_URL": api_url, "VITE_AGENT_BASE_URL": agent_url, "VITE_ENABLE_ROUTE_EDITOR": str(args.editor).lower()})
        # Vite serves HTML; verify readiness without parsing it as JSON.
        for _ in range(100):
            assert vite.poll() is None, "Frontend exited"
            try:
                HTTP.open(frontend_url, timeout=1).close()
                break
            except OSError:
                time.sleep(.2)
        else:
            raise AssertionError("Frontend readiness deadline exceeded")

        def count(table):
            assert table in ("places", "routes")
            return int(capture(["docker", "exec", db, "psql", "-U", "fixture", "-d", "fixture", "-Atc", f"SELECT count(*) FROM {table}"]))

        def chat(session, message):
            return request(agent_url + "/api/chat", {"sessionId": session, "message": message})

        print("Checking real chat, persistence, repeated stops, sources and cache", flush=True)
        first = chat("fixture-first", CORPUS["message"])
        assert set(first) == {"reply", "places", "routeId"}, first
        saved = request(api_url + "/api/routes/" + first["routeId"])
        assert saved["geojson"] == CORPUS["route"]["geojson"]
        assert [p["name"] for p in saved["places"]] == [CORPUS["places"][i]["name"] for i in CORPUS["stopIndexes"]]
        assert {k: saved[k] for k in ("distanceKm", "ascentM", "durationMin")} == {k: CORPUS["route"][k] for k in ("distanceKm", "ascentM", "durationMin")}
        assert len(first["places"]) == count("places") == 3
        for actual, expected in zip(first["places"], CORPUS["places"], strict=True):
            assert {k:v for k,v in actual.items() if k != "id"} == {k:v for k,v in expected.items() if k != "id"}
        second = chat("fixture-second", CORPUS["message"])
        assert second["routeId"] != first["routeId"] and count("routes") == 2
        second_saved = request(api_url + "/api/routes/" + second["routeId"])
        assert {k:v for k,v in saved.items() if k != "id"} == {k:v for k,v in second_saved.items() if k != "id"}
        assert len(ors_calls) == 1
        assert ors_calls[0]["coordinates"] == CORPUS["route"]["geojson"]["coordinates"]
        before = count("places"), count("routes")
        before_api = [call for call in request(agent_url + "/__fixture/calls") if call.startswith("api:")]
        unclear = chat("fixture-incomplete", CORPUS["incompleteMessage"])
        assert unclear["places"] == [] and "routeId" not in unclear
        assert before == (count("places"), count("routes")) and len(ors_calls) == 1
        assert before_api == [call for call in request(agent_url + "/__fixture/calls") if call.startswith("api:")]
        for payload, status in [({"unsupported": True}, 400), ({
            "start": {"lat": 49, "lon": 20}, "end": {"lat": 49.2, "lon": 20.2},
            "placeIds": ["ffffffff-ffff-4fff-8fff-ffffffffffff"], "preferences": []}, 422)]:
            try:
                request(api_url + "/api/routes", payload)
                raise AssertionError("Invalid route input was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == status
        assert before == (count("places"), count("routes")) and len(ors_calls) == 1
        stored = capture(["docker", "exec", cache, "valkey-cli", "--raw", "LRANGE", "gopstop:chat-session:fixture-first", "0", "-1"]).splitlines()
        assert [json.loads(row)["role"] for row in stored] == ["user", "assistant"]
        assert json.loads(stored[0])["content"] == CORPUS["message"]
        extensions = capture(["docker", "exec", db, "psql", "-U", "fixture", "-d", "fixture", "-Atc", "SELECT extname FROM pg_extension ORDER BY extname"])
        assert {"postgis", "vector"} <= set(extensions.splitlines())
        migrations = capture(["docker", "exec", db, "psql", "-U", "fixture", "-d", "fixture", "-Atc",
                              "SELECT script FROM flyway_schema_history WHERE success ORDER BY installed_rank"]).splitlines()
        assert sorted(migrations) == sorted(p.name for p in (ROOT / "api/src/main/resources/db/migration").glob("V*.sql"))
        for i, place in enumerate(first["places"]):
            media = request(api_url + f"/api/places/{place['id']}/media")
            assert media["status"] == ("ready" if i == 1 else "empty")
        evidence.update({"api": api_url, "agent": agent_url, "frontend": frontend_url, "chat": first, "route": saved,
                         "appliedMigrations": migrations,
                         "checks": {"newIdsOnCacheHit": True, "orderedRepeats": True, "sources": True,
                                    "noPartialPersistence": True, "sessionReadback": True, "postgisAndVector": True}})
        config = OUT / "services.json"
        config.write_text(json.dumps(evidence, indent=2))
        run(["npm", "test", "--prefix", "tests/integration"], env={**env, "E2E_CONFIG": str(config), "E2E_EDITOR": "1" if args.editor else "0"})
        browser = json.loads((OUT / "browser-results.json").read_text())
        assert browser["stats"]["unexpected"] == browser["stats"]["skipped"] == browser["stats"]["flaky"] == 0
        tests = [test for suite in browser["suites"] for spec in suite.get("specs", []) for test in spec["tests"]]
        assert len(tests) == (5 if args.editor else 4)
        assert all(test["expectedStatus"] == "passed" for test in tests), "Baseline regressions must not expect failure"
        calls = request(agent_url + "/__fixture/calls")
        assert calls.count("nominatim") == 3 and calls.count("exa") == 3
        assert calls.count("api:POST:/api/routes") == 6
        assert count("places") == 3 and count("routes") == (8 if args.editor else 6) and len(ors_calls) == (2 if args.editor else 1)
        evidence.update({"result": "passed",
                         "orsRequests": len(ors_calls), "providerFixtureCalls": calls,
                         "browser": {"passed": len(tests), "knownExpectedFailures": 0, "unexpected": 0, "skipped": 0}})
        print("Fixture acceptance complete: " + evidence["result"], flush=True)
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        for log in logs:
            log.close()
        for container in reversed(containers):
            subprocess.run(["docker", "rm", "-f", "-v", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ors.shutdown()
        (OUT / "report.json").write_text(json.dumps(evidence, indent=2))
        # Only allowlisted, synthetic harness logs are uploaded by CI.
        for path in OUT.glob("*.log"):
            path.write_text(path.read_text(errors="replace").replace(str(ROOT), "<checkout>").replace("fixture-only", "<redacted>"))
        browser_report = OUT / "browser-results.json"
        if browser_report.exists():
            browser_report.write_text(browser_report.read_text().replace(str(ROOT), "<checkout>").replace("fixture-only", "<redacted>"))


if __name__ == "__main__":
    main()
