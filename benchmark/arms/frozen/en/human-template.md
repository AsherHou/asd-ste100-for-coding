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

<!-- For the AI's time, use the total estimated time in plan doc item 6. For the "you about" time, count only the things listed in plan doc item 10. Do not count reading the documents, replying to approve, or checking the work after it is done. If plan doc item 10 is "none", write only the first half. -->

Estimated time: AI about {how long?}; you about {how long?}.
