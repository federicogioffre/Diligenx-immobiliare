#!/usr/bin/env python3
"""Opt-in staging load exercise using Python's standard library only.

Creates one workspace/deal per supplied account, uploads synthetic text,
waits for ingestion/analysis, probes isolation, and writes a redacted JSON
result. It never registers users, deletes data, or prints credentials.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import random
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


class CheckFailed(RuntimeError):
    """Contains a safe diagnostic only, never an HTTP body or credential."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Do not send a Bearer token or login form to a redirected host.
        return None


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def retry_delay(header: str | None, attempt: int) -> float:
    if header:
        try:
            return max(0.0, min(120.0, float(header)))
        except ValueError:
            try:
                delay = parsedate_to_datetime(header).timestamp() - time.time()
                return max(0.0, min(120.0, delay))
            except (ValueError, TypeError, OverflowError):
                pass
    return min(30.0, 2 ** attempt) + random.uniform(0, 0.5)


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = defaultdict(list)
        self.statuses = Counter()
        self.retries = 0

    def record(self, label: str, status: int, elapsed: float):
        with self.lock:
            self.samples[label].append(elapsed)
            self.statuses[str(status)] += 1

    def retry(self):
        with self.lock:
            self.retries += 1

    def summary(self):
        with self.lock:
            return {
                "http_statuses": dict(self.statuses),
                "retries": self.retries,
                "latency_seconds": {
                    key: {"requests": len(values),
                          "p50": round(percentile(values, 0.50), 3),
                          "p95": round(percentile(values, 0.95), 3),
                          "max": round(max(values), 3)}
                    for key, values in sorted(self.samples.items())
                },
            }


class API:
    def __init__(self, base_url: str, metrics: Metrics, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.metrics = metrics
        self.timeout = timeout
        self.token = ""
        self.opener = build_opener(NoRedirects())

    def request(self, method: str, path: str, label: str, *, payload=None,
                body: bytes | None = None, content_type: str | None = None,
                expected=(200,), replay_safe: bool = False):
        if payload is not None:
            body = json.dumps(payload).encode()
            content_type = "application/json"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if content_type:
            headers["Content-Type"] = content_type
        for attempt in range(9):
            started = time.monotonic()
            retry_after = None
            raw = b""
            try:
                request = Request(self.base_url + path, data=body,
                                  headers=headers, method=method)
                with self.opener.open(request, timeout=self.timeout) as response:
                    status = response.status
                    raw = response.read()
            except HTTPError as error:
                status = error.code
                retry_after = error.headers.get("Retry-After")
                error.close()
            except (URLError, TimeoutError, ConnectionError, OSError):
                status = 0
            self.metrics.record(label, status, time.monotonic() - started)
            if status in expected:
                try:
                    return json.loads(raw) if raw else None
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise CheckFailed(f"{label}: response is not JSON") from None
            # A 429 is rejected before mutation. Only GET and deduplicated
            # uploads replay ambiguous network errors/5xx; never replay a
            # workspace/deal creation or analysis submission after timeout.
            retryable = status == 429 or (replay_safe and status in (0, 502, 503, 504))
            if not retryable or attempt == 8:
                raise CheckFailed(f"{label}: unexpected HTTP status {status}")
            self.metrics.retry()
            time.sleep(retry_delay(retry_after, attempt))


@dataclass
class Actor:
    index: int
    api: API
    workspace_id: int
    deal_id: int
    owner_id: int
    uploaded_ids: set[int]

    def public_record(self):
        return {"account_index": self.index, "workspace_id": self.workspace_id,
                "deal_id": self.deal_id, "uploaded_documents": len(self.uploaded_ids)}


def prepare_actor(index, account, args, metrics, run_id):
    api = API(args.base_url, metrics, args.request_timeout)
    if account.get("token_env"):
        api.token = os.environ[account["token_env"]]
    else:
        login = api.request(
            "POST", "/auth/login", "login",
            body=urlencode({"username": account["email"],
                            "password": os.environ[account["password_env"]]}).encode(),
            content_type="application/x-www-form-urlencoded",
        )
        api.token = login["access_token"]
    workspace = api.request("POST", "/workspaces/", "create_workspace",
                            payload={"name": f"beta-{run_id}-u{index}"}, expected=(201,))
    deal = api.request("POST", f"/deals/?workspace_id={workspace['id']}", "create_deal",
                       payload={"title": f"Synthetic beta corpus {run_id} user {index}"},
                       expected=(201,))
    return Actor(index, api, workspace["id"], deal["id"], workspace["owner_id"], set())


def synthetic_document(run_id: str, actor_index: int, index: int, size: int) -> bytes:
    marker = f"BETA-{run_id}-U{actor_index}-D{index}"
    paragraph = (
        f"Synthetic contract {marker}. This document is generated test data. "
        "Either party may terminate this agreement with 30 days written notice. "
        "Liability is limited to the contract value. Confidential information "
        "must be protected for two years. No real company or client is represented.\n"
    )
    return (paragraph * (size // len(paragraph) + 1))[:size].encode("utf-8")


def multipart(filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "beta_" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: text/plain\r\n\r\n").encode()
    return body + content + f"\r\n--{boundary}--\r\n".encode(), \
        f"multipart/form-data; boundary={boundary}"


def upload_and_wait(actor: Actor, args, run_id: str):
    started = time.monotonic()
    for index in range(args.documents):
        filename = f"contract-{run_id}-u{actor.index}-{index:04d}.txt"
        body, content_type = multipart(
            filename, synthetic_document(run_id, actor.index, index, args.document_bytes))
        result = actor.api.request(
            "POST", f"/documents/upload?deal_id={actor.deal_id}", "upload",
            body=body, content_type=content_type, expected=(201,), replay_safe=True)
        document_id = result["id"]
        if document_id in actor.uploaded_ids:
            raise CheckFailed("distinct documents unexpectedly share an ID")
        actor.uploaded_ids.add(document_id)
        # Replaying the first response exercises upload idempotency explicitly.
        if index == 0:
            replay = actor.api.request(
                "POST", f"/documents/upload?deal_id={actor.deal_id}", "upload_replay",
                body=body, content_type=content_type, expected=(201,), replay_safe=True)
            if replay["id"] != document_id:
                raise CheckFailed("replayed upload created a duplicate document")
    deadline = time.monotonic() + args.job_timeout
    while time.monotonic() < deadline:
        documents = actor.api.request(
            "GET", f"/documents/deals/{actor.deal_id}/documents", "list_documents",
            replay_safe=True)
        if {doc["id"] for doc in documents} != actor.uploaded_ids:
            raise CheckFailed("document inventory contains missing or extra IDs")
        if any(doc["deal_id"] != actor.deal_id for doc in documents):
            raise CheckFailed("document inventory contains another deal")
        states = Counter(doc["status"] for doc in documents)
        if states["failed"]:
            raise CheckFailed(f"ingestion failed for {states['failed']} synthetic documents")
        if states["processed"] == args.documents:
            return {"account_index": actor.index,
                    "upload_and_ingestion_seconds": round(time.monotonic() - started, 3)}
        time.sleep(args.poll_seconds)
    raise CheckFailed("ingestion did not finish before job timeout")


def check_isolation(actor: Actor, foreign: Actor):
    for path, label in [
        (f"/deals/{foreign.deal_id}", "isolation_deal"),
        (f"/documents/deals/{foreign.deal_id}/documents", "isolation_documents"),
        (f"/deals/{foreign.deal_id}/report", "isolation_report"),
        (f"/deals/{foreign.deal_id}/agent-runs", "isolation_agent_runs"),
    ]:
        actor.api.request("GET", path, label, expected=(403, 404), replay_safe=True)


def analyze_and_wait(actor: Actor, args):
    started = time.monotonic()
    actor.api.request("POST", f"/deals/{actor.deal_id}/analyze", "analyze", expected=(202,))
    deadline = time.monotonic() + args.job_timeout
    while time.monotonic() < deadline:
        deal = actor.api.request("GET", f"/deals/{actor.deal_id}", "get_deal", replay_safe=True)
        runs = actor.api.request("GET", f"/deals/{actor.deal_id}/agent-runs",
                                  "agent_runs", replay_safe=True)
        if any(run["status"] == "failed" for run in runs):
            raise CheckFailed("analysis has a failed stage")
        if deal["status"] == "reviewed":
            if not runs or any(run["status"] != "completed" for run in runs):
                raise CheckFailed("reviewed deal has incomplete stage records")
            report = actor.api.request("GET", f"/deals/{actor.deal_id}/report",
                                        "get_report", replay_safe=True)
            if report.get("deal_id") != actor.deal_id:
                raise CheckFailed("report belongs to another deal")
            if not report.get("content") and not report.get("markdown"):
                raise CheckFailed("analysis completed without a report")
            return {"account_index": actor.index, "stages": len(runs),
                    "analysis_seconds": round(time.monotonic() - started, 3)}
        if deal["status"] == "draft":
            raise CheckFailed("analysis returned to draft without completion")
        time.sleep(args.poll_seconds)
    raise CheckFailed("analysis did not finish before job timeout")


def parallel_stage(actors, function, failures, name, *arguments):
    results = []
    with ThreadPoolExecutor(max_workers=len(actors)) as pool:
        futures = {pool.submit(function, actor, *arguments): actor.index for actor in actors}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as error:
                # Unknown errors may include a credential or response body;
                # only the dedicated sanitized exception is echoed.
                message = str(error) if isinstance(error, CheckFailed) else type(error).__name__
                failures.append({"account_index": futures[future], "stage": name,
                                 "error": message})
    return results


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Staging API URL, without /docs")
    parser.add_argument("--accounts", type=Path, required=True)
    parser.add_argument("--users", type=int, choices=(5, 10), default=5)
    parser.add_argument("--documents", type=int, choices=(100, 300), default=100)
    parser.add_argument("--document-bytes", type=int, default=8000)
    parser.add_argument("--provider-mode", choices=("fake", "real"), required=True,
                        help="Operator assertion; this script cannot verify server credentials")
    parser.add_argument("--execute", action="store_true", help="Actually create staging data")
    parser.add_argument("--ingestion-only", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--job-timeout", type=float, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=3)
    parser.add_argument("--read-p95-seconds", type=float, default=2)
    parser.add_argument("--output", type=Path, default=Path("beta-load-result.json"))
    args = parser.parse_args(argv)
    url = urlsplit(args.base_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password \
            or url.query or url.fragment:
        parser.error("base-url must be an HTTP(S) URL without credentials/query/fragment")
    if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        parser.error("remote staging requires HTTPS")
    if not 1024 <= args.document_bytes <= 1024 * 1024:
        parser.error("document-bytes must be between 1024 and 1048576")
    if min(args.request_timeout, args.job_timeout, args.poll_seconds, args.read_p95_seconds) <= 0:
        parser.error("timeouts, polling and latency target must be positive")
    return args


def main(argv=None):
    args = parse_args(argv)
    accounts = json.loads(args.accounts.read_text(encoding="utf-8"))["accounts"][:args.users]
    if len(accounts) != args.users:
        raise CheckFailed("accounts file contains fewer accounts than requested")
    identities = [account.get("token_env") or account.get("email") for account in accounts]
    if None in identities or len(set(identities)) != args.users:
        raise CheckFailed("supply distinct test accounts")
    for account in accounts:
        name = account.get("token_env") or account.get("password_env")
        if not name or not os.environ.get(name):
            raise CheckFailed("a required credential environment variable is missing")
    if not args.execute:
        print(json.dumps({"dry_run": True, "users": args.users,
                          "documents_per_user": args.documents,
                          "total_documents": args.users * args.documents,
                          "provider_mode_declared": args.provider_mode,
                          "analysis": not args.ingestion_only}))
        return 0

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    metrics, failures, actors = Metrics(), [], []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        pending = {pool.submit(prepare_actor, i, account, args, metrics, run_id): i
                   for i, account in enumerate(accounts)}
        for future in as_completed(pending):
            try:
                actors.append(future.result())
            except Exception as error:
                failures.append({"account_index": pending[future], "stage": "prepare",
                                 "error": str(error) if isinstance(error, CheckFailed)
                                 else type(error).__name__})
    actors.sort(key=lambda actor: actor.index)
    ingestion, analysis = [], []
    if len({actor.owner_id for actor in actors}) != len(actors):
        failures.append({"stage": "prepare", "error": "accounts resolve to the same owner"})
    if not failures:
        ingestion = parallel_stage(actors, upload_and_wait, failures, "ingestion", args, run_id)
        for i, actor in enumerate(actors):
            try:
                check_isolation(actor, actors[(i + 1) % len(actors)])
            except CheckFailed as error:
                failures.append({"account_index": actor.index, "stage": "isolation",
                                 "error": str(error)})
        if not failures and not args.ingestion_only:
            analysis = parallel_stage(actors, analyze_and_wait, failures, "analysis", args)
            if not failures:
                # Probe again now that foreign reports and stage records
                # exist: a pre-analysis report 404 alone proves no isolation.
                for i, actor in enumerate(actors):
                    try:
                        check_isolation(actor, actors[(i + 1) % len(actors)])
                    except CheckFailed as error:
                        failures.append({"account_index": actor.index, "stage": "isolation",
                                         "error": str(error)})
    summary = metrics.summary()
    read_labels = ("list_documents", "get_deal", "agent_runs", "get_report")
    slow_reads = [label for label in read_labels
                  if summary["latency_seconds"].get(label, {}).get("p95", 0)
                  > args.read_p95_seconds]
    if slow_reads:
        failures.append({"stage": "latency", "error": "read p95 target exceeded",
                         "operations": slow_reads})
    result = {
        "run_id": run_id, "passed": not failures,
        "scope": "ingestion_only" if args.ingestion_only else "synthetic_pipeline",
        "provider_mode_declared": args.provider_mode,
        "users": args.users, "documents_per_user": args.documents,
        "bytes_per_document": args.document_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "read_p95_target_seconds": args.read_p95_seconds,
        "resources_created": [actor.public_record() for actor in actors],
        "ingestion": ingestion, "analysis": analysis, "failures": failures, **summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": run_id, "passed": result["passed"],
                      "failed_checks": len(failures), "result_file": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckFailed as error:
        print(json.dumps({"passed": False, "error": str(error)}))
        raise SystemExit(1)
