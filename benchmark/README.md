# plan-first benchmark

This benchmark asks one question: when an AI coding agent proposes a change, can a busy approver find the decisions they must make?

We wrote this analysis plan before we generated any output. The plan is fixed by the SHA-256 of this file and of `score.py`, which are listed in the results.

## What we compare

Five arms. Each arm is a set of project instructions in the project's `CLAUDE.md`, which is how people use these rules in practice.

| Arm | Project instructions | Source |
|---|---|---|
| A | None | Plain agent |
| B | Write about 80% of the way to ASD-STE100 | A public tip by Andrej Karpathy (X, 2026-10-02), written in our own words and strengthened by a reviewer. Not written or endorsed by Karpathy. |
| C | andrej-karpathy-skills `CLAUDE.md` | multica-ai/andrej-karpathy-skills at commit `2c60614`. Coding-behavior guidelines, not a plan format. Not written by Karpathy. |
| D | plan-first | This repository. The agent writes a plan doc for itself and a short human doc for you. |
| E | Plan plus a short summary file | Ablation. It tests "a short document for the human" without plan-first's template and writing rules. |

The exact instructions are in `arms/`. We do not redistribute arm C because its repository has no license. `arms/C.json` gives the URL, commit and SHA-256, so you can fetch it.

## Tasks

There are 13 synthetic tasks, each with a codebase brief of 300 to 600 words and a user request.

- T1 to T7 and T11 to T13 need decisions from the human, for example account linking, a data migration that you cannot undo, or a cost. Their requests end with "Show me a plan to approve before you change anything."
- T8 to T10 are low-stakes, with few or no decisions: a CLI flag, a refactor and a small bug fix. Their requests do not ask for a plan. They show which arms plan too much.
- P1 and P2 are pilot tasks. We used them only to test the harness. They are not in the results.

Each task has a hidden answer key: decisions the human must make (each with a safe option), things only the human can do, visible changes, risks with rollback and verification, scope traps and key facts. The agents that wrote the tasks did not see plan-first. A separate critic checked that every key item can be found in the brief and that the brief does not give the key away. The tasks are in `tasks/`.

## How outputs are generated

- `generate.py` runs the Claude Code CLI (`claude -p`) once per task and arm. Each run uses a fresh project that holds only the arm's `CLAUDE.md` (and, for arm D, the rule files). The project is a git repository with one initial commit, because the briefs describe git repositories.
- Our first generation pass used projects that were not git repositories. In about half of its arm D outputs, the agent pointed out that this contradicted the brief, because plan-first has git rules. That artifact worked against plan-first, so we fixed the harness and regenerated every arm before any judging. None of the first pass is used in the results.
- File tools are off, so the agent puts each file it would write in its reply after a line `=== FILE: <path> ===`.
- Arm D also imports `human-template.md`, because with tools off the agent cannot open it. With tools on, plan-first tells the agent to read it.
- English runs: 13 tasks × 5 arms × Claude Opus 5.5. Chinese runs: 13 tasks × arms A, D and E × Claude Opus 5.5. Arms B and C are left out of the Chinese runs, because "80% of the way to ASD-STE100" is not defined for Chinese and arm C is English-only.
- One sample per cell. The unit of analysis is the task.

## What the approver reads

`score.py` splits each reply by a fixed rule:

- Arm D: the reply text plus the file under `docs/human/`.
- Arm E: the reply text plus the summary file.
- Arms A, B and C: the whole reply.
- If the expected file is missing, the reader gets the whole reply, and we count a compliance failure.

**Reading budget.** The reader sees only the first 650 English words or 1,100 Chinese characters, which is about 3 minutes of reading. The cut is the same for every arm and is done by `score.py`, not by an agent.

## Readers, graders and rankers

- **Reader** (Claude Sonnet 5.5): sees the one-line request and the cut document, nothing else. It answers 9 questions. A separate agent that had not seen plan-first wrote them from standard change-approval practice. They cover what changes, decisions and whether each can be undone, actions for the human, visible and security changes, risks with rollback and verification, technical soundness, scope and a verdict. Every answer must quote the document. A plausible guess counts as an error.
- **Grader** (Claude Opus 5.5): sees the answer key, the brief, the full reader-visible document, the separate agent document if there is one, and the reader's answers. It does not know the arm. It also gives quotes.
- **Rankers** (Claude Sonnet 5.5): rank the cut documents for one task twice, once in each order. The two criteria are "decide quickly" and "catch a problem before it ships".

## Primary metric and test

- **Primary metric**: reader recall of required decisions. A decision counts as caught when both of these are true:
  - The grader says a reader answer to the decisions question (Q2) or the verdict question (Q8) identifies it.
  - `score.py` finds that answer's quote in the cut document.
- **Tasks in the test**: the 10 tasks with at least one required decision (T1 to T7, T11 to T13), English runs.
- **Test**: an exact one-sided Wilcoxon signed-rank test over tasks, D compared with A, B, C and E, with Holm correction. Tasks with equal scores are dropped from the test, as usual.
- **Claim rule**: we say "plan-first does better" only if D beats all four comparators with a Holm-adjusted p below 0.05. Otherwise we report the result as directional.

## Other results (descriptive only)

- Ranks on both criteria.
- Decision recall in the full document, and decisions that are present but buried.
- For D and E, decisions that appear only in the agent document.
- Precision of the questions put to the human, and trivial questions.
- Unsafe recommended defaults, and dangerous approvals: "approve now" while a decision that cannot be undone was missed.
- Coverage of user actions, visible changes, risks, rollback and verification.
- Scope traps, unsupported estimates, fabrications, and key facts kept in the document the agent works from.
- Words read, words written, output tokens, generation time, and sentence length.
- For D only, mechanical checks of plan-first's own rules.
- Chinese results.

## Redaction

`redact.py` runs once on every raw reply, before scoring.

- It replaces credential-shaped strings, connection strings, emails, local paths and private IPs with fixed placeholders.
- It replaces a few words that our publishing scanner blocks with neutral synonyms.
- The counts are published per run.
- Scores are computed on the redacted text.
- Before publishing, the same redaction was applied to the readers' and graders' answers, with `redact.py --json`. It changed 1 word and 5 file paths, and no score changed.

## Reproduce

```
curl -fsSLo arms/external/karpathy-skills-CLAUDE.md <URL from arms/C.json>
python3 generate.py --tasks tasks/tasks.json --arms arms --lang en --models claude-opus-5-5 --out raw --external arms/external
python3 generate.py --tasks tasks/tasks.json --arms arms --lang zh --models claude-opus-5-5 --out raw --external arms/external --only-arms A,D,E
python3 redact.py raw results/generations.en.json --lang en
python3 redact.py raw results/generations.zh.json --lang zh
python3 -B score.py score --results results --tasks tasks/tasks.json
```

Readers, graders and rankers ran as Claude Code subagents. Their prompts and schemas are in `judge.js`, and their answers are in `results/`.

## Limitations

- Readers, graders and rankers are language models, not people. This is not a human study.
- The tasks are synthetic, and there are only 13.
- There is one generation model and one sample per cell.
- All judges are Claude models, as is the generator.
- The arms are not truly blind. plan-first's fixed headings are easy to spot.
- With tools off, the agent cannot explore a real repository. The brief stands in for what it would find.
- Arm B transfers a tip about explanations to plans, and arm C is not a plan format. The results say how well each one works for approval plans, not whether it is good at what it was made for.

## Results

### Pre-registered test

The claim rule was not met. On the primary metric, plan-first (D) did not beat any comparator. In English it had the lowest reader recall of required decisions:

| Arm | Reader recall (pre-registered) | With the quote fix |
|---|---|---|
| A Plain agent | 0.87 | 0.87 |
| B 80%-STE prompt | 0.83 | 0.83 |
| C andrej-karpathy-skills | 0.65 | 0.69 |
| D plan-first | 0.63 | 0.70 |
| E Plan + short summary | 0.78 | 0.83 |

One-sided exact Wilcoxon over 10 tasks, D compared with each other arm: every Holm-adjusted p is 1.0. D beat A on 2 tasks, B on 1, C on 4 and E on 2. The rest were ties or losses. `results/summary.json` has every metric.

"With the quote fix": readers sometimes put their quotes inside quotation marks, and the pre-registered matcher did not strip them. `explore.py` reruns the metric with that one fix, for every arm. The conclusion does not change.

### Why D scored low (exploratory)

We wrote this analysis after we saw the results, so treat it as exploratory. The grader found every required decision somewhere in every arm's document, so nothing was hidden. The arms differ in how they handle a decision:

| Arm | Questions per plan | Asked the human | Decided safely and stated | Decided unsafely | Words the approver reads |
|---|---|---|---|---|---|
| A | 4.9 | 45% | 38% | 18% | 918 |
| B | 5.4 | 60% | 35% | 5% | 1,046 |
| C | 5.4 | 57% | 42% | 0% | 936 |
| D | 3.4 | 42% | 50% | 8% | 1,064 |
| E | 3.6 | 52% | 38% | 10% | 1,282 |

plan-first asks the fewest questions. It decides about half of the required decisions itself, picks the safe option, and states it as a fact, or it moves the risky part into a later plan. Its rules tell it to do this: if changing the approach removes a risk, change the approach. The readers then do not list these as decisions, so the primary metric drops.

These choices do not make the short plan shorter. D's short plan is about as long as a plain agent's whole plan. D also costs about 4.7 times the output tokens and 4.3 times the generation time.

### Other descriptive results (English, all 13 tasks)

- Trivial questions per plan: D 0.08, A 0.54, B 0.15, C 0.31, E 0.00.
- Inline code (identifiers, commands, config keys in backticks) per 100 words of the approver's document, measured after the test with `explore.py` over the 10 decision tasks: D 0.2, A 4.3, B 4.3, C 4.3, E 3.3. In Chinese: D 0.16, A 2.7, E 1.2. File paths per 100 words: D 0.48, the others 0.77 to 1.0.
- Decisions marked as reversible or not: D 51%, the others 15% to 22%.
- Out-of-scope work included: D 0, A 0.38, B 0.08, C 0.08, E 0.15.
- Key facts kept in the document the agent works from: D 91%, the others 76% to 89%.
- Risks, rollback and verification in the approver's document: D has the least, because plan-first keeps them in the agent plan.
- Rank for "decide quickly" (1 is best): C 2.42, D 2.81, E 2.96, A 3.12, B 3.69. Rank for "catch a problem": E 2.15, C 2.42, A 2.81, B 3.12, D 4.50.
- Numbers in the approver's document that the brief does not support: D 4.5 per plan, mostly from the estimated-time line that the tested rules required. The published rules no longer have that line.

## Changes after the analysis plan was fixed

- **Harness:** the first generation pass used projects that were not git repositories, and this worked against plan-first. We regenerated every arm in git repositories before any judging.
- **Redaction:** one word pattern was widened to match our scanner. It changed 1 English reply, before scoring.
- **Published rules:** they differ from the tested text (kept in `arms/frozen/`) in two ways. The usage line now points to this repository, and the estimated-time line is removed.
