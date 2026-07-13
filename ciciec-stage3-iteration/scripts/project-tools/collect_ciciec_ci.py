#!/usr/bin/env python3
"""Collect CICIEC Stage 3 GitLab CI evidence into local data files.

This script is intentionally read-only against GitLab. It expects the access
token in GITLAB_TOKEN and never writes the token to output files.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


DEFAULT_BASE = os.environ.get("CICIEC_GITLAB_API_URL", "")
DEFAULT_PROJECT = os.environ.get("CICIEC_GITLAB_PROJECT_ID", "")
DEFAULT_REF = os.environ.get("CICIEC_CI_REF", os.environ.get("CICIEC_SUBMISSION_REF", "submit/codex"))
DEFAULT_OUT_DIR = "ci_data"
SCHEMA_VERSION = 1
CN_TZ = timezone(timedelta(hours=8))
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def request_bytes(url: str, token: str, attempts: int = 4) -> tuple[int, bytes]:
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code in RETRYABLE_HTTP_STATUS and attempt < attempts:
                time.sleep(min(30, 2**attempt))
                continue
            return exc.code, body
        except urllib.error.URLError as exc:
            if attempt < attempts:
                time.sleep(min(30, 2**attempt))
                continue
            raise RuntimeError(f"request failed for {url}: {exc}") from exc
    raise RuntimeError(f"request failed for {url}")


def request_json(url: str, token: str) -> Any:
    status, body = request_bytes(url, token)
    if status < 200 or status >= 300:
        raise RuntimeError(f"HTTP {status} for {url}: {body[:200]!r}")
    return json.loads(body.decode("utf-8"))


def api_url(base: str, path: str, query: dict[str, str] | None = None) -> str:
    url = base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def parse_gitlab_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S %z")


def first_match(pattern: str, text: str, flags: int = 0) -> re.Match[str] | None:
    return re.search(pattern, text, flags)


def classify_failure(trace: str, job_status: str) -> dict[str, Any]:
    if job_status in {"running", "pending", "created"}:
        return {"class": "pending", "message": "pipeline/job still running"}
    if job_status == "success":
        return {"class": "none", "message": ""}
    if job_status == "canceled":
        return {"class": "canceled", "message": "job canceled"}

    checks: list[tuple[str, str, str, int]] = [
        (
            "missing_linker_script",
            r"No rule to make target '../../bsp/env/separate\.lds'",
            "missing ../../bsp/env/separate.lds",
            0,
        ),
        (
            "sdk_copy_permission",
            r"cp: cannot create regular file '/sdk': Permission denied",
            "optional SDK copy tried to write /sdk",
            0,
        ),
        (
            "linter_missing_define",
            r"HDL lint failed\..*?Define or directive not defined: `([^`\n]+)",
            "HDL lint missing define/directive",
            re.S,
        ),
        (
            "timing_failure",
            r"ERROR: WNS must be positive, got (-?[0-9.]+) ns",
            "timing WNS is not positive",
            0,
        ),
        (
            "vivado_timing_failure",
            r"The design failed to meet the timing requirements",
            "Vivado reports timing requirements not met",
            0,
        ),
        (
            "make_failure",
            r"make: \*\*\*([^\n]+)",
            "make failed",
            0,
        ),
    ]

    dsp_error = first_match(r"ERROR: DSP usage (\d+) exceeds allowed limit 0", trace)
    if dsp_error:
        return {
            "class": "dsp_limit",
            "message": "DSP usage exceeds allowed limit 0",
            "detail": dsp_error.group(0).strip(),
        }

    dsp_used = first_match(r"DSP used: (\d+), allowed: (\d+)", trace)
    if dsp_used and int(dsp_used.group(1)) > int(dsp_used.group(2)):
        return {
            "class": "dsp_limit",
            "message": "DSP usage exceeds allowed limit 0",
            "detail": dsp_used.group(0).strip(),
        }

    for klass, pattern, message, flags in checks:
        match = first_match(pattern, trace, flags)
        if match:
            detail = match.group(0).strip().replace("\r", "")
            return {"class": klass, "message": message, "detail": detail}

    match = first_match(r"ERROR: Job failed: exit code \d+", trace)
    if match:
        return {
            "class": "job_failed",
            "message": "job failed without a more specific classifier",
            "detail": match.group(0),
        }
    return {"class": "unclassified", "message": "no known failure pattern found"}


def parse_trace_metrics(trace: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if "rtl/ is unchanged. Reusing previous Vivado artifacts" in trace:
        metrics["artifact_reuse"] = True
    if "No reusable artifacts found, or rtl/ changed. Running Vivado." in trace:
        metrics["fresh_vivado"] = True
    if "Starting Vivado implementation" in trace:
        metrics["vivado_implementation_started"] = True
    if "Generating bitstream" in trace:
        metrics["bitstream_generation_started"] = True

    dsp = first_match(r"DSP used: (\d+), allowed: (\d+)", trace)
    if dsp:
        metrics["dsp_used_trace"] = int(dsp.group(1))
        metrics["dsp_allowed_trace"] = int(dsp.group(2))

    wns = first_match(r"ERROR: WNS must be positive, got (-?[0-9.]+) ns", trace)
    if wns:
        metrics["wns_error_ns"] = float(wns.group(1))

    return metrics


def parse_timing_summary(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "WNS(ns)" not in line:
            continue
        for candidate in lines[idx + 1 :]:
            fields = candidate.split()
            if not fields or fields[0].startswith("-"):
                continue
            try:
                return {
                    "wns_ns": float(fields[0]),
                    "tns_ns": float(fields[1]),
                    "tns_failing_endpoints": int(fields[2]),
                    "tns_total_endpoints": int(fields[3]),
                    "whs_ns": float(fields[4]),
                    "ths_ns": float(fields[5]),
                }
            except (ValueError, IndexError):
                return {}
    return {}


def parse_dsp_report(text: str) -> dict[str, Any]:
    for line in text.splitlines():
        match = first_match(r"\|\s*DSPs\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)", line)
        if match:
            return {
                "dsp_used": int(match.group(1)),
                "dsp_fixed": int(match.group(2)),
                "dsp_available": int(match.group(3)),
            }
    return {}


def extract_artifact_metrics(artifact_body: bytes, status: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "artifact_http_status": status,
        "artifact_available": status == 200,
        "artifact_bytes": len(artifact_body) if status == 200 else 0,
    }
    if status != 200:
        return result

    try:
        archive = zipfile.ZipFile(io.BytesIO(artifact_body))
    except zipfile.BadZipFile:
        result["artifact_error"] = "bad zip"
        return result

    names = archive.namelist()
    result["artifact_files"] = names
    result["has_bitstream"] = any(name.endswith(".bit") for name in names)
    result["has_timing_summary"] = any(name.endswith("timing_summary.rpt") for name in names)
    result["has_dsp_report"] = any(name.endswith("dsp_utilization.rpt") for name in names)
    result["has_linter_log"] = any(name.endswith("linter.log") for name in names)

    for info in archive.infolist():
        if info.filename.endswith("sdk/software/examples/asm/obj/user-sample.bin"):
            result["user_sample_bin_bytes"] = info.file_size
        elif info.filename == "rtl.sha256":
            result["rtl_sha256"] = archive.read(info).decode("utf-8", "replace").strip()

    for name in names:
        if name.endswith("timing_summary.rpt"):
            text = archive.read(name).decode("utf-8", "replace")
            result.update(parse_timing_summary(text))
            break

    for name in names:
        if name.endswith("dsp_utilization.rpt"):
            text = archive.read(name).decode("utf-8", "replace")
            result.update(parse_dsp_report(text))
            break

    return result


def collect_once(base: str, project: str, ref: str, limit: int, token: str) -> list[dict[str, Any]]:
    pipelines = request_json(
        api_url(
            base,
            f"/projects/{project}/pipelines",
            {"ref": ref, "per_page": str(limit)},
        ),
        token,
    )
    records: list[dict[str, Any]] = []

    for pipeline in pipelines:
        pipeline_id = pipeline["id"]
        jobs = request_json(
            api_url(base, f"/projects/{project}/pipelines/{pipeline_id}/jobs", {"per_page": "50"}),
            token,
        )
        job = next((item for item in jobs if item.get("name") == "bitstream"), jobs[0] if jobs else None)
        commit = (job or {}).get("commit") or {}
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": int(project),
            "ref": pipeline.get("ref"),
            "pipeline_id": pipeline_id,
            "pipeline_iid": pipeline.get("iid"),
            "pipeline_status": pipeline.get("status"),
            "pipeline_source": pipeline.get("source"),
            "pipeline_created_at": pipeline.get("created_at"),
            "pipeline_created_at_cn": parse_gitlab_time(pipeline.get("created_at")),
            "pipeline_updated_at": pipeline.get("updated_at"),
            "pipeline_web_url": pipeline.get("web_url"),
            "sha": pipeline.get("sha"),
            "short_sha": (pipeline.get("sha") or "")[:8],
        }

        if job:
            record.update(
                {
                    "job_id": job.get("id"),
                    "job_name": job.get("name"),
                    "job_stage": job.get("stage"),
                    "job_status": job.get("status"),
                    "job_failure_reason": job.get("failure_reason"),
                    "job_duration_s": job.get("duration"),
                    "job_queued_duration_s": job.get("queued_duration"),
                    "job_created_at": job.get("created_at"),
                    "job_started_at": job.get("started_at"),
                    "job_finished_at": job.get("finished_at"),
                    "job_web_url": job.get("web_url"),
                    "commit_title": commit.get("title") or commit.get("message", "").splitlines()[0],
                }
            )

            trace = ""
            trace_status, trace_body = request_bytes(
                api_url(base, f"/projects/{project}/jobs/{job['id']}/trace"),
                token,
            )
            record["trace_http_status"] = trace_status
            if trace_status == 200:
                trace = trace_body.decode("utf-8", "replace")
                record["trace_bytes"] = len(trace_body)
                record["trace_metrics"] = parse_trace_metrics(trace)
                record["failure"] = classify_failure(trace, str(job.get("status")))
            else:
                record["trace_bytes"] = 0
                record["failure"] = {"class": "trace_unavailable", "message": f"trace HTTP {trace_status}"}

            artifact_status, artifact_body = request_bytes(
                api_url(base, f"/projects/{project}/jobs/{job['id']}/artifacts"),
                token,
            )
            record["artifact_metrics"] = extract_artifact_metrics(artifact_body, artifact_status)
        else:
            record.update(
                {
                    "job_id": None,
                    "job_status": "missing",
                    "commit_title": "",
                    "failure": {"class": "job_missing", "message": "no jobs returned for pipeline"},
                }
            )

        records.append(record)

    return records


def load_existing_jsonl(path: Path) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        records[int(item["pipeline_id"])] = item
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda item: item.get("pipeline_created_at") or "", reverse=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in ordered:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def md_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def format_metrics(record: dict[str, Any]) -> str:
    artifact = record.get("artifact_metrics") or {}
    trace = record.get("trace_metrics") or {}
    parts: list[str] = []
    if trace.get("artifact_reuse"):
        parts.append("reuse")
    if trace.get("fresh_vivado"):
        parts.append("fresh Vivado")
    if "wns_ns" in artifact:
        parts.append(f"WNS {artifact['wns_ns']:+.3f} ns")
    elif "wns_error_ns" in trace:
        parts.append(f"WNS {trace['wns_error_ns']:+.3f} ns")
    if "tns_ns" in artifact:
        parts.append(f"TNS {artifact['tns_ns']:+.3f} ns")
    if "dsp_used" in artifact:
        parts.append(f"DSP {artifact['dsp_used']}")
    elif "dsp_used_trace" in trace:
        parts.append(f"DSP {trace['dsp_used_trace']}")
    if "user_sample_bin_bytes" in artifact:
        parts.append(f"bin {artifact['user_sample_bin_bytes']} B")
    if artifact.get("has_bitstream"):
        parts.append("bitstream")
    return "; ".join(parts)


def write_summary(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "# CICIEC Stage 3 CI Auto Summary",
        "",
        f"Generated: {now}",
        "",
        "This file is generated by `tools/collect_ciciec_ci.py`. It contains no access token.",
        "",
        "| Pipeline | Job | Commit | Status | Duration | Metrics | Failure | URL |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for record in sorted(records, key=lambda item: item.get("pipeline_created_at") or "", reverse=True):
        failure = record.get("failure") or {}
        duration = record.get("job_duration_s")
        duration_text = "" if duration is None else f"{float(duration):.2f}s"
        commit = f"`{record.get('short_sha', '')}` {record.get('commit_title', '')}".strip()
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(record.get("pipeline_id")),
                    md_cell(record.get("job_id")),
                    md_cell(commit),
                    md_cell(record.get("job_status") or record.get("pipeline_status")),
                    md_cell(duration_text),
                    md_cell(format_metrics(record)),
                    md_cell(f"{failure.get('class', '')}: {failure.get('message', '')}".strip(": ")),
                    md_cell(record.get("pipeline_web_url")),
                ]
            )
            + " |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def has_incomplete_latest(records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    latest = max(records, key=lambda item: item.get("pipeline_created_at") or "")
    return str(latest.get("pipeline_status")) in {"running", "pending", "created"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--wait", action="store_true", help="poll until the latest pipeline leaves running/pending")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        print("error: set GITLAB_TOKEN in the shell; the token is not stored by this script", file=sys.stderr)
        return 2
    if not args.base:
        print("error: set CICIEC_GITLAB_API_URL or pass --base", file=sys.stderr)
        return 2
    if not args.project:
        print("error: set CICIEC_GITLAB_PROJECT_ID or pass --project", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    jsonl_path = out_dir / "ciciec_stage3_ci_runs.jsonl"
    summary_path = out_dir / "ciciec_stage3_ci_latest.md"

    start = time.monotonic()
    while True:
        try:
            new_records = collect_once(args.base, args.project, args.ref, args.limit, token)
        except RuntimeError as exc:
            if not args.wait or time.monotonic() - start >= args.timeout_seconds:
                raise
            print(f"warning: collection attempt failed: {exc}", file=sys.stderr)
            time.sleep(args.poll_seconds)
            continue
        merged = load_existing_jsonl(jsonl_path)
        for record in new_records:
            merged[int(record["pipeline_id"])] = record
        records = list(merged.values())
        write_jsonl(jsonl_path, records)
        write_summary(summary_path, records)

        latest = max(new_records, key=lambda item: item.get("pipeline_created_at") or "", default=None)
        if latest:
            print(
                f"collected {len(new_records)} pipelines; latest pipeline "
                f"{latest['pipeline_id']} status={latest.get('pipeline_status')}"
            )
        else:
            print("collected 0 pipelines")

        if not args.wait or not has_incomplete_latest(new_records):
            break
        if time.monotonic() - start >= args.timeout_seconds:
            print("timeout while waiting; wrote latest running state", file=sys.stderr)
            break
        time.sleep(args.poll_seconds)

    print(f"wrote {jsonl_path}")
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
