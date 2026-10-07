#!/usr/bin/env python3
"""Exploratory analysis, written after we saw the pre-registered results.

These numbers are not part of the pre-registered test in README.md. They look
at plan-first's own design goal: ask the human fewer questions, decide the
rest safely, and keep every decision visible.

    python3 -B explore.py --results results --tasks tasks/tasks.json

It also counts technical noise in what the approver reads: inline code spans
(identifiers, commands, config keys in backticks) and file paths per 100 words.
It also reruns the primary metric with one fix: readers sometimes wrapped
their quotes in quotation marks, which the pre-registered matcher did not
strip. The fix applies to every arm.
Standard library only; reuses the helpers in score.py.
"""

import argparse
import collections
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("score", HERE / "score.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

QUOTES = r"[\s\"“”「」'‘’]+"
PATH = re.compile(r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+|\b[\w-]+\.(?:py|ts|js|tsx|jsx|rb|go|sql|yml|yaml|json|toml|md|rake|sh|csv|html|css)\b")


def technical_density(text, lang):
    """Inline code spans and file paths per 100 words, outside code blocks."""
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    words = max(1, S.count(text, lang))
    return (len(re.findall(r"`[^`\n]+`", prose)) * 100 / words,
            len(PATH.findall(prose)) * 100 / words)


def quote_in_stripped(quote, text):
    q = re.sub(rf"^{QUOTES}|{QUOTES}$", "", quote or "")
    return S.quote_in(q, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--tasks", required=True)
    args = ap.parse_args()
    R = Path(args.results)
    tasks = {t["id"]: t for t in json.loads(Path(args.tasks).read_text(encoding="utf-8"))}
    graders = {g["nid"]: g for g in json.loads((R / "graders.json").read_text(encoding="utf-8"))}
    readers = {r["nid"]: r for r in json.loads((R / "readers.json").read_text(encoding="utf-8"))}
    out = {}
    for lang in ("en", "zh"):
        f = R / f"generations.{lang}.json"
        if not f.exists():
            continue
        handling = collections.defaultdict(collections.Counter)
        words = collections.defaultdict(list)
        recall = collections.defaultdict(dict)
        for run in json.loads(f.read_text(encoding="utf-8")):
            req = tasks[run["task"]]["key"]["required_decisions"]
            if not req:
                continue
            reader, agent, whole, flags = S.split_views(run)
            cut, _ = S.cut(reader, lang)
            nid = S.neutral_id(run["run_id"])
            g, rd = graders[nid], readers[nid]
            arm = run["arm"]
            words[arm].append(S.count(reader, lang))
            c = handling[arm]
            c["plans"] += 1
            c["questions"] += len(g.get("posed_decisions", []))
            code, paths = technical_density(reader, lang)
            c["inline_code"] += code
            c["paths"] += paths
            dec = {d["id"]: d for d in g.get("decisions", [])}
            items = [(a.get("question_id", ""), it) for a in rd.get("answers", []) for it in a.get("items", [])]
            caught = 0
            for d in req:
                v = dec.get(d["id"], {})
                c["required"] += 1
                if v.get("recommendation_unsafe"):
                    c["decided_unsafely"] += 1
                elif v.get("asked_explicitly"):
                    c["asked"] += 1
                elif v.get("in_doc"):
                    c["decided_safely_and_stated"] += 1
                else:
                    c["not_visible"] += 1
                ri = v.get("reader_item")
                caught += bool(v.get("reader_caught")) and isinstance(ri, int) and 0 <= ri < len(items) \
                    and items[ri][0].upper().startswith(("Q2", "Q8")) and quote_in_stripped(items[ri][1].get("quote"), cut)
            recall[run["task"]][arm] = caught / len(req)
        res = {}
        for arm, c in sorted(handling.items()):
            r = c["required"]
            res[arm] = {
                "questions_per_plan": c["questions"] / c["plans"],
                "asked": c["asked"] / r,
                "decided_safely_and_stated": c["decided_safely_and_stated"] / r,
                "decided_unsafely": c["decided_unsafely"] / r,
                "not_visible": c["not_visible"] / r,
                "words_read": sum(words[arm]) / len(words[arm]),
                "inline_code_per_100_words": c["inline_code"] / c["plans"],
                "file_paths_per_100_words": c["paths"] / c["plans"],
                "reader_recall_quote_fixed": sum(recall[t][arm] for t in recall) / len(recall),
            }
        out[lang] = res
        print(f"[{lang}] arm: questions/plan | asked | decided safely and stated | decided unsafely | not visible | words read | reader recall (quote fix) | inline code /100w | paths /100w")
        for arm, x in res.items():
            print(f"  {arm}: {x['questions_per_plan']:.1f} | {x['asked']:.0%} | {x['decided_safely_and_stated']:.0%} | "
                  f"{x['decided_unsafely']:.0%} | {x['not_visible']:.0%} | {x['words_read']:.0f} | {x['reader_recall_quote_fixed']:.3f} | "
                  f"{x['inline_code_per_100_words']:.2f} | {x['file_paths_per_100_words']:.2f}")
    (R / "exploratory.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
