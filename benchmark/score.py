#!/usr/bin/env python3
"""Score the plan-first benchmark. Standard library only.

    python3 -B score.py views  --gen results/generations.en.json --out <dir>
    python3 -B score.py score  --results results --tasks tasks/tasks.json

`views` splits every reply into what the human reads and what the agent works
from, applies the reading budget, and writes one file per view under a neutral
id, so readers and graders cannot see which arm wrote it.

`score` combines generations, reader answers, grader verdicts and rankings
into results/summary.json and prints the tables used in the README.
The analysis plan is fixed in benchmark/README.md before any generation.
"""

import argparse
import hashlib
import itertools
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ARMS = ["A", "B", "C", "D", "E"]
COMPARATORS = ["A", "B", "C", "E"]
SALT = "plan-first-benchmark-v1"

# Reading budget: about 3 minutes of reading.
BUDGET = {"en": 650, "zh": 1100}
CUT_MARK = {"en": "\n\n[cut: the reader ran out of time here]", "zh": "\n\n[截断：读者的时间到了]"}

FILE_RE = re.compile(r"^=== FILE: (.+?) ===\s*$", re.M)
CJK = r"㐀-䶿一-鿿豈-﫿"
UNIT_RE = re.compile(rf"[{CJK}]|[A-Za-z0-9][A-Za-z0-9_.'/+-]*")


# ---------------------------------------------------------------- text helpers
def units(text, lang):
    """Words for English; for Chinese, each CJK character and each Latin word or number."""
    if lang == "en":
        return re.findall(r"\S+", text)
    return UNIT_RE.findall(text)


def count(text, lang):
    return len(units(text, lang))


def cut(text, lang):
    """Keep the first BUDGET units of text, keeping the original formatting."""
    limit = BUDGET[lang]
    rx = re.compile(r"\S+") if lang == "en" else UNIT_RE
    for i, m in enumerate(rx.finditer(text)):
        if i == limit:
            return text[:m.start()].rstrip() + CUT_MARK[lang], True
    return text, False


def norm(s):
    return re.sub(r"[\s*_`>#|-]+", " ", s).strip().lower()


def quote_in(quote, text):
    q = norm(quote or "")
    if len(q) < 4:
        return False
    return q in norm(text)


def sentences(text, lang):
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    out = []
    for line in body.splitlines():
        line = re.sub(r"^\s*(#+|[-*+]|\d+[.)]|>)\s*", "", line).strip()
        if not line or line.startswith("|"):
            continue
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", line) if lang == "en" \
            else re.split(r"(?<=[。！？；])", line)
        out += [p.strip() for p in parts if p.strip()]
    return out


# ---------------------------------------------------------------- reply parsing
def parse_reply(reply):
    """-> (text outside file blocks, [(path, content), ...])"""
    marks = list(FILE_RE.finditer(reply))
    if not marks:
        return reply.strip(), []
    pre = reply[:marks[0].start()].strip()
    files = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(reply)
        body = reply[m.end():end].strip("\n")
        body = re.sub(r"^```[a-zA-Z]*\n(.*)\n```\s*$", r"\1", body.strip(), flags=re.S)
        files.append((m.group(1).strip(), body))
    return pre, files


def split_views(run):
    """Fixed rule for what the human reads and what the agent works from."""
    pre, files = parse_reply(run["reply"])
    whole = run["reply"].strip()
    arm = run["arm"]
    flags = {"has_file_blocks": bool(files)}
    if arm == "D":
        human = [(p, c) for p, c in files if "docs/human/" in p]
        plan = [(p, c) for p, c in files if "docs/plan/" in p]
        flags["has_human_doc"] = bool(human)
        flags["has_plan_doc"] = bool(plan)
        if human:
            reader = "\n\n".join([pre] + [c for _, c in human]).strip()
            agent = "\n\n".join(c for _, c in plan) if plan else whole
        else:
            reader, agent = whole, whole
    elif arm == "E":
        summ = [(p, c) for p, c in files if "summary" in p.lower()]
        rest = [(p, c) for p, c in files if "summary" not in p.lower()]
        flags["has_summary_file"] = bool(summ)
        if summ:
            reader = "\n\n".join([pre] + [c for _, c in summ]).strip()
            agent = "\n\n".join([pre] + [c for _, c in rest]).strip() or whole
        else:
            reader, agent = whole, whole
    else:
        reader, agent = whole, whole
    return reader, agent, whole, flags


def neutral_id(run_id):
    return hashlib.sha256((SALT + run_id).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- plan-first compliance
LABELS = {
    "zh": {
        "headings": ["## 这次要做什么", "## 需要你决定的事", "## 影响面"],
        "optional_heading": "## 需要你做的事",
        "not_doing": "不做：", "status": "状态：",
        "tags": ["能回退", "难回退"], "hard": "难回退",
        "recommended": "推荐：", "cost": "代价：",
        "closing": "全部按推荐", "nothing": "无需决定",
        "impact": ["会改：", "新增：", "删除：", "对外行为："],
        "time": "预计时间：",
        "length": (300, 800, 1500), "sentence_max": 40,
        "vague": ["相关", "进行", "实现", "优化", "赋能", "闭环"],
        "plan_sections": ["状态", "目标", "背景", "方案", "改动清单", "步骤", "风险", "不做", "待用户决定", "需要用户做", "变更记录", "执行记录"],
    },
    # Filled from the frozen English edition (references/en/plan-first.md).
    "en": {
        "headings": ["## What this does", "## Decisions for you", "## Impact"],
        "optional_heading": "## What you need to do",
        "not_doing": "Not doing:", "status": "Status:",
        "tags": ["can undo", "hard to undo"], "hard": "hard to undo",
        "recommended": "Recommended:", "cost": "Cost:",
        "closing": "To accept all recommendations", "nothing": "Nothing to decide",
        "impact": ["Changes:", "Adds:", "Removes:", "Visible behavior:"],
        "time": "Estimated time:",
        "length": (200, 500, 900), "sentence_max": 25,
        "vague": ["related", "relevant", "perform", "conduct", "optimize", "leverage", "empower",
                  "enhance", "robust", "seamless", "streamline", "facilitate", "end-to-end", "closed loop"],
        "plan_sections": ["status", "goal", "background", "approach", "change list", "steps", "risk", "not doing",
                          "decision", "user", "change log", "execution log"],
    },
}


def compliance(run):
    """Mechanical checks of plan-first's rules on one D output. None = not applicable."""
    lang = run["lang"]
    L = LABELS[lang]
    pre, files = parse_reply(run["reply"])
    human = [(p, c) for p, c in files if "docs/human/" in p]
    plan = [(p, c) for p, c in files if "docs/plan/" in p]
    r = {"human_doc": bool(human), "plan_doc": bool(plan)}
    if not human:
        return r
    hp, h = human[0]
    pp, pl = plan[0] if plan else ("", "")
    name_ok = re.search(r"/(\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md)$", hp)
    r["dated_name"] = bool(name_ok)
    r["same_name"] = bool(plan) and Path(hp).name == Path(pp).name
    r["cross_links"] = bool(plan) and Path(pp).name in h and Path(hp).name in pl
    r["status_line"] = L["status"] in h
    pos = [h.find(x) for x in L["headings"]]
    r["fixed_headings"] = all(p >= 0 for p in pos) and pos == sorted(pos)
    r["not_doing_line"] = L["not_doing"] in h
    sec = h[h.find(L["headings"][1]):h.find(L["headings"][2])] if r["fixed_headings"] else ""
    items = re.findall(r"^\s*\d+\.\s.*$", sec, re.M)
    if L["nothing"] in sec and not items:
        r["decisions_format"] = True
    elif items:
        tagged = all(any(t in it for t in L["tags"]) for it in items)
        rec = sec.count(L["recommended"]) >= len(items)
        hard = sum(1 for it in items if L["hard"] in it)
        r["decisions_format"] = tagged and rec and sec.count(L["cost"]) >= hard
        r["decisions_closing"] = L["closing"] in sec
    else:
        r["decisions_format"] = False
    r["impact_lines"] = all(x in h for x in L["impact"])
    lines = [x for x in h.strip().splitlines() if x.strip()]
    r["time_line_last"] = bool(lines) and lines[-1].strip().startswith(L["time"])
    r["no_tables_html_code"] = not re.search(r"^\s*\|.*\|\s*$|<[a-zA-Z][^>]*>|```", h, re.M)
    bold = re.findall(r"\*\*(.+?)\*\*", h)
    bold_ok = 0
    for b in bold:
        line = next((x for x in h.splitlines() if f"**{b}**" in x), "")
        if re.match(r"^\s*\d+\.\s+\*\*", line):
            bold_ok += 1
    r["bold_only_features_and_questions"] = bold_ok == len(bold)
    lo, hi, mx = L["length"]
    n = count(h, lang)
    r["length_units"] = n
    r["length_in_range"] = lo <= n <= hi
    r["length_under_max"] = n <= mx
    sents = sentences(h, lang)
    over = [s for s in sents if count(s, lang) > L["sentence_max"]]
    r["sentences"] = len(sents)
    r["sentence_over_limit_share"] = round(len(over) / len(sents), 3) if sents else 0.0
    if lang == "en":
        r["vague_words_found"] = [w for w in L["vague"] if re.search(rf"\b{re.escape(w)}\b", h, re.I)]
    else:
        r["vague_words_found"] = [w for w in L["vague"] if w in h]
    # A paragraph is a run of plain text lines; headings, list items, quotes and blank lines end it.
    paras, cur = [], []
    for line in h.splitlines():
        if not line.strip() or re.match(r"^\s*(#|[-*+]\s|\d+[.)]\s|>)", line):
            if cur:
                paras.append(" ".join(cur))
            cur = []
        else:
            cur.append(line.strip())
    if cur:
        paras.append(" ".join(cur))
    r["paragraphs_over_4_sentences"] = sum(1 for p in paras if len(sentences(p, lang)) > 4)
    if plan:
        lp = pl.lower()
        r["plan_sections_found"] = sum(1 for s in L["plan_sections"] if s in lp)
    return r


# ---------------------------------------------------------------- statistics
def rank_abs(diffs):
    order = sorted(range(len(diffs)), key=lambda i: abs(diffs[i]))
    ranks = [0.0] * len(diffs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and abs(diffs[order[j + 1]]) == abs(diffs[order[i]]):
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def wilcoxon_exact(diffs):
    """Exact Wilcoxon signed-rank test. Zero differences are dropped.
    Returns (n_used, W_plus, p_one_sided_greater, p_two_sided)."""
    d = [x for x in diffs if abs(x) > 1e-12]
    n = len(d)
    if n == 0:
        return 0, 0.0, 1.0, 1.0
    ranks = rank_abs(d)
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    total = 0
    ge = 0
    le = 0
    for signs in itertools.product((0, 1), repeat=n):
        w = sum(r for r, s in zip(ranks, signs) if s)
        total += 1
        ge += w >= w_plus - 1e-9
        le += w <= w_plus + 1e-9
    p_one = ge / total
    p_two = min(1.0, 2 * min(ge, le) / total)
    return n, w_plus, p_one, p_two


def holm(pvals):
    """pvals: {name: p} -> {name: adjusted p}"""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return adj


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- commands
def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(obj, path):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_views(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for gen in args.gen:
        for run in load(gen):
            reader, agent, whole, flags = split_views(run)
            lang = run["lang"]
            reader_cut, was_cut = cut(reader, lang)
            nid = neutral_id(run["run_id"])
            for kind, text in (("reader_cut", reader_cut), ("reader_full", reader), ("agent", agent)):
                (out / f"{nid}.{kind}.md").write_text(text, encoding="utf-8")
            index.append({
                "run_id": run["run_id"], "nid": nid, "task": run["task"], "arm": run["arm"],
                "lang": lang, "model": run["model"], "was_cut": was_cut,
                "units_read": count(reader, lang), "units_total": count(whole, lang), **flags,
            })
    dump(index, out / "index.json")
    print(f"{len(index)} runs -> {out}")


def cmd_score(args):
    R = Path(args.results)
    tasks = {t["id"]: t for t in load(args.tasks)}
    gens = []
    for f in sorted(R.glob("generations.*.json")):
        gens += load(f)
    readers = {x["nid"]: x for x in load(R / "readers.json")}
    graders = {x["nid"]: x for x in load(R / "graders.json")}
    rankings = load(R / "rankings.json") if (R / "rankings.json").exists() else []

    rows = []
    for run in gens:
        lang = run["lang"]
        reader_full, agent, whole, flags = split_views(run)
        reader_cut, was_cut = cut(reader_full, lang)
        nid = neutral_id(run["run_id"])
        key = tasks[run["task"]]["key"]
        g = graders.get(nid) or {}
        rd = readers.get(nid) or {}
        # Flattened reader items, in answer order; graders refer to them by index.
        items = [(a.get("question_id", ""), it) for a in rd.get("answers", []) for it in a.get("items", [])]

        req = key["required_decisions"]
        dec = {d["id"]: d for d in g.get("decisions", [])}
        caught = in_doc = buried = hidden = 0
        for d in req:
            v = dec.get(d["id"], {})
            ri = v.get("reader_item")
            # Credit only when the matching answer comes from the decisions or verdict question,
            # and its quote really appears in what the reader saw.
            q_ok = (isinstance(ri, int) and 0 <= ri < len(items)
                    and items[ri][0].upper().startswith(("Q2", "Q8"))
                    and quote_in(items[ri][1].get("quote"), reader_cut))
            c = bool(v.get("reader_caught")) and q_ok
            i = bool(v.get("in_doc")) and quote_in(v.get("doc_quote"), reader_full)
            caught += c
            in_doc += i
            buried += i and not c
            hidden += v.get("hidden_in_agent_plan") == "yes" and not i
        posed = g.get("posed_decisions", [])
        good = sum(1 for p in posed if p.get("class") in ("required", "optional", "legit_other"))
        trivial = sum(1 for p in posed if p.get("class") in ("should_not_ask", "trivial_other"))
        unsafe = sum(1 for v in dec.values() if v.get("recommendation_unsafe"))
        rev_stated = [v.get("reversibility") for v in dec.values() if v.get("reversibility") in ("correct", "wrong")]
        irreversible_missed = any((not d["reversible"]) and not (dec.get(d["id"], {}).get("reader_caught")) for d in req)

        def recall(listname, kind):
            ks = key[listname]
            got = {x["id"]: x for x in g.get(kind, [])}
            hit = sum(1 for k in ks if got.get(k["id"], {}).get("in_doc") and quote_in(got[k["id"]].get("quote"), reader_full))
            return hit / len(ks) if ks else None

        risks = g.get("risks", [])
        nr = len(key["execution_risks"]) or None
        traps = g.get("scope_traps", [])
        facts = g.get("key_facts", [])
        sents = sentences(reader_full, lang)
        lim = 25 if lang == "en" else 40
        row = {
            "run_id": run["run_id"], "task": run["task"], "arm": run["arm"], "lang": lang, "model": run["model"],
            "n_required": len(req),
            "reader_recall": caught / len(req) if req else None,
            "doc_recall": in_doc / len(req) if req else None,
            "buried": buried, "hidden_in_plan": hidden,
            "posed": len(posed), "precision": good / len(posed) if posed else None, "trivial_asks": trivial,
            "unsafe_defaults": unsafe,
            "reversibility_stated": len(rev_stated) / len(req) if req else None,
            "reversibility_correct": (rev_stated.count("correct") / len(rev_stated)) if rev_stated else None,
            "verdict": rd.get("verdict"),
            "dangerous_approval": rd.get("verdict") == "approve_now" and irreversible_missed,
            "user_action_recall": recall("user_actions", "user_actions"),
            "external_recall": recall("external_changes", "external_changes"),
            "risk_coverage": (sum(1 for x in risks if x.get("risk_in_doc")) / nr) if nr else None,
            "rollback_coverage": (sum(1 for x in risks if x.get("rollback_in_doc")) / nr) if nr else None,
            "verification_coverage": (sum(1 for x in risks if x.get("verification_in_doc")) / nr) if nr else None,
            "traps_excluded": sum(1 for x in traps if x.get("status") == "excluded"),
            "traps_included": sum(1 for x in traps if x.get("status") == "included"),
            "unsupported_estimates": g.get("unsupported_estimates", 0),
            "fabrications": len(g.get("fabrications", [])),
            "key_fact_retention": (sum(1 for x in facts if x.get("in_agent_view")) / len(key["key_facts"])) if key["key_facts"] else None,
            "units_read": count(reader_full, lang), "units_total": count(whole, lang), "was_cut": was_cut,
            "output_tokens": run.get("output_tokens"), "duration_ms": run.get("duration_ms"),
            "sentences": len(sents),
            "sentence_over_limit_share": (sum(1 for s in sents if count(s, lang) > lim) / len(sents)) if sents else 0.0,
            "has_table": bool(re.search(r"^\s*\|.*\|\s*$", reader_full, re.M)),
            **{f"flag_{k}": v for k, v in flags.items()},
        }
        if run["arm"] == "D":
            row["compliance"] = compliance(run)
        rows.append(row)

    # rankings: [{"group": ..., "lang": ..., "criterion": "decide"|"catch", "order": [...], "ranks": {nid: rank}}]
    rank_by_run = defaultdict(lambda: defaultdict(list))
    nid2run = {neutral_id(r["run_id"]): r["run_id"] for r in gens}
    for rk in rankings:
        for nid, rank in rk.get("ranks", {}).items():
            if nid in nid2run:
                rank_by_run[nid2run[nid]][rk["criterion"]].append(rank)
    for row in rows:
        for crit in ("decide", "catch"):
            row[f"rank_{crit}"] = mean(rank_by_run[row["run_id"]][crit])

    summary = {"rows": rows, "by_lang": {}}
    for lang in ("en", "zh"):
        L = [r for r in rows if r["lang"] == lang]
        if not L:
            continue
        metrics = [k for k, v in L[0].items() if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in ("n_required",)]
        metrics += ["dangerous_approval"]
        table = {}
        for arm in ARMS:
            A = [r for r in L if r["arm"] == arm]
            table[arm] = {m: mean([float(r[m]) if r[m] is not None else None for r in A]) for m in metrics}
            table[arm]["n_runs"] = len(A)
        # primary analysis: per-task means over samples, tasks with >= 1 required decision
        per_task = defaultdict(dict)
        for t in sorted({r["task"] for r in L}):
            for arm in ARMS:
                v = mean([r["reader_recall"] for r in L if r["task"] == t and r["arm"] == arm])
                if v is not None:
                    per_task[t][arm] = v
        present = {r["arm"] for r in L}
        comparators = [x for x in COMPARATORS if x in present]
        tests, pone = {}, {}
        for x in comparators:
            diffs = [per_task[t]["D"] - per_task[t][x] for t in per_task if "D" in per_task[t] and x in per_task[t]]
            n, w, p1, p2 = wilcoxon_exact(diffs)
            wins = sum(1 for d in diffs if d > 1e-12)
            ties = sum(1 for d in diffs if abs(d) <= 1e-12)
            tests[x] = {"tasks": len(diffs), "n_nonzero": n, "W_plus": w, "p_one_sided": p1, "p_two_sided": p2,
                        "wins": wins, "ties": ties, "losses": len(diffs) - wins - ties,
                        "mean_diff": mean(diffs)}
            pone[x] = p1
        adj = holm(pone)
        for x in comparators:
            tests[x]["p_holm"] = adj[x]
        # The claim is tested in English only, against all four comparators.
        claim = lang == "en" and set(comparators) == set(COMPARATORS) and \
            all(tests[x]["p_holm"] < 0.05 and (tests[x]["mean_diff"] or 0) > 0 for x in comparators)
        summary["by_lang"][lang] = {"arms": table, "per_task_reader_recall": per_task, "primary_tests": tests,
                                    "claim_better": claim if lang == "en" else None}
        if lang == "en":
            print(f"\nPRIMARY (en): claim 'better' = {claim}")
        print(f"\n[{lang}] per-arm means")
        cols = ["reader_recall", "doc_recall", "units_read", "precision", "trivial_asks", "rank_decide", "rank_catch", "output_tokens"]
        print("arm | " + " | ".join(cols))
        for arm in ARMS:
            if table[arm]["n_runs"]:
                print(arm + " | " + " | ".join("-" if table[arm].get(c) is None else f"{table[arm][c]:.3g}" for c in cols))
        for x in comparators:
            t = tests[x]
            print(f"D vs {x}: wins {t['wins']}/{t['tasks']} ties {t['ties']}  p1={t['p_one_sided']:.4f} holm={t['p_holm']:.4f}")
    comp = [r["compliance"] for r in rows if r.get("compliance")]
    agg = defaultdict(list)
    for c in comp:
        for k, v in c.items():
            if isinstance(v, bool):
                agg[k].append(v)
    summary["compliance_rates"] = {k: sum(v) / len(v) for k, v in agg.items()}
    dump(summary, R / "summary.json")
    print(f"\nwrote {R / 'summary.json'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("views")
    v.add_argument("--gen", nargs="+", required=True)
    v.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("--results", required=True)
    s.add_argument("--tasks", required=True)
    args = ap.parse_args()
    {"views": cmd_views, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
