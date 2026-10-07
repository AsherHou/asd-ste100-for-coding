#!/usr/bin/env python3
"""Generate benchmark outputs with the Claude Code CLI.

Each run gets a fresh, empty project directory. The arm's rules go into that
project's CLAUDE.md, which is how people use these rules in practice. File
tools are turned off, so the agent returns any file it would write inline,
after a line "=== FILE: <path> ===".

    python3 generate.py --tasks tasks/tasks.json --arms arms --lang en \
        --models claude-opus-5-5,claude-sonnet-5-5 --out results/raw \
        --workdir /tmp/ptb --jobs 6

Requires a logged-in `claude` CLI. Standard library only.
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ARMS = ["A", "B", "C", "D", "E"]

WRAPPER = {
    "en": (
        "Context about the repository (you cannot open files in this session, "
        "so this summary is all you have):\n\n{brief}\n\n---\n\nMy request: {request}\n\n"
        "(File tools are turned off in this session. Reply with exactly what you "
        "would send me now. If you would create or edit any files at this point, "
        "put each file's full content in your reply, starting on its own line with: "
        "=== FILE: <relative path> ===)"
    ),
    "zh": (
        "仓库背景（本次会话里你打不开文件，下面的说明就是你掌握的全部信息）：\n\n{brief}\n\n---\n\n我的请求：{request}\n\n"
        "（本次会话关闭了文件工具。请直接回复你此刻会发给我的内容。如果你此刻会创建或修改文件，"
        "把每个文件的完整内容放进回复，每个文件另起一行，以这一行开头：=== FILE: <相对路径> ===）"
    ),
}


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_arm(arms_dir, arm, lang, external_dir):
    """Return {relative path: content} for the files that make up an arm's project.

    A source is inline text ({"text": ...}), a path relative to the arms
    directory, or "external:<name>" for a file we may not redistribute; fetch
    that one yourself (see arms/C.json) and pass --external.
    """
    spec = json.loads((arms_dir / f"{arm}.json").read_text(encoding="utf-8"))
    files = {}
    for rel, src in spec.get("files", {}).get(lang, spec.get("files", {}).get("*", {})).items():
        if isinstance(src, dict) and "text" in src:
            files[rel] = src["text"]
        else:
            if src.startswith("external:"):
                p = Path(external_dir) / src.split(":", 1)[1]
            else:
                p = (arms_dir / src).resolve()
            text = p.read_text(encoding="utf-8")
            want = spec.get("sha256", {}).get(src)
            if want and sha256(text) != want:
                sys.exit(f"arm {arm}: {src} sha256 mismatch (expected {want})")
            files[rel] = text
    return files


def run_one(job, args):
    run_id = job["run_id"]
    out_path = Path(args.out) / f"{run_id}.json"
    if out_path.exists() and not args.force:
        return run_id, "skip"
    proj = Path(args.workdir) / run_id
    if proj.exists():
        shutil.rmtree(proj)
    proj.mkdir(parents=True)
    for rel, text in job["files"].items():
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    # The briefs describe a git repository, so each project is one: the arm's
    # files in a single initial commit on main, with a clean working tree.
    git = ["git", "-C", str(proj), "-c", "user.name=Bench", "-c", "user.email=bench@example.com"]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "Initial commit"], check=True)

    cmd = ["claude", "-p", "--tools", "", "--setting-sources", "project", "--strict-mcp-config",
           "--output-format", "json", "--model", job["model"]]
    # A minimal environment: no inherited agent or editor variables, no auto memory.
    env = {k: os.environ[k] for k in ("HOME", "USER", "LOGNAME", "PATH", "LANG", "TERM") if k in os.environ}
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    record = None
    for attempt in range(1, 4):
        t0 = time.time()
        p = subprocess.run(cmd, input=job["prompt"], cwd=proj, env=env, capture_output=True, text=True)
        try:
            data = json.loads(p.stdout)
        except json.JSONDecodeError:
            data = {"is_error": True, "result": p.stdout[-2000:], "stderr": p.stderr[-2000:]}
        if "Not logged in" in str(data.get("result", "")):
            sys.exit("claude CLI is not logged in. Run `claude` and then /login.")
        record = {
            "run_id": run_id, "task": job["task"], "arm": job["arm"], "lang": job["lang"],
            "model": job["model"], "attempt": attempt,
            "prompt_sha256": sha256(job["prompt"]),
            "project_files_sha256": {k: sha256(v) for k, v in job["files"].items()},
            "reply": data.get("result", ""),
            "is_error": bool(data.get("is_error")),
            "output_tokens": (data.get("usage") or {}).get("output_tokens"),
            "input_tokens": (data.get("usage") or {}).get("input_tokens"),
            "duration_ms": data.get("duration_ms") or int((time.time() - t0) * 1000),
            "total_cost_usd": data.get("total_cost_usd"),
            "stop_reason": data.get("stop_reason"),
        }
        # Retry only on API or transport errors, the same way for every arm.
        if not record["is_error"] and record["reply"]:
            break
        time.sleep(10 * attempt)
    shutil.rmtree(proj, ignore_errors=True)
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_id, "error" if record["is_error"] else "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--arms", required=True)
    ap.add_argument("--lang", choices=["en", "zh"], required=True)
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", default="/tmp/ptb")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--only-tasks", default="")
    ap.add_argument("--only-arms", default="")
    ap.add_argument("--external", default="arms/external")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    arms_dir = Path(args.arms)
    only_t = set(filter(None, args.only_tasks.split(",")))
    only_a = set(filter(None, args.only_arms.split(","))) or set(ARMS)
    Path(args.out).mkdir(parents=True, exist_ok=True)

    jobs = []
    for t in tasks:
        if only_t and t["id"] not in only_t:
            continue
        brief = t["brief"] if args.lang == "en" else t["brief_zh"]
        request = t["request"] if args.lang == "en" else t["request_zh"]
        prompt = WRAPPER[args.lang].format(brief=brief.strip(), request=request.strip())
        for arm in ARMS:
            if arm not in only_a:
                continue
            files = load_arm(arms_dir, arm, args.lang, args.external)
            for model in args.models.split(","):
                short = model.split("-")[1] if "-" in model else model
                jobs.append({
                    "run_id": f"{args.lang}-{t['id']}-{arm}-{short}",
                    "task": t["id"], "arm": arm, "lang": args.lang, "model": model,
                    "prompt": prompt, "files": files,
                })

    print(f"{len(jobs)} runs, {args.jobs} in parallel", flush=True)
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for run_id, status in ex.map(lambda j: run_one(j, args), jobs):
            print(f"{status:5} {run_id}", flush=True)


if __name__ == "__main__":
    main()
