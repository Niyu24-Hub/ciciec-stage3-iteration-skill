#!/usr/bin/env python3
"""Automate CICIEC online judge access for Stage 3 CI artifacts.

Credentials are read from CICIEC_JUDGE_USER and CICIEC_JUDGE_PASSWORD. Optional
GitLab token updates use CICIEC_JUDGE_GITLAB_TOKEN. Secrets are never written to
output files.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


DEFAULT_BASE = os.environ.get("CICIEC_JUDGE_BASE_URL", "")
DEFAULT_PROJECT_ID = os.environ.get("CICIEC_GITLAB_PROJECT_ID", "")
DEFAULT_REF = os.environ.get("CICIEC_CI_REF", os.environ.get("CICIEC_SUBMISSION_REF", "submit/codex"))
DEFAULT_STAGE3_LAB_ID = os.environ.get("CICIEC_STAGE3_LAB_ID", "")
DEFAULT_EVAL_JSONL = "ci_data/ciciec_stage3_eval_results.jsonl"
DEFAULT_WINNER_SCRIPT = "tools/update_ciciec_eval_winners.py"
DEFAULT_POLL_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 1800
CN_TZ = timezone(timedelta(hours=8))
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
FINAL_STATES = {"Finished", "SysErr", "Failed", "Canceled"}


class JudgeError(RuntimeError):
    pass


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_submission_repo() -> Path:
    configured = os.environ.get("CICIEC_SUBMISSION_REPO")
    return Path(configured) if configured else workspace_root() / "regional-submission"


def now_cn() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def parse_platform_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def normalize_sha(value: Any) -> str:
    return str(value or "").strip().lower()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "..." + value[-2:]
    return value[:6] + "..." + value[-4:]


def api_url(base: str, path: str, query: dict[str, str] | None = None) -> str:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


class JudgeClient:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.username = username
        self.password = password
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        form: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: int = 60,
        attempts: int = 4,
    ) -> tuple[int, bytes, urllib.response.addinfourl]:
        body = None
        headers = {"User-Agent": "codex-ciciec-judge/1.0"}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json;charset=utf-8"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        url = api_url(self.base, path, query)
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
            try:
                resp = self.opener.open(req, timeout=timeout)
                data = resp.read()
                return resp.status, data, resp
            except urllib.error.HTTPError as exc:
                data = exc.read()
                if exc.code in RETRYABLE_HTTP_STATUS and attempt < attempts:
                    time.sleep(min(30, 2**attempt))
                    continue
                raise JudgeError(f"HTTP {exc.code} for {url}: {data[:200]!r}") from exc
            except urllib.error.URLError as exc:
                if attempt < attempts:
                    time.sleep(min(30, 2**attempt))
                    continue
                raise JudgeError(f"request failed for {url}: {exc}") from exc
        raise JudgeError(f"request failed for {url}")

    def request_text(self, method: str, path: str, *, allow_signin_page: bool = False, **kwargs: Any) -> str:
        status, body, resp = self.request_bytes(method, path, **kwargs)
        if status < 200 or status >= 300:
            raise JudgeError(f"HTTP {status} for {path}: {body[:200]!r}")
        if not allow_signin_page and resp.headers.get("X-Signin-Page") == "1":
            raise JudgeError("judge platform redirected to signin; check credentials")
        return body.decode("utf-8", "replace")

    def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        text = self.request_text(method, path, **kwargs)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise JudgeError(f"expected JSON from {path}, got: {text[:200]!r}") from exc

    def login(self) -> None:
        self.request_text("GET", "signin", allow_signin_page=True)
        text = self.request_text(
            "POST",
            "signin",
            form={"username": self.username, "password": self.password},
            timeout=30,
            allow_signin_page=True,
        )
        if "账号密码登录" in text and "inputPassword" in text:
            raise JudgeError("judge login failed; signin page returned after POST")
        self.request_text("GET", "judge", timeout=30)

    def gitlab_info(self) -> dict[str, Any]:
        body = self.request_json("POST", "getGitlabInfo", json_body={"uname": self.username}, timeout=30)
        if not isinstance(body, dict):
            raise JudgeError(f"unexpected getGitlabInfo response: {body!r}")
        return body

    def set_gitlab_token(self, token: str) -> str:
        text = self.request_text(
            "POST",
            "change_id",
            json_body={"utoken": token, "uname": self.username},
            timeout=30,
        )
        return text.strip()

    def course_labs(self) -> list[dict[str, Any]]:
        body = self.request_json("GET", "all_course_labs", timeout=30)
        if not isinstance(body, list):
            raise JudgeError(f"unexpected all_course_labs response: {body!r}")
        return body

    def lab_info(self, lab_id: str) -> dict[str, Any]:
        body = self.request_json("GET", "lab_info", query={"lab_id": lab_id}, timeout=30)
        if not isinstance(body, dict):
            raise JudgeError(f"unexpected lab_info response: {body!r}")
        return body

    def ci_projects(self, page: int = 1) -> dict[str, Any]:
        body = self.request_json("GET", "ci_projects", query={"page": str(page), "_": str(int(time.time() * 1000))})
        if not isinstance(body, dict):
            raise JudgeError(f"unexpected ci_projects response: {body!r}")
        return body

    def ci_refs(self, project_id: str) -> list[str]:
        body = self.request_json(
            "GET",
            "ci_refs",
            query={"project_id": str(project_id), "_": str(int(time.time() * 1000))},
        )
        if not isinstance(body, dict):
            raise JudgeError(f"unexpected ci_refs response: {body!r}")
        return list(body.get("refs") or [])

    def ci_info(self, project_id: str, ref: str, page: int = 1) -> dict[str, Any]:
        body = self.request_json(
            "GET",
            "ci_info",
            query={
                "project_id": str(project_id),
                "ref": ref,
                "page": str(page),
                "_": str(int(time.time() * 1000)),
            },
            timeout=60,
        )
        if not isinstance(body, dict):
            raise JudgeError(f"unexpected ci_info response: {body!r}")
        return body

    def submissions(self, lab_id: str, *, final: bool, manual_refresh: bool = False) -> list[dict[str, Any]]:
        query = {"lab_id": lab_id, "final": "true" if final else "false"}
        if manual_refresh:
            query["manual_refresh"] = "true"
        body = self.request_json("GET", "submissions", query=query, timeout=60)
        if not isinstance(body, list):
            raise JudgeError(f"unexpected submissions response: {body!r}")
        return body

    def submit_judge(self, lab_id: str, project_id: str, job_id: str) -> str:
        text = self.request_text(
            "POST",
            "submit_judge",
            json_body={"labId": lab_id, "source": "ci", "projectId": str(project_id), "jobId": str(job_id)},
            timeout=60,
        )
        return text.strip()

    def mark_final(self, lab_id: str, submission_id: int) -> dict[str, Any]:
        body = self.request_json(
            "POST",
            "mark_final",
            json_body={"labId": lab_id, "subId": submission_id},
            timeout=30,
        )
        if not isinstance(body, dict):
            raise JudgeError(f"unexpected mark_final response: {body!r}")
        return body


def make_client(args: argparse.Namespace) -> JudgeClient:
    username = os.environ.get("CICIEC_JUDGE_USER")
    password = os.environ.get("CICIEC_JUDGE_PASSWORD")
    if not username or not password:
        raise SystemExit("error: set CICIEC_JUDGE_USER and CICIEC_JUDGE_PASSWORD in the shell")
    client = JudgeClient(args.base, username, password)
    client.login()
    return client


def resolve_lab_id(client: JudgeClient, lab_id: str | None) -> str:
    if lab_id:
        return lab_id
    labs = client.course_labs()
    visible_stage3: list[dict[str, Any]] = []
    fallback_stage3: list[dict[str, Any]] = []
    for course in labs:
        for lab in course.get("labs") or []:
            name = str(lab.get("name") or "")
            desc = str(lab.get("description") or "")
            if "阶段任务三" in name or "Stage 3" in desc or "stage3" in desc.lower():
                fallback_stage3.append(lab)
                if lab.get("show", True):
                    visible_stage3.append(lab)
    for lab in visible_stage3 + fallback_stage3:
        if DEFAULT_STAGE3_LAB_ID and str(lab.get("_id")) == DEFAULT_STAGE3_LAB_ID:
            return DEFAULT_STAGE3_LAB_ID
    if visible_stage3:
        return str(visible_stage3[-1]["_id"])
    if fallback_stage3:
        return str(fallback_stage3[-1]["_id"])
    raise JudgeError("no Stage 3 lab found; set CICIEC_STAGE3_LAB_ID or pass --lab-id")


def current_git_commit(repo: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise JudgeError(f"cannot resolve current git commit from {repo}") from exc


def collect_ci_jobs(client: JudgeClient, project_id: str, ref: str, pages: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        info = client.ci_info(project_id, ref, page)
        jobs.extend(info.get("jobs") or [])
        if not info.get("next_page"):
            break
    return jobs


def is_usable_ci_job(job: dict[str, Any]) -> bool:
    return job.get("status") == "success" and bool(job.get("artifacts_file"))


def resolve_ci_job(client: JudgeClient, args: argparse.Namespace) -> dict[str, Any]:
    jobs = collect_ci_jobs(client, str(args.project_id), args.ref, args.ci_pages)
    if not jobs:
        raise JudgeError(f"no CI jobs visible for project={args.project_id} ref={args.ref}")

    if args.job_id:
        for job in jobs:
            if str(job.get("id")) == str(args.job_id):
                if not is_usable_ci_job(job) and not args.allow_non_success:
                    raise JudgeError(f"CI job {args.job_id} is not a successful artifact job")
                return job
        raise JudgeError(f"CI job {args.job_id} not found in first {args.ci_pages} page(s)")

    if args.latest_success:
        for job in jobs:
            if is_usable_ci_job(job):
                return job
        raise JudgeError(f"no successful artifact job found for project={args.project_id} ref={args.ref}")

    commit = args.commit
    if commit == "current":
        commit = current_git_commit(Path(args.submission_repo))
    commit_norm = normalize_sha(commit)
    if not commit_norm:
        raise JudgeError("empty commit selector")
    for job in jobs:
        job_commit = normalize_sha(job.get("commit") or job.get("commit_s"))
        job_short = normalize_sha(job.get("commit_s"))
        if job_commit.startswith(commit_norm) or commit_norm.startswith(job_commit) or job_short.startswith(commit_norm):
            if not is_usable_ci_job(job) and not args.allow_non_success:
                raise JudgeError(
                    f"matching CI job {job.get('id')} for {commit_norm[:8]} is not a successful artifact job"
                )
            return job
    raise JudgeError(f"no CI job found for commit {commit_norm[:12]} in first {args.ci_pages} page(s)")


def combined_submissions(client: JudgeClient, lab_id: str, manual_refresh: bool = False) -> list[dict[str, Any]]:
    rows = client.submissions(lab_id, final=False, manual_refresh=manual_refresh)
    final_rows = client.submissions(lab_id, final=True, manual_refresh=False)
    by_id: dict[int, dict[str, Any]] = {}
    for row in rows + final_rows:
        try:
            by_id[int(row["_id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(by_id.values(), key=lambda item: int(item.get("_id") or 0), reverse=True)


def find_submission_for_job(
    submissions: list[dict[str, Any]], project_id: str, job_id: str
) -> dict[str, Any] | None:
    matches = [
        row
        for row in submissions
        if str(row.get("ci_project_id")) == str(project_id) and str(row.get("ci_job_id")) == str(job_id)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: int(item.get("_id") or 0))


def wait_for_submission(
    client: JudgeClient,
    lab_id: str,
    project_id: str,
    job_id: str,
    *,
    timeout_seconds: int,
    poll_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_state = ""
    while True:
        rows = combined_submissions(client, lab_id, manual_refresh=True)
        submission = find_submission_for_job(rows, project_id, job_id)
        if submission:
            state = str(submission.get("state") or "")
            if state != last_state:
                print(f"submission {submission.get('_id')} state={state}")
                last_state = state
            if state in FINAL_STATES:
                return submission
        if time.monotonic() >= deadline:
            if submission:
                return submission
            raise JudgeError(f"timed out waiting for submission for job {job_id}")
        time.sleep(poll_seconds)


def result_json_items(submission: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for result in submission.get("result") or []:
        parsed: dict[str, Any] = {}
        raw = result.get("result_json")
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
        items.append(
            {
                "testcase_id": result.get("testcase_id"),
                "thinpad_id": result.get("thinpad_id"),
                "success": result.get("success"),
                "score": result.get("score"),
                "run_time": result.get("run_time"),
                "feedback": parsed,
            }
        )
    return items


def score_percent(submission: dict[str, Any]) -> float | None:
    for item in result_json_items(submission):
        feedback = item.get("feedback") or {}
        if isinstance(feedback, dict) and feedback.get("score_percent") is not None:
            return round(float(feedback["score_percent"]), 2)
    value = submission.get("score")
    if value is None:
        return None
    return round(float(value) * 100.0, 2)


def submission_record(submission: dict[str, Any], lab_id: str, project_id: str) -> dict[str, Any]:
    status = str(submission.get("state") or "")
    percent = score_percent(submission) if status == "Finished" else None
    results = result_json_items(submission)
    record: dict[str, Any] = {
        "schema_version": 1,
        "task_id": int(submission.get("_id")),
        "submitted_at": parse_platform_time(submission.get("created_date")),
        "version": str(submission.get("name") or ""),
        "status": status,
        "score": percent,
        "source": "frontend_platform_auto",
        "lab_id": lab_id,
        "ci_project_id": str(project_id),
        "ci_job_id": str(submission.get("ci_job_id") or ""),
        "updated_at": parse_platform_time(submission.get("updated") or ""),
        "raw_score": submission.get("score"),
        "boards": submission.get("boards") or [],
        "results": results,
    }
    for item in results:
        feedback = item.get("feedback") or {}
        if not isinstance(feedback, dict):
            continue
        for key in ("elapsed_ms", "crc32", "seed", "groups"):
            if key in feedback and key not in record:
                record[key] = feedback[key]
        if "score_rule" in feedback and "score_rule" not in record:
            record["score_rule"] = feedback["score_rule"]
    return record


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda item: (str(item.get("submitted_at") or ""), int(item.get("task_id") or 0)))
    with path.open("w", encoding="utf-8") as fh:
        for row in ordered:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def upsert_eval_record(path: Path, record: dict[str, Any]) -> None:
    rows = load_jsonl(path)
    replaced = False
    for idx, row in enumerate(rows):
        if int(row.get("task_id", -1)) == int(record["task_id"]):
            rows[idx] = record
            replaced = True
            break
    if not replaced:
        rows.append(record)
    write_jsonl(path, rows)


def refresh_winner_tree(args: argparse.Namespace) -> None:
    cmd = [sys.executable, str(workspace_root() / DEFAULT_WINNER_SCRIPT)]
    if args.backup_best:
        cmd.append("--backup-best")
    sys.stdout.flush()
    subprocess.run(cmd, cwd=workspace_root(), check=True)


def print_submission_summary(submission: dict[str, Any]) -> None:
    percent = score_percent(submission)
    score_text = "" if percent is None else f" score={percent:.2f}"
    print(
        f"submission {submission.get('_id')} version={submission.get('name')} "
        f"state={submission.get('state')}{score_text}"
    )
    for item in result_json_items(submission):
        feedback = item.get("feedback") or {}
        if isinstance(feedback, dict):
            elapsed = feedback.get("elapsed_ms")
            crc32 = feedback.get("crc32")
            seed = feedback.get("seed")
            print(
                "  "
                f"board={item.get('thinpad_id')} testcase={item.get('testcase_id')} "
                f"elapsed_ms={elapsed} crc32={crc32} seed={seed}"
            )


def command_token_status(args: argparse.Namespace) -> int:
    client = make_client(args)
    info = client.gitlab_info()
    token = str(info.get("token") or "")
    print(f"judge user={client.username}")
    print(f"gitlab token present={bool(token)} token={mask_secret(token)}")
    return 0


def command_set_token(args: argparse.Namespace) -> int:
    token = os.environ.get("CICIEC_JUDGE_GITLAB_TOKEN")
    if not token:
        raise SystemExit("error: set CICIEC_JUDGE_GITLAB_TOKEN in the shell")
    client = make_client(args)
    result = client.set_gitlab_token(token)
    if not result.startswith("ok"):
        raise JudgeError(f"change_id failed: {result}")
    info = client.gitlab_info()
    saved = str(info.get("token") or "")
    print(f"gitlab token updated token={mask_secret(saved)}")
    return 0


def command_list_ci(args: argparse.Namespace) -> int:
    client = make_client(args)
    if args.show_projects:
        projects = client.ci_projects().get("projects") or []
        print("projects:")
        for project in projects:
            print(f"  {project.get('id')} {project.get('name')} {project.get('repo')}")
    if args.show_refs:
        refs = client.ci_refs(str(args.project_id))
        print("refs:")
        for ref in refs:
            print(f"  {ref}")
    jobs = collect_ci_jobs(client, str(args.project_id), args.ref, args.ci_pages)
    print(f"jobs project={args.project_id} ref={args.ref}:")
    for job in jobs[: args.limit]:
        artifact = job.get("artifacts_file") or {}
        size = artifact.get("size", "")
        print(
            f"  job={job.get('id')} status={job.get('status')} "
            f"commit={job.get('commit_s') or str(job.get('commit') or '')[:8]} "
            f"name={job.get('name')} artifact_bytes={size}"
        )
    return 0


def command_list_submissions(args: argparse.Namespace) -> int:
    client = make_client(args)
    lab_id = resolve_lab_id(client, args.lab_id)
    info = client.lab_info(lab_id)
    lab = info.get("lab") or {}
    print(f"lab={lab_id} name={lab.get('name')}")
    rows = combined_submissions(client, lab_id, manual_refresh=args.manual_refresh)
    for row in rows[: args.limit]:
        percent = score_percent(row)
        score_text = "" if percent is None else f" score={percent:.2f}"
        print(
            f"  task={row.get('_id')} state={row.get('state')} version={row.get('name')} "
            f"job={row.get('ci_job_id')}{score_text} submitted={parse_platform_time(row.get('created_date'))}"
        )
    return 0


def command_submit(args: argparse.Namespace) -> int:
    client = make_client(args)
    lab_id = resolve_lab_id(client, args.lab_id)
    lab = client.lab_info(lab_id).get("lab") or {}
    job = resolve_ci_job(client, args)
    job_id = str(job.get("id"))
    project_id = str(args.project_id)
    print(
        f"target lab={lab.get('name') or lab_id} project={project_id} "
        f"ref={args.ref} job={job_id} commit={job.get('commit_s')}"
    )

    existing = find_submission_for_job(combined_submissions(client, lab_id, manual_refresh=True), project_id, job_id)
    if existing and not args.force:
        print(f"reusing existing submission {existing.get('_id')} for job {job_id}")
        submission = existing
    else:
        if args.dry_run:
            print("dry run: would POST submit_judge")
            return 0
        result = client.submit_judge(lab_id, project_id, job_id)
        if not result.startswith("ok"):
            raise JudgeError(f"submit_judge failed: {result}")
        print(f"submit_judge: {result}")
        submission = wait_for_submission(
            client,
            lab_id,
            project_id,
            job_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )

    if args.wait and str(submission.get("state")) not in FINAL_STATES:
        submission = wait_for_submission(
            client,
            lab_id,
            project_id,
            job_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )

    print_submission_summary(submission)

    if args.record:
        record = submission_record(submission, lab_id, project_id)
        eval_path = Path(args.eval_jsonl)
        if not eval_path.is_absolute():
            eval_path = workspace_root() / eval_path
        upsert_eval_record(eval_path, record)
        print(f"wrote {eval_path}")
        refresh_winner_tree(args)

    if args.mark_final:
        if str(submission.get("state")) != "Finished":
            raise JudgeError("cannot mark non-Finished submission as final")
        result = client.mark_final(lab_id, int(submission["_id"]))
        if not result.get("success"):
            raise JudgeError(f"mark_final failed: {result.get('message') or result}")
        print(f"marked final submission {submission['_id']}")

    return 0


def command_status(args: argparse.Namespace) -> int:
    client = make_client(args)
    info = client.gitlab_info()
    print(f"judge user={client.username}")
    print(f"gitlab token present={bool(info.get('token'))} token={mask_secret(str(info.get('token') or ''))}")
    lab_id = resolve_lab_id(client, args.lab_id)
    lab_info = client.lab_info(lab_id)
    lab = lab_info.get("lab") or {}
    print(f"stage3 lab={lab_id} name={lab.get('name')}")
    refs = client.ci_refs(str(args.project_id))
    print(f"ref available={args.ref in refs} ref={args.ref}")
    jobs = collect_ci_jobs(client, str(args.project_id), args.ref, 1)
    if jobs:
        latest = jobs[0]
        print(
            f"latest ci job={latest.get('id')} status={latest.get('status')} "
            f"commit={latest.get('commit_s')} artifact={bool(latest.get('artifacts_file'))}"
        )
    rows = combined_submissions(client, lab_id, manual_refresh=False)
    if rows:
        print_submission_summary(rows[0])
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", default=DEFAULT_BASE, help="online judge base URL")


def add_ci_selector_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--ci-pages", type=int, default=3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    sub = parser.add_subparsers(dest="command")

    status = sub.add_parser("status", help="show judge token, lab, CI, and latest submission status")
    add_common_args(status)
    add_ci_selector_args(status)
    status.add_argument("--lab-id")
    status.set_defaults(func=command_status)

    token_status = sub.add_parser("token-status", help="show masked GitLab token stored by the judge platform")
    add_common_args(token_status)
    token_status.set_defaults(func=command_token_status)

    set_token = sub.add_parser("set-token", help="set judge platform GitLab token from CICIEC_JUDGE_GITLAB_TOKEN")
    add_common_args(set_token)
    set_token.set_defaults(func=command_set_token)

    list_ci = sub.add_parser("list-ci", help="list visible CI jobs from the judge platform")
    add_common_args(list_ci)
    add_ci_selector_args(list_ci)
    list_ci.add_argument("--show-projects", action="store_true")
    list_ci.add_argument("--show-refs", action="store_true")
    list_ci.add_argument("--limit", type=int, default=10)
    list_ci.set_defaults(func=command_list_ci)

    list_sub = sub.add_parser("list-submissions", help="list latest judge submissions")
    add_common_args(list_sub)
    list_sub.add_argument("--lab-id")
    list_sub.add_argument("--manual-refresh", action="store_true")
    list_sub.add_argument("--limit", type=int, default=10)
    list_sub.set_defaults(func=command_list_submissions)

    submit = sub.add_parser("submit", help="submit or reuse a CI artifact job for online judging")
    add_common_args(submit)
    add_ci_selector_args(submit)
    submit.add_argument("--lab-id")
    submit.add_argument("--submission-repo", default=str(default_submission_repo()))
    submit.add_argument("--job-id")
    submit.add_argument("--commit", default="current", help="commit SHA/prefix, or 'current' for submission repo HEAD")
    submit.add_argument("--latest-success", action="store_true", help="ignore --commit and use latest successful artifact job")
    submit.add_argument("--allow-non-success", action="store_true", help="allow selecting a non-success CI job")
    submit.add_argument("--force", action="store_true", help="submit even if an existing submission for the job is found")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--wait", action="store_true", help="wait until the submission reaches a final state")
    submit.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    submit.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    submit.add_argument("--record", action="store_true", default=True, help="write ci_data evaluator JSONL and refresh winner tree")
    submit.add_argument("--no-record", action="store_false", dest="record")
    submit.add_argument("--eval-jsonl", default=DEFAULT_EVAL_JSONL)
    submit.add_argument("--backup-best", action="store_true", help="pass --backup-best to update_ciciec_eval_winners.py")
    submit.add_argument("--mark-final", action="store_true", help="mark the finished CI submission as final on the judge platform")
    submit.set_defaults(func=command_submit)

    parser.set_defaults(func=command_status)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if hasattr(args, "base") and not args.base:
            raise JudgeError("set CICIEC_JUDGE_BASE_URL or pass --base")
        if hasattr(args, "project_id") and not args.project_id:
            raise JudgeError("set CICIEC_GITLAB_PROJECT_ID or pass --project-id")
        return int(args.func(args) or 0)
    except JudgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
