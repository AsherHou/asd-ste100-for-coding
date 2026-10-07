---
name: plan-first
description: Makes the agent write a plan and wait for approval before it changes code, configuration, build scripts, dependencies, public interfaces, or design documents. Produces two files per task, a dense plan for the agent (docs/plan/) and a short plan for the human (docs/human/) written in ASD-STE100-style plain English. Use at the start of any feature, refactor, migration, dependency or API change, or multi-file edit, and when the user asks for a plan, plan mode, or approval before coding. Does not apply to questions, code reading, running existing tests, typo or comment fixes, or small bug fixes that restore designed behavior. For Chinese, use plan-first-zh.
license: MIT
metadata:
  author: "Asher"
  homepage: "https://github.com/AsherHou/asd-ste100-for-coding"
---
# Rule: Plan before development, act only after approval

> This skill holds the full plan-first rules. The human doc template is the last section of this file. Where the rules mention `human-template.md`, use that section. If the user writes in Chinese, use the `plan-first-zh` skill. If the project already loads plan-first through `CLAUDE.md` or `AGENTS.md`, follow that copy and ignore this one.

## 1. When to plan first

Any development task that changes any of the following needs a plan first, and you carry it out only after the user approves: code, configuration, build scripts, dependencies, external interfaces, design documents, patches.

The following are exceptions. You can do them directly, but say clearly in your reply what you changed and why:

- **Bug fixes**: restoring an existing feature to its designed behavior, without changing the design, external interfaces, configuration options, data formats, or dependencies. The existing tests, the documentation, or the user's description define the designed behavior. If none of these exist, or they contradict each other, handle the task as one you are not sure about. If changes outside tests touch more than 3 files or about 50 lines, treat it as a development task. These two numbers are upper limits, not the criteria for a bug fix. You can adjust them for each project, but write them as numbers.
- **Work that changes nothing**: looking things up, research, answering questions, reading code, running existing build and test commands.
- **Small changes that do not affect behavior**: fixing typos only in comments or documentation, or changing only whitespace and formatting, in at most 3 files. Treat typos in program output, user interface text, configuration options, and identifiers as bug fixes. Treat formatting the whole repository as a development task.
- **Small changes the user has already specified**: the user's request already gives the exact change or the exact value. The change must also meet four conditions. It changes at most 3 files and adds no dependencies. It does not change external interfaces, data, or permissions. Reverting the commit fully undoes it. Also, carrying it out must not require the AI to make any trade-off that the user can see. If all of these hold, you can do it directly. In your reply, also write the four Impact lines, and commit as section 4 describes. If any condition fails, stop and write a plan as for a development task. Do the same if you find during execution that you must make a trade-off the user can see.
- **The user explicitly says "just do it" or "no plan needed".**

If you are not sure which category a task belongs to, treat it as needing a plan, or ask the user first.

## 2. Write two documents

For each task, write two documents with the same file name in different directories:

| Document | Location | Reader |
|---|---|---|
| plan | `docs/plan/YYYY-MM-DD-<task-short-name>.md` | The agent that carries out the task |
| human | `docs/human/YYYY-MM-DD-<task-short-name>.md` | The user |

- If the project's CLAUDE.md or AGENTS.md names a different plan directory, use that directory.
- The task short name is lowercase English words joined by hyphens, for example `2026-10-04-contract-freeze.md`.
- If a directory does not exist, create it first.
- Each document links to the other at the top.

### plan: for the agent

**Goal**: a different agent that has not seen this conversation can read only this document and still complete the task correctly.

It contains, in this order:

1. **Status line**: Draft / Awaiting approval / Approved / In progress / Done, plus a version number and a date.
2. **Goals and completion criteria**: the criteria must be checkable, for example "command X prints Y" or "file X exists and passes test Y". When the task has several features, group the criteria by feature number, using the same numbers as the human doc. In the human doc, each feature's "When done" items reword these criteria.
3. **Background and constraints**: the design sections that apply, confirmed facts, and things you must not do.
4. **Approach and key decisions**: what you chose and why; for each rejected option, one sentence on why it was rejected. Small choices that the AI can make on its own and that can be undone are also recorded here.
5. **Change list and Impact**: down to the file or directory, each marked as new, modified, or deleted. Also write the Impact in the four lines of the human doc: Changes, Adds, Removes, Visible behavior. Visible behavior includes changes to security and permissions. Write "none" for any line that has nothing. The human doc's Impact rewords these four lines and has the same content.
6. **Steps**: numbered. Each step states what to do, what it produces, and how to verify it (give a command or a check method).
7. **Risk handling and stop conditions**: for each risk, state where it went: removed by changing the approach / turned into a user decision / turned into a stop condition. A stop condition is a situation that, if it occurs during execution, requires you to stop and ask the user. For changes that reverting the commit cannot undo, state how to recover.
8. **Not doing**: explicitly list what is outside the scope, to prevent scope creep.
9. **Decisions for the user**: limited to the three kinds defined in the human part of section 2. For each question, note whether it can be undone; for hard-to-undo questions, state the cost; give a recommended option and the reason.
10. **What the user needs to do**: things the user must do personally; if there are none, write "none".
11. **Change log**: add one line for each revision.
12. **Execution log**: append to it during execution, recording deviations and verification results; when done, write the full result.

Style: it can be dense; use lists, paths, and commands freely; no pleasantries and no repetition. For any plan doc item with no content, write only one line: "none".

### human: for the user

**Goal**: without reading code, the user can judge four things: what this task does, what it will touch, what they need to decide, and what they need to do themselves. The human doc covers only these four things. Things done by convention go into the rules (see section 4) and are not repeated in each plan.

Before writing:

- First read `human-template.md` in the same directory, and fill in that template.
- **No "Risks" section.** If every plan lists risks, the user gets used to skipping them. Each risk must go into one place:
  - If changing the approach can remove it, change the approach.
  - If the user must make a trade-off, write it under "Decisions for you".
  - If it only becomes known during execution, write it into the plan doc's stop conditions.
- If a risk fits none of the three places, the plan is not thought through yet. Do not hand it to the user yet.

The human doc starts with three items, in this order: a level-1 heading, a status line, and a link to the plan doc. The heading is one sentence that says what the task does. The status line uses the same format as plan doc item 1. If the template and this section disagree, follow this section.

Fixed structure: the heading text and order are fixed, and headings never contain answers.

1. **## What this does**: write it by feature. When the task has only one feature, always write the three lines below. When it has several features, give each feature its own number with its own "Purpose:" and "When done:", then write one shared "Not doing:" line at the end.
   - Purpose: what problem it solves and what happens if it is not done. One or two sentences.
   - When done: results the user can check, usually 1 to 4 per feature. Together, the "When done" items of all features must cover all completion criteria in the plan doc. Mark anything the user asked for with "(your requirement)".
   - Not doing: the 1 to 3 things the user is most likely to wrongly expect to be done.

   Format for several features:

   ```
   1. **{feature name}**
      - Purpose: ...
      - When done:
        - ...
   2. **{feature name}** (depends on feature 1)
      - Purpose: ...
      - When done:
        - ...

   Not doing: ...
   ```

   - A feature name is "verb + object", for example "Support Chinese input" or "Add login handoff".
   - If one feature depends on another, add "(depends on feature N)" after its name.
   - Later sections refer to a feature as "feature N" and do not repeat its name.
2. **## Decisions for you**: always keep this section. It holds only three kinds of items:
   - trade-offs in product direction, or in behavior the user can see;
   - things that are hard to undo;
   - things that cost money, take the user's time, or use or change the user's accounts.

   Conventions such as naming, formatting, directories, and git follow the rules or are decided by the AI, and are recorded in the plan doc.

   Put each question in bold, followed by "(can undo)" or "(hard to undo)". When the task has several features, add the feature inside the parentheses, for example "(feature 2, hard to undo)". Below the question, write sub-items: "Recommended:" with the reason, and optionally "Alternative:". For hard-to-undo items, add a "Cost:" sub-item. The last line is: To accept all recommendations, reply "approve" to start. To change one and keep the other recommendations, reply like "1: alternative" to start.

   When there is nothing to decide, this section has only one line: Nothing to decide. Reply "approve" to start.
3. **## What you need to do**: include it only when there is something; otherwise omit the whole section. Write what the user must do personally: when, what, and why. The fewer such items the better; do not hand the user anything the AI can do.
4. **## Impact**: always four lines, stating only confirmed facts; if a line has 3 or more items, split it into a sub-list. When the task has several features, write one merged list for the whole round; if an item belongs to only one feature, add "(feature N)" at the end of the line.
   - Changes: which parts change, and about how many files.
   - Adds: new files, dependencies, concepts, or practices, each with a one-sentence reason.
   - Removes: deleted files, features, or data; if there are none, write "none".
   - Visible behavior: changes that users or other programs can see, including changes to security and permissions; if there are none, write "none".

   Changes that reverting the commit cannot undo (for example deleting data, changing external accounts, or publishing externally) must also be written as items under "Decisions for you".
Length and format:

- **The goal is readability, not compression.** Usually 200 to 500 words. This is not a minimum: stop once the four things are written. A large task can use at most 900 words. When there is a lot of content, write it out completely as list items; do not compress sentences. If it would exceed 900 words, split the work into several plans.
- Say each thing only once. No code, no tables, no HTML, no anchors; avoid paths and commands as much as possible.
- Put each field in its own list item, or separate fields with blank lines. Do not rely on a single line break alone to separate them.
- Use bold only for feature names and decision questions.
- Every sentence must have a basis in the plan doc. Do not write promises or numbers that are not in the plan doc.

Writing rules:

These rules are based on the ASD-STE100 (Simplified Technical English) writing rules. You can also apply the full STE100 writing rules. You do not have to use the STE dictionary. Write the human doc by the rules below. For Chinese projects, use the Chinese edition of plan-first.

Sentences

1. Each sentence covers one topic. A descriptive sentence (one that gives information) has at most 25 words. A procedural sentence (one that tells the reader to do something) has at most 20 words. Punctuation does not count, and a number counts as one word.
2. Write complete sentences. Do not shorten them by dropping words. Do not write in telegraph style, and do not write half-sentences like "A -> B, C TBD".
3. Use active voice and make clear who acts. Write "I will ..." and "You need to ...", not "X will be done" or "X was performed".

Words

4. Use one name for one thing from start to finish, and use the same name as the plan doc.
5. When a new term first appears, explain it in one sentence. Do not explain terms that earlier human docs already explained. If an everyday word works, use it instead of a term.
6. Do not use vague words such as "related", "relevant", "perform", "conduct", "implement" (when nothing concrete follows), "optimize", "leverage", "empower", "enhance", "robust", "seamless", "streamline", "facilitate", "end-to-end", or "closed loop". Say what was actually done instead.
7. Use concrete numbers, not "quickly" or "large". For example, write "about 20 minutes" or "2 GB".

Paragraphs

8. Each paragraph has at most 4 sentences and covers only one topic.
9. Items in the same list use the same sentence pattern.

## 3. Approval, revision, and execution

- **Requesting approval**: after writing both documents, give their paths in your reply, summarize the key points and the decisions needed in three to five lines, then stop and wait for the user to approve.
- **When in plan mode**: some tools, for example Claude Code, let you write only their own plan file while in plan mode. In that case, put the full human doc in the first half of the plan file. Put the full plan doc in the second half, then request approval. If the user accepts this plan, that counts as approval. All decisions follow the recommendations unless the user names an item to change. As the first step after approval, write the two halves to `docs/human/` and `docs/plan/`, and set their status to "Approved". Then start execution. If the user allows a file write or a command in the tool's permission prompt, that does not count as approving the plan.
- **What counts as approval**: only an explicit statement of agreement from the user counts (for example "approve", "OK", "let's start", "go ahead"). Choosing only among the options listed under "Decisions for you" also counts as approval, for example "1: alternative" or "approve, 2: alternative". Agreement with conditions, for example "OK, but ...", counts as a revision. Questions, discussion, and no reply do not count. If the user approves only part of the plan, do not carry out the unapproved parts. This also counts as a revision, so follow "Revise both documents together".
- **Record approval in the documents**: after the user approves, first set the status of both documents to "Approved" and write the approved version number. If the user chose among the listed options, the version with those choices written in is the approved version. When execution starts, change the status to "In progress". If you change the plan and must request approval again, first set the status back to "Awaiting approval". After a switch to a new session or agent, trust the status and version number in the documents.
- **Revise both documents together**: whether the user asks for a change or you find one yourself, update both documents at the same time, add a line to the plan doc's change log, and request approval again. The exception is when the user only chooses among the listed options. Then write the choices into both documents, add a line to the change log, and start execution. If a revision removes content, remove it from both documents' "When done", completion criteria, change list, and Impact. Write that content into the plan doc's "Not doing".
- **Deviating from the plan during execution**: the Impact in plan doc item 5 is the boundary, and it matches the Impact in the human doc.
  - Small deviation: it changes no completion criterion and stays within the four Impact lines. You can go ahead and record it in the plan doc's execution log.
  - Large deviation, or a stop condition is hit: stop at once, tell the user, update both documents, and request approval again.
- **Finishing execution**:
  - Set the status of both documents to "Done". Write the full result only in the plan doc's execution log; do not add results to the human doc.
  - Give the user a completion report in your reply, using the same writing rules as the human doc. The first line is "Done: {task name}", followed by four fixed blocks; omit any block that is empty:
    1. When done: for each item, write "met" or "not met", with evidence. If the task had several features, group the items by feature.
    2. Differences from the plan: list the ones that went beyond Impact first.
    3. How you can check: give 1 check the user can do themselves.
    4. What remains: name anything that needs a separate plan.
- **Handing execution to a subagent or a new session**: the task description must give the plan doc path, the step numbers, the approved version number, and "the user has approved". The agent that takes over checks these first. If the description gives all of them and the version number matches the status line, that agent follows the plan doc. It then writes no separate plan and does not request approval from the user. If the description lacks them, or the version number does not match, the agent only reports and changes no files. If a subagent hits a large deviation or a stop condition, it hands the matter back to the agent that sent it. For other tasks, section 1 still applies.

## 4. Git conventions

If the project or the user has other git conventions, follow those. The conventions below are the defaults when there are none.

All tasks follow these conventions, and each rule applies only where it fits. Plans do not repeat them. Except for rules 2 and 3, do not ask the user about them.

1. The project must be in a git repository. If it is not in one yet, put a step to initialize git in the first plan. List that step under "Adds" in the human doc's Impact. When the user approves the plan, that approval covers this step.
2. Commit authorship uses the repository's local config; do not change the global config. Before the first commit, if there is no usable authorship config, ask the user once for a name and email. Ask in your reply, and reuse the answer afterward.
3. Before execution starts, the working tree must be clean. If there are uncommitted changes that this task did not cause, stop and ask the user first. Do not handle these changes yourself with stash, reset, checkout, or clean.
4. Commit after each plan is carried out. First set both documents to "Done" and finish the execution log. Then make the last commit, and include both documents in it. Stage only the files in this plan's change list and the two documents. Do not use `git add -A`, `git add .`, or `git commit -a`. Do not stage changes that this task did not cause; list them in the completion report. The first line of the commit message states the result; the body gives the plan file name. One plan can be split into several commits along logical lines.
5. Do not commit build output, dependency directories, large files, secrets, or personal data; exclude them with `.gitignore`.
6. The default way to roll back is to revert this task's commits.
7. Do not rewrite existing commit history, for example by force-pushing or rebasing committed work, unless the user asks.
8. Rules 3 and 4 do not apply to read-only work in the exception tasks of section 1. If an exception task changes files and the working tree was clean before it started, commit when done. Commit only the files you changed. The first line of the commit message states the result. The body says "No plan: " followed by the exception category, for example "No plan: bug fix". If the working tree was not clean before the task started, do not stop to ask, and do not commit. List the files you changed in your reply.

## Human doc template

````markdown
<!-- This is the template for the human doc. Replace each {...} with your content. Delete all comments when you finish. The rules are in section 2 of plan-first.md, under "human: for the user". -->
# {Write the task name as one sentence that says what this task does.}

> Status: Awaiting approval · v1 · YYYY-MM-DD
>
> Plan doc for the agent: [../plan/YYYY-MM-DD-{task-short-name}.md](../plan/YYYY-MM-DD-{task-short-name}.md)

## What this does

<!-- Format 1: use this format when the task has only one feature. -->

Purpose: {Say what problem this solves and what happens without this change. Use one or two sentences.}

When done:

1. {Write a result the user can check.}
2. {Write a result the user can check. If the user asked for it, add "(your requirement)".}

Not doing: {List the 1 to 3 things the user is most likely to expect by mistake.}

<!-- Format 2: use this format when the task has several features. Give each feature its own number and a "verb + object" name. Later sections refer to each feature as "feature N". -->

1. **{Feature name}**
   - Purpose: {Use one or two sentences.}
   - When done:
     - {Write a result the user can check.}
2. **{Feature name}** (depends on feature 1)
   - Purpose: {Use one or two sentences.}
   - When done:
     - {Write a result the user can check.}

Not doing: {List the 1 to 3 things the user is most likely to expect by mistake.}

## Decisions for you

<!-- Put only three kinds of items here. The first kind is a trade-off in product direction or in behavior the user can see. The second kind is hard to undo. The third kind costs money, takes the user's time, or uses or changes the user's accounts. -->
<!-- If there is nothing to decide, this section has only one line: Nothing to decide. Reply "approve" to start. -->

1. **{Question?}** (can undo)<!-- If the task has several features, write "(feature N, can undo)". -->
   - Recommended: {Give the option and the reason.}
   - Alternative: {Give another option. This line is optional.}
2. **{Question?}** (hard to undo)
   - Recommended: {Give the option and the reason.}
   - Cost: {Say what is hard to undo after this choice.}

To accept all recommendations, reply "approve" to start. To change one and keep the other recommendations, reply like "1: alternative" to start.

## What you need to do

<!-- If the user does not need to do anything personally, delete this whole section. -->

- {Say when to do it, what to do, and why.}

## Impact

<!-- If the task has several features, write one merged list for the whole round. If an item belongs to only one feature, add "(feature N)" at the end of the line. -->

- Changes: {Name the parts that change and about how many files.}
- Adds: {List new files, dependencies, concepts, or practices. Give a one-sentence reason for each. If there are none, write "none".}
- Removes: {List deleted files, features, or data. If there are none, write "none".}
- Visible behavior: {List changes that users or other programs can see. Include changes to security and permissions. If there are none, write "none".}
````
