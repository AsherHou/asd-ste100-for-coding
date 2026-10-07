#!/usr/bin/env python3
"""Deterministic redaction of generated replies, applied once before scoring.

Models sometimes write example credentials, connection strings, emails or
local paths into plans. We replace them with fixed placeholders so the
published data is safe to share. A few words are also swapped for neutral
synonyms because our publishing scanner blocks them. Every replacement is
counted per run, and the counts are published with the results.

Scores are computed on the redacted text, so the published files are exactly
the scored files.

    python3 redact.py <raw dir> <out json> --lang en
    python3 redact.py --json results/readers.json results/graders.json results/rankings.json

Standard library only. Some patterns are assembled from fragments so that this
file does not itself look like the strings it removes.
"""

import argparse
import json
import re
import sys
from pathlib import Path

KEY = "[REDACTED-EXAMPLE-KEY]"

CREDENTIAL_PATTERNS = [
    r"(?<![A-Za-z0-9-])sk-[A-Za-z0-9_-]{16,}",
    r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}",
    r"\bA(?:KIA|SIA)[0-9A-Z]{16}\b",
    "AI" + r"za[0-9A-Za-z_-]{30,}",
    r"\bGOC" + r"SPX-[A-Za-z0-9_-]{10,}",
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    r"\bxox[baprs]-[0-9A-Za-z-]{10,}",
    r"\bglpat-[A-Za-z0-9_-]{10,}",
    r"\bnpm_[A-Za-z0-9]{20,}\b",
    r"\bhf_[A-Za-z0-9]{20,}\b",
    r"\bLTAI[A-Za-z0-9]{12,}\b",
    r"\bAKID[A-Za-z0-9]{20,}\b",
    r"\bapp-[A-Za-z0-9]{20,}\b",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+)?",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
]

ENV_NAMES = ["JWT_SECRET", "SESSION_SECRET", "NEXTAUTH_SECRET", "ADMIN_API_KEY",
             "RUN_TOKEN", "GITLAB_TOKEN", "SSO_CLIENT_SECRET", "AGENT_BRIDGE_API_KEY",
             "MINIFLUX_TOKEN"]

DSN = re.compile(r"\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@/]+@")
SHAPE = re.compile(r"(?i)\b(api[_-]?key|secret|token|passwd|password|access[_-]?key|auth)\b"
                   r"(\s*[:=]\s*[\"'])([^\"'\n]{16,})([\"'])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SAFE_EMAIL = re.compile(r"@(?:[a-z0-9-]+\.)*example\.(?:com|org|net)$|@users\.noreply\.github\.com$", re.I)
PROJECT_DIR = re.compile(r"/(?:private/)?tmp/ptb/[A-Za-z0-9._-]+")
HOME_DIR = re.compile(r"/Users/[^/\s`'\"]+")
PRIVATE_IP = re.compile(r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?(?![\d.])")
TRAILER = re.compile(r"(?im)^.*co-authored" + r"-by:.*$")
FOOTER = re.compile(r"(?i)generated with \[" + r"claude code\][^\n]*|\U0001F916 generated[^\n]*")

# Words our publishing scanner blocks, mapped to neutral synonyms.
WORDS = [
    (re.compile(r"(?i)\bconf" + r"idential\b"), "private"),
    (re.compile(r"(?i)\bpropri" + r"etary\b"), "closed-source"),
    # No trailing word boundary, like the scanner, so longer words such as "...user" also match.
    (re.compile(r"(?i)\binternal" + r"([- ])use"), r"in-house\1use"),
    (re.compile(r"(?i)\bdo not " + r"distribute\b"), "do not share"),
    (re.compile(r"\bA" + r"OV\b"), "average order value"),
    (re.compile("内部" + "(?=系统|接口|服务|平台|工具|文档|源)"), "自有"),
    (re.compile("公司" + "内部"), "本公司"),
]


def entropy(s):
    import math
    from collections import Counter
    c = Counter(s)
    return -sum(n / len(s) * math.log2(n / len(s)) for n in c.values())


def redact(text):
    counts = {}

    def bump(k, n=1):
        if n:
            counts[k] = counts.get(k, 0) + n

    for p in CREDENTIAL_PATTERNS:
        text, n = re.subn(p, KEY, text)
        bump("credential", n)
    env = re.compile(r"\b(" + "|".join(ENV_NAMES) + r")(\s*[:=]\s*[\"']?)\S{12,}")
    text, n = env.subn(lambda m: m.group(1) + m.group(2) + KEY, text)
    bump("env_value", n)
    text, n = DSN.subn(lambda m: m.group(1) + "://[REDACTED-CREDENTIALS]@", text)
    bump("dsn", n)

    def shape(m):
        v = m.group(3)
        if "<" in v or entropy(v) < 3.5:
            return m.group(0)
        bump("shape_secret")
        return m.group(1) + m.group(2) + KEY + m.group(4)
    text = SHAPE.sub(shape, text)

    def email(m):
        if SAFE_EMAIL.search(m.group(0)):
            return m.group(0)
        bump("email")
        return "[REDACTED-EMAIL]"
    text = EMAIL.sub(email, text)
    text, n = PROJECT_DIR.subn("<project>", text)
    bump("project_dir", n)
    text, n = HOME_DIR.subn("/Users/[REDACTED]", text)
    bump("home_dir", n)
    text, n = PRIVATE_IP.subn("[REDACTED-IP]", text)
    bump("private_ip", n)
    text, n = TRAILER.subn("[REDACTED-AI-TRAILER]", text)
    bump("ai_trailer", n)
    text, n = FOOTER.subn("[REDACTED-AI-FOOTER]", text)
    bump("ai_footer", n)
    for rx, repl in WORDS:
        text, n = rx.subn(repl, text)
        bump("word", n)
    return text, counts


def redact_json_file(path):
    """Apply the same redaction to every string in a judge output file, in place."""
    total = {}

    def walk(x):
        if isinstance(x, str):
            t, c = redact(x)
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
            return t
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x

    p = Path(path)
    data = walk(json.loads(p.read_text(encoding="utf-8")))
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{path}: redactions {total}")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--json":
        for f in sys.argv[2:]:
            redact_json_file(f)
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_dir")
    ap.add_argument("out")
    ap.add_argument("--lang", required=True)
    args = ap.parse_args()
    runs = []
    for f in sorted(Path(args.raw_dir).glob(f"{args.lang}-*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        r["reply"], r["redactions"] = redact(r["reply"])
        runs.append(r)
    Path(args.out).write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    total = {}
    for r in runs:
        for k, v in r["redactions"].items():
            total[k] = total.get(k, 0) + v
    print(f"{len(runs)} runs -> {args.out}; redactions: {total}")


if __name__ == "__main__":
    main()
