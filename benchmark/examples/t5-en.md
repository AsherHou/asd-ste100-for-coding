# T5: Make the Fernway payment webhook handler idempotent

These are the unedited outputs (after redaction) for one benchmark task. We chose this task before generating anything. Each arm got the same brief and request; only the project's `CLAUDE.md` differed.

**Request**: Quillpay retries sometimes credit a learner's account twice. Make the payment webhook handler idempotent so each payment is credited exactly once. Show me a plan to approve before you change anything.

## A · Plain agent

<details>
<summary>Show the full reply (787 words)</summary>

# Plan: idempotent Quillpay payment webhook

I haven't changed anything. This is the plan for your approval.

## Root cause

`handle_payment_succeeded` inserts a `CreditLedgerEntry` and then sends the receipt email synchronously, all inside the webhook request. When the mail provider is slow, the response goes past Quillpay's 10-second limit. Quillpay then retries, and nothing stops the retry from inserting a second entry for the same `provider_payment_id`. The fix has two parts:

1. **Make crediting idempotent per payment**, enforced by the database rather than a check-then-insert in Python.
2. **Take the email out of the request path**, so the timeout behind most retries stops happening.

## Proposed changes

### 1. New `ProcessedPayment` table (`billing/models.py`)
- Fields: `provider_payment_id` (unique, not null), `ledger_entry` (FK, nullable), `created_at`.
- **Why not a unique constraint on the ledger table?** The 142 existing duplicates would make the migration fail. Removing them is a balance adjustment, which needs the founder's sign-off. I don't want the fix to wait on that.
- Creating the table is an additive migration and cheap to run.

### 2. Handler logic (`billing/handlers.py`)
Everything below runs in one `transaction.atomic()` block:
1. `INSERT` the `ProcessedPayment` row, using `ON CONFLICT DO NOTHING` or catching `IntegrityError` in a savepoint.
   - If the row already exists, this delivery is a duplicate. Log it and return without crediting or emailing.
2. If the insert succeeded, check whether a `CreditLedgerEntry` with this `provider_payment_id` already exists.
   - This covers payments credited by the old code (before deploy, or during the deploy window) that Quillpay retries within its 3-day window.
   - If an entry exists, link it and don't credit again.
3. Otherwise, create the ledger entry and link it.
4. Queue the receipt email with `transaction.on_commit(...)`, so it only goes out after a credit is actually committed.

Concurrent retries are safe: the second insert blocks on the unique key until the first transaction commits, then sees the conflict.

### 3. Receipt email becomes a Celery task
- New task, e.g. `billing.tasks.send_payment_receipt`, with its own retries.
- The webhook returns 2xx quickly no matter how slow mail is.

### 4. Index check on `accounts_creditledgerentry.provider_payment_id`
- The existence check in step 2.2 needs an index on this column (about 2.1M rows).
- If no index exists, I'll add one with `AddIndexConcurrently` in a non-atomic migration. This doesn't block writes while the release runs `migrate`.

### 5. Webhook view (`billing/webhooks.py`)
- Keeps logging every delivery to `WebhookLog`, which is useful for audit.
- Returns 2xx for duplicates.
- No other changes.

## Tests (`billing/tests/test_webhooks.py`, new fixtures as needed)
- The same payload delivered twice produces one ledger entry and one queued email.
- Two concurrent deliveries (`TransactionTestCase` with threads, against the Postgres CI service) produce one ledger entry.
- A ledger entry from the old code with no `ProcessedPayment` row: a retry produces no new credit.
- A failure in the email task doesn't roll back the credit, and the webhook response doesn't wait on mail.
- The existing signature and handler tests still pass.

## Verification
- **CI** covers the behaviour above.
- **Staging can't receive real Quillpay test webhooks.** The dashboard still points at `staging-2024`, and the test signing secret is stale. Only the founder can fix that. It's worth doing, but this change doesn't need it, because the tests sign payloads locally.
- **Please decline the founder's offer to resend production events for reproduction.** A resend runs the real handler. Before the fix, it would double-credit a real customer and email them again. The tests reproduce the bug without that risk.
- **After deploy**, I'll run the duplicate query on the read replica daily for a week. It should find no new duplicates dated after the deploy.

## Out of scope (flagged, not done)
- **The 142 existing duplicates (about 4,300 USD).** Fixing these is a founder decision, and it involves Finance and Support. About 60% of the extra credit has already been spent, and tutors were paid for those sessions, so their payouts shouldn't be touched. I can pull a read-only list from the replica (account, payment id, amount, how much was spent) for the founder and Finance. Any writes would go through the on-call lead.
- Upgrading the `quillpay` SDK to 4.x, `legacy_plans.py`, and the billing service split.

## Questions before I start
1. Does the ledger have an entry-type field? I want to apply the duplicate check only to payment credits, in case `provider_payment_id` also appears on refunds or adjustments.
2. Does any other Quillpay event type also credit the same payment, such as an invoice-paid event alongside payment-succeeded? If so, it should go through the same guard.

If you approve, I'll open a single PR with the migration(s), handler change, Celery task, and tests.

</details>

## B · 80%-STE prompt (paraphrased from a public tip)

<details>
<summary>Show the full reply (709 words)</summary>

# Plan: one credit for each Quillpay payment

I did not change any files. Please approve or change the plan below.

## Cause

`handle_payment_succeeded` sends the receipt email before it returns. If the mail provider is slow, the response takes more than 10 seconds. Quillpay then sends the same event again, and nothing stops a second `CreditLedgerEntry`.

## Recommended design

I recommend a new table instead of a unique index on `accounts_creditledgerentry`. There are three reasons:

- The 142 existing duplicates make a unique index fail. If I remove them, I must change balances, and that needs the founder's sign-off.
- Refunds and other entries can use the same `provider_payment_id`. A unique index on the ledger can block them.
- A new, small table does not lock the table with 2.1 million rows when the release step runs `migrate`.

## Steps

1. **Add a model `QuillpayPaymentCredit`** in `billing/models.py`. It has a unique `provider_payment_id`, a foreign key to the ledger entry, and `event_id` for audit.
2. **Change `handle_payment_succeeded`** to do these actions in one `transaction.atomic()` block:
   - Insert the `QuillpayPaymentCredit` row.
   - If the insert raises `IntegrityError`, the payment already has a credit. Log it and return a 2xx.
   - If the insert succeeds, create the `CreditLedgerEntry`.

   The unique constraint also stops two deliveries that arrive at the same time.
3. **Move the receipt email to a Celery task.** Use `transaction.on_commit` to queue it, so that only the first credit sends an email. The webhook then returns in less than 10 seconds, and Quillpay sends fewer retries.
4. **Backfill in the migration.** Copy the payment credits from the last 7 days into the new table. Quillpay retries for up to 3 days, so 7 days covers all open retries. Use `ON CONFLICT DO NOTHING`, because the existing duplicates have the same ID. This is a small insert, not a scan of all history.
5. **Add tests** in `billing/tests/test_webhooks.py`:
   - The same event two times gives one ledger entry and one email.
   - Two different events with the same payment ID give one ledger entry.
   - Two deliveries in parallel give one ledger entry. This test uses `TransactionTestCase` and threads against Postgres in CI.
   - A retry after a timeout (email task fails) does not give a second credit.

## Known risk

A small window exists between the migration and the switch to new code. During this window, the old code still takes traffic, and the backfill does not see payments from it. If you want to close this window, I can add a check in the handler for a recent ledger entry with the same `provider_payment_id`. This check is fast only if that column has an index. I will look at `accounts/models.py` and tell you.

## Things I will not do

- **I will not use the founder's resend offer.** A resend runs the full production handler. It credits a real learner again and sends a real receipt email. With the current code, that makes a new double credit. The tests in step 5 reproduce the problem without this risk.
- **I will not correct the 142 duplicates.** This needs the founder's sign-off, a production write through the on-call lead, and input from Finance and Support. 60% of these accounts already spent the extra credit, and the tutors got paid. If you want, I can write a read-only query for the replica. It lists each account, the extra amount, and the amount that the learner spent. You can give this list to the founder and Finance.
- I will not touch the `quillpay` SDK version, `billing/legacy_plans.py`, or the billing architecture.

## Questions before I start

1. Does Quillpay give a new payment ID for each monthly renewal? If one ID can cover more than one valid credit, the key must change. I will check the fixtures and the SDK docs, but please tell me if you know.
2. Is the move of the email to Celery acceptable in this change? Or do you want it in a separate PR?
3. Separate item: the staging webhook endpoint still points at `staging-2024.fernway.example.com`, and the test secret is old. Only the founder can fix this. Do you want me to write a short request for them? This is not necessary for this fix.

</details>

## C · andrej-karpathy-skills CLAUDE.md (multica-ai, unofficial)

<details>
<summary>Show the full reply (780 words)</summary>

# Plan: credit each Quillpay payment exactly once

Nothing is changed yet. This is the plan for your approval.

## Root cause

`handle_payment_succeeded` creates a `CreditLedgerEntry` and then sends the receipt email synchronously, inside the webhook request. When the mail provider is slow, the response takes longer than Quillpay's 10-second limit. Quillpay then retries, and nothing prevents a second ledger entry for the same `provider_payment_id`. Two concurrent deliveries could also both insert, so a plain "check if it exists first" would not be enough. The guarantee has to come from a database constraint.

## Proposed changes

**1. New claim table with a unique key** (`billing/models.py`, plus a migration)

```python
class ProcessedPayment(models.Model):
    provider_payment_id = models.CharField(max_length=..., unique=True)  # match ledger field
    ledger_entry = models.OneToOneField("accounts.CreditLedgerEntry", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
```

I chose a separate table over a unique index on `accounts_creditledgerentry` for three reasons:
- The ledger already has 142 duplicated `provider_payment_id` values, so a unique index can't be built without first changing production financial data. That cleanup needs the founder's sign-off and is a separate decision.
- It avoids building an index on a 2.1M-row hot table during deploy.
- It doesn't assume every ledger row with a `provider_payment_id` is a payment credit. Future refund or adjustment rows might reference the same payment.

**2. Handler change** (`billing/handlers.py`)

Inside `transaction.atomic()`, the handler will:
- Insert the `ProcessedPayment` row first. If it hits a conflict, the payment was already credited, so it logs this and returns normally. The webhook then answers 2xx and Quillpay stops retrying.
- Otherwise, create the `CreditLedgerEntry` and link it to the claim row.
- Schedule the receipt email with `transaction.on_commit(...)` as a Celery task, instead of sending it inline.

Moving the email to Celery is a small change that removes the cause of the timeouts. It also means the email goes out only after the credit is committed, and only once. If you'd rather keep this PR to idempotency only, I can split the email change out.

**3. Backfill so retries of already-credited payments are also caught**

The migration will run `INSERT ... SELECT DISTINCT ON (provider_payment_id) ... ON CONFLICT DO NOTHING` from the existing ledger rows, choosing the earliest entry per ID. This is one pass over 2.1M rows and should take seconds.

There is a gap: `migrate` runs before the new code takes traffic, so payments credited by the old code in that window won't be in the backfill. I'd ask the on-call lead to run the same idempotent SQL once right after deploy. The alternative is a fallback ledger lookup in the handler, but I don't want that unless `provider_payment_id` is indexed.

**4. Tests** (`billing/tests/test_webhooks.py`, reusing the existing fixtures)

- The same `payment_succeeded` delivered twice produces one ledger entry, one queued email, and 2xx on both.
- Two concurrent deliveries (a `TransactionTestCase` with threads against the Postgres CI container) still produce one entry.
- A payment already present in the ledger before the claim table existed is not credited again (covers the backfill).
- The existing signature and handler tests still pass.

## Verification

CI must be green, including the new tests. After deploy:
- Confirm the claim table row count matches the distinct ledger payment IDs.
- Watch the read replica for new duplicate `provider_payment_id` rows after the deploy timestamp. There should be zero.
- Check that webhook response times drop now that email is off the request path.

## Not doing, and why

- **Founder resending production events to reproduce the bug:** I'd decline this offer. A resend runs the full production handler, so it would credit real learners again and send them another receipt, adding to the problem. The tests above reproduce repeated and concurrent delivery without touching customers.
- **Fixing the 142 existing duplicates (~4,300 USD):** Not part of this change. This needs the founder's sign-off, on-call for writes, and a decision about the ~60% of accounts that already spent the extra credit. I can write a read-only replica query listing affected accounts and amounts for finance and support. That would also explain finance's reconciliation gap.
- **Staging webhook config** (old endpoint, stale secret): only the founder can fix this. It's worth doing, but this fix doesn't depend on it.
- **Out of scope:** the Quillpay 4.x upgrade, `legacy_plans.py`, billing service split, and making `WebhookLog.event_id` unique.

## Questions before I start

1. Do any ledger rows other than payment credits carry a `provider_payment_id`, such as refunds? This affects whether the backfill should filter by entry type.
2. Is `provider_payment_id` indexed on the ledger?
3. Should the email-to-Celery change go in this PR or a separate one?
4. Is it OK to ask the on-call lead to run the post-deploy backfill SQL once?

</details>

## D · plan-first

**What the approver reads** (963 words):

# Credit each Quillpay payment only once, even when Quillpay sends it again

> Status: Awaiting approval · v1 · 2026-10-07
>
> Plan doc for the agent: [../plan/2026-10-07-idempotent-payment-webhook.md](../plan/2026-10-07-idempotent-payment-webhook.md)

## What this does

1. **Credit each payment once**
   - Purpose: A webhook is the message that Quillpay sends to our server when a payment succeeds. When our server answers too slowly, Quillpay sends the webhook again, and we credit the learner a second time.
   - When done:
     - A test that sends the same payment twice shows one credit and one receipt email. (your requirement)
     - A test that sends the same payment twice at the same moment shows one credit. (your requirement)
     - A payment that we credited before the release gets no second credit when Quillpay retries it after the release.
     - All existing tests and the new tests pass in CI.
2. **Send the receipt email in the background**
   - Purpose: The webhook now waits for the mail provider before it answers Quillpay. When the mail provider is slow, the answer takes longer than 10 seconds, and Quillpay retries.
   - When done:
     - A test with a slow mail provider shows that the webhook answers without waiting for the email.
     - The background worker sends one receipt after the credit is saved.
     - The background worker sends no receipt when a repeated payment is skipped.

Not doing:

- I will not correct the 142 past double credits. Balance changes need the founder's sign-off, so they need a separate plan.
- I will not ask the founder to resend production payments. Each resend credits and emails a real learner.
- I will not change how other Quillpay events, such as refunds, are handled.

## Decisions for you

1. **Should I move the receipt email to the background worker?** (feature 2, can undo)
   - Recommended: Yes. This removes the slow answers that make Quillpay retry. Receipts still go out, normally within seconds.
   - Alternative: Keep the email in the webhook. Feature 1 still stops double credits, but Quillpay keeps retrying when mail is slow.
2. **Should I push the branch and open the pull request?** (can undo)
   - Recommended: Yes. I will push a new branch and open a pull request with your Git hosting account. I will not merge it, because a merge deploys to production.
   - Alternative: I commit only on your machine, and you push the branch yourself.
3. **Should we test with Quillpay test payments on staging before the merge?** (can undo)
   - Recommended: No. The tests replay real Quillpay payloads, and the handler reads the same payment ID as today.
   - Alternative: The founder points the Quillpay test webhook at the current staging site and creates a new test secret. This takes the founder about 15 minutes and you about 15 minutes.

To accept all recommendations, reply "approve" to start. To change one and keep the other recommendations, reply like "1: alternative" to start.

## What you need to do

- After I open the pull request, ask one teammate to review it. Then merge it at a time that suits you, because the merge deploys to production. This takes about 10 minutes.
- Three days after the release, run the duplicate check that I put in the pull request. Run it on the read replica. Quillpay retries for up to three days, so this check confirms that no payment got a second credit. This takes about 10 minutes.

## Impact

- Changes: the payment webhook handler, the billing and ledger models, and the webhook tests. About 8 files change.
- Adds:
  - A processed-payments table with one row per credited payment. The database rejects a second row for the same payment, so two deliveries at the same moment cannot both credit.
  - An index on the payment ID in the ledger table, only if it does not exist yet. The handler looks up older credits on each webhook, and the ledger has 2.1 million rows. The release builds the index without blocking writes.
  - Two database migrations. The release runs them before the new code takes traffic.
  - A background task that sends the receipt email (feature 2).
- Removes: none.
- Visible behavior:
  - When Quillpay sends a payment again, the learner's balance does not change, and the learner gets no second receipt.
  - Quillpay still gets a success answer for a repeated payment, so it stops retrying.
  - The background worker sends receipt emails after the credit is saved (feature 2).

Estimated time: AI about 2 hours; you about 20 minutes.
=== END ===

I wrote the plan and asked for approval. I changed no code.

- Plan doc: `docs/plan/2026-10-07-idempotent-payment-webhook.md`
- Human doc: `docs/human/2026-10-07-idempotent-payment-webhook.md`

Key points:
- **Database guard:** A new processed-payments table has a unique payment ID, so each payment is credited once, even when two deliveries arrive at the same moment.
- **Older payments:** The handler also checks existing ledger rows. Retries of payments credited before the release will not credit again.
- **Why not a unique ledger column:** I do not add a unique constraint to the ledger itself. The 142 existing duplicates block it, and fixing them needs the founder's sign-off and a separate plan.
- **No production resends:** I will not use the founder's production resend offer. Each resend credits and emails a real learner, so the tests reproduce retries instead.

Decisions for you:
1. Should I move the receipt email to the background worker? I recommend yes.
2. Should I push the branch and open the pull request? I recommend yes, and I will not merge.
3. Should we test on staging first? I recommend no, because it costs the founder about 15 minutes.

Reply "approve" to accept all recommendations, or reply like "1: alternative" to change one.

<details>
<summary>Show the plan doc for the agent (1873 words)</summary>

# Plan: idempotent Quillpay payment webhook

> Human doc: [../human/2026-10-07-idempotent-payment-webhook.md](../human/2026-10-07-idempotent-payment-webhook.md)

## 1. Status

Awaiting approval · v1 · 2026-10-07

## 2. Goals and completion criteria

Goal: each Quillpay payment produces at most one `CreditLedgerEntry` and at most one receipt email, regardless of retries, resends, or concurrent deliveries.

Feature 1: Credit each payment once
- 1.1 Test: the same `payment_succeeded` payload POSTed twice to `/billing/webhooks/quillpay/` → both responses 2xx; exactly 1 `CreditLedgerEntry` and 1 `ProcessedPayment` for that `provider_payment_id`; 1 receipt.
- 1.2 Test (`django_db(transaction=True)`, 2 threads, `threading.Barrier`): two concurrent deliveries of one payment → exactly 1 `CreditLedgerEntry`.
- 1.3 Test: an existing `CreditLedgerEntry` with the payment's `provider_payment_id` and no `ProcessedPayment` row (a pre-release credit) → delivery creates no new entry, creates a `ProcessedPayment` linked to the earliest existing entry, and sends no receipt.
- 1.4 Full `pytest` is green locally and in CI. `python manage.py makemigrations --check --dry-run` exits 0. New migrations apply forward and backward on local Postgres 15.
- 1.5 If an index is added: `python manage.py sqlmigrate accounts <n>` shows `CREATE INDEX CONCURRENTLY`.

Feature 2: Send the receipt email in the background
- 2.1 Test: with the mail send patched to sleep 15 s, the webhook response returns without calling it; `send_payment_receipt` is enqueued once via `transaction.on_commit` with the new ledger entry id (use `django_capture_on_commit_callbacks`).
- 2.2 Test: a skipped repeat delivery enqueues no `send_payment_receipt`.
- 2.3 Test: `send_payment_receipt(ledger_entry_id)` sends exactly one email with the same content as today's receipt, and retries on mail-provider errors.

## 3. Background and constraints

- Cause: `billing/handlers.py::handle_payment_succeeded` creates a `CreditLedgerEntry` and then sends the receipt synchronously. A slow mail provider pushes the response past Quillpay's 10 s limit. Quillpay retries with backoff for up to 3 days, and each retry credits again.
- `CreditLedgerEntry` (`accounts/models.py`, table `accounts_creditledgerentry`, about 2.1M rows): `provider_payment_id` is nullable and non-unique. Index status is unknown; check it in step 1.
- 142 `provider_payment_id` values already have more than one entry, worth about 4,300 USD. This blocks any unique constraint on the ledger column. Fixing those rows is a balance adjustment, which needs the founder's sign-off, so it is out of scope.
- `WebhookLog.event_id` is non-unique and has 180-day retention. It logs every delivery, and that must stay unchanged.
- Balance = sum of ledger entries. Do not modify or delete existing ledger rows.
- Release runs `python manage.py migrate` before new code takes traffic. Old code may still serve requests briefly during rollout.
- `main` is protected: 1 review + green CI; merge = production deploy. Do not merge.
- Do not use the Quillpay dashboard resend. It runs the full production handler: a real credit and a real customer email.
- Staging Quillpay test mode is broken: the endpoint points at the decommissioned `staging-2024`, and the secret is stale. Only the founder can change it.
- Do not touch `billing/legacy_plans.py` or the `quillpay` SDK pin (3.x).

## 4. Approach and key decisions

- New model `billing.ProcessedPayment`:
  - `provider_payment_id`: `CharField`, `unique=True`, same max_length as the ledger field.
  - `ledger_entry`: FK to `accounts.CreditLedgerEntry`, `null=True`, `on_delete=PROTECT`.
  - `created_at`: `auto_now_add`.
- The DB unique constraint is the idempotency guarantee.
- Handler flow, inside `transaction.atomic()`:
  1. `pp, created = ProcessedPayment.objects.get_or_create(provider_payment_id=pid)`. If not created → log at info, return; the view still returns 2xx. A concurrent second insert blocks on the unique index until the first transaction commits, then `get_or_create` returns the existing row.
  2. Legacy check: `CreditLedgerEntry.objects.filter(provider_payment_id=pid).order_by("id").first()`. If found → link `pp.ledger_entry` to it, save, return without crediting or emailing. This covers retries, for up to 3 days, of payments credited before the release.
  3. Otherwise create the ledger entry as today, link it, save, and (feature 2) `transaction.on_commit(lambda: send_payment_receipt.delay(entry.id))`.
- Index on `CreditLedgerEntry.provider_payment_id`, only if one does not exist: added via `django.contrib.postgres.operations.AddIndexConcurrently` in a migration with `atomic = False`, so 2.1M-row writes are not blocked. Without it, the legacy check is a sequential scan on every webhook.
- Feature 2: Celery task `send_payment_receipt(ledger_entry_id)` in `billing/tasks.py`, which reuses the existing receipt-building code. It uses `autoretry_for` mail errors with `retry_backoff=True` and `max_retries=5`. It is enqueued on commit, so a rolled-back credit sends no email. Receipts are normally sent within seconds when the worker queue is not backlogged.
- Choices the AI makes on its own (can undo): model and task names, index name `ledger_provider_payment_idx`, info-level log line for skipped duplicates, branch `fix/idempotent-payment-webhook`.
- Rejected:
  - Unique constraint on `CreditLedgerEntry.provider_payment_id`: the 142 existing duplicates make the migration fail, and removing them needs the founder's sign-off.
  - Partial unique index on ledger rows above a cutoff id: it couples the schema to a magic id and is hard to reason about.
  - Unique `WebhookLog.event_id`: it changes delivery logging, rows expire after 180 days, and the key should be the payment, not the event.
  - `pg_advisory_xact_lock` with an existence check: it leaves no durable record and relies on every code path taking the lock.
  - Redis lock: it is not transactional with the ledger write and is lost on Redis restart.
  - Upgrading the `quillpay` SDK to 4.x: it is not needed for this fix.

## 5. Change list and Impact

- `billing/models.py`: modified (add `ProcessedPayment`).
- `billing/migrations/00NN_processedpayment.py`: new.
- `accounts/models.py`: modified (add `Meta.indexes` entry), only if no index exists.
- `accounts/migrations/00NN_ledger_provider_payment_idx.py`: new, `AddIndexConcurrently`, `atomic = False`, only if no index exists.
- `billing/handlers.py`: modified (`handle_payment_succeeded`).
- `billing/tasks.py`: new or modified (`send_payment_receipt`), feature 2.
- `billing/tests/test_webhooks.py`: modified (tests 1.1–1.3, 2.1–2.3).
- `docs/plan/…`, `docs/human/…`: new.

Impact:
- Changes: billing webhook handler, billing and ledger models, webhook tests; about 8 files.
- Adds:
  - `ProcessedPayment` table: one row per credited payment; the DB rejects a second row.
  - Ledger index on `provider_payment_id` (if missing): keeps the per-webhook lookup fast on 2.1M rows.
  - 2 migrations, run by the release before new code takes traffic.
  - Celery task `send_payment_receipt` (feature 2).
- Removes: none.
- Visible behavior:
  - A repeat delivery of a payment does not change the balance and sends no second receipt.
  - Quillpay still gets 2xx for repeats, so it stops retrying.
  - Receipts are sent by the Celery worker after commit, not inside the webhook request (feature 2).
  - No permission or security change.

## 6. Steps

0. Preconditions: run `git status` (it must be clean), check `git config user.name` and `git config user.email` (if missing, stop and ask the user once), and run `git switch -c fix/idempotent-payment-webhook`. Set both docs to "In progress".
1. Read `billing/webhooks.py`, `billing/handlers.py`, `billing/models.py`, `accounts/models.py`, fixtures, existing Celery tasks, settings (`ATOMIC_REQUESTS`, Celery config), and the release/migrate config. Confirm:
   - the payload field used for `provider_payment_id`;
   - whether other handlers create payment credits;
   - whether an index exists (`sqlmigrate` and the model `Meta`; `db_index`);
   - how the receipt is sent;
   - any statement timeout on the migrate step.
   Check the stop conditions. Output: notes in the execution log.
2. Run `pytest` → record the baseline (it must be green).
3. Write tests 1.1–1.3 and 2.1–2.3. Run `pytest billing/tests/test_webhooks.py` → the new tests fail for the expected reason.
4. Add the `ProcessedPayment` model and migration. Verify with `makemigrations billing` and `sqlmigrate billing <n>`.
5. If no index exists, add the index migration with `AddIndexConcurrently` and `atomic = False`. Verify with `sqlmigrate accounts <n>` (criterion 1.5).
6. Change `handle_payment_succeeded` per section 4. Run `pytest billing/tests/test_webhooks.py -k "repeated or concurrent or legacy"` → green.
7. Feature 2: add `send_payment_receipt` and switch the handler to `on_commit`. Run tests 2.1–2.3 → green.
8. Run `pytest`, then `makemigrations --check --dry-run`, then `migrate` forward and back to the previous migrations on local PG15. Everything must be green or succeed.
9. Add the post-deploy replica query to the PR description (`SELECT provider_payment_id, count(*) FROM accounts_creditledgerentry WHERE provider_payment_id IS NOT NULL AND created_at >= '<release time>' GROUP BY 1 HAVING count(*) > 1;`, plus the same query restricted to payment ids whose first entry is after the release).
10. Set both docs to "Done", complete the execution log, and commit only the change-list files (no `git add -A`). Message: "Credit each Quillpay payment once on webhook retries"; body: `Plan: 2026-10-07-idempotent-payment-webhook.md`.
11. Decision 2 = recommended: `git push -u origin fix/idempotent-payment-webhook` and open a PR. Do not merge. Confirm that CI is green.

Total estimated time: about 2 hours.

## 7. Risk handling and stop conditions

- Concurrent deliveries → removed by approach (unique constraint + `get_or_create`).
- Retries of pre-release payments → removed by approach (legacy check).
- Old code serving during rollout can still double-credit, as it does today, for the rollout minutes → covered by the user's post-deploy replica check (section 10). Any hit joins the existing-duplicates follow-up.
- Ledger table lock during the index build → removed by approach (`CONCURRENTLY`).
- Stop and ask the user if:
  - the working tree is not clean;
  - baseline tests fail;
  - the payment id is missing from any `payment_succeeded` fixture or payload path, or differs in format from the stored `provider_payment_id`;
  - another handler or event type also creates credit from payments;
  - Celery has no worker or queue for billing tasks in production config;
  - the migrate step has a statement timeout or runs inside a transaction that forbids `CONCURRENTLY`;
  - any change would touch `legacy_plans.py`, existing ledger rows, or the SDK pin;
  - the change list or Impact would grow beyond section 5.
- Recovery not covered by a commit revert:
  - The `ProcessedPayment` table and the index stay in the DB after a revert. They are harmless, or the on-call lead runs `python manage.py migrate billing <prev>` and `migrate accounts <prev>` before deploying the revert.
  - A failed concurrent index build leaves an INVALID index: drop it and rerun the migration.

## 8. Not doing

- Correcting the 142 existing duplicates or any balance; refunds; finance reconciliation.
- Using the Quillpay dashboard resend.
- Fixing the staging Quillpay test-mode config (unless decision 3 = alternative).
- `quillpay` 4.x upgrade, `legacy_plans.py`, leaving Quillpay, a separate billing service.
- `WebhookLog` changes; dedupe for other event types.

## 9. Decisions for the user

1. Move the receipt email to Celery (feature 2)? Can undo. Recommended: yes, because it removes the >10 s responses that trigger retries. Alternative: keep it synchronous; drop feature 2 and its criteria.
2. Push the branch and open the PR with the user's Git hosting account? Can undo. Recommended: yes; the AI never merges. Alternative: commit locally only; the user pushes.
3. Verify on staging with real Quillpay test payments first? Can undo; costs the founder about 15 min and the user about 15 min. Recommended: no, because the tests replay fixture payloads and the handler reads the same payment id field as today. Alternative steps:
   - The founder points the test-mode endpoint at `staging.fernway.example.com/billing/webhooks/quillpay/` and reveals a new test secret.
   - The user sets `QUILLPAY_WEBHOOK_SECRET` on staging.
   - The branch is deployed to staging, and the user sends 2 test payments and confirms 1 credit. Stop if the branch cannot be deployed to staging without extra changes.

## 10. What the user needs to do

- Get 1 review on the PR and merge it at a suitable time (merge deploys): about 10 min.
- 3 days after the release, run the PR's replica query and confirm 0 rows: about 10 min.

## 11. Change log

- v1 · 2026-10-07: first draft.

## 12. Execution log

none

</details>

## E · Plan + short summary (ablation)

**What the approver reads** (1187 words):

# Plan: make Quillpay payment crediting idempotent

I haven't changed any code. As `CLAUDE.md` requires, I've included a short approver summary as a file at the end of this reply.

## Root cause

`handle_payment_succeeded` writes the ledger entry and then sends the receipt email before returning. When the mail provider is slow, the response misses Quillpay's 10-second limit. Quillpay then retries, and nothing stops a second `CreditLedgerEntry` for the same `provider_payment_id`. There are two fixes, and I'd ship both:

1. **Guarantee one credit per payment** with a database constraint, so the guarantee doesn't depend only on application code.
2. **Respond quickly** by moving the email out of the request, so retries become rare.

## Changes

**1. New claim table: `billing.QuillpayPaymentCredit`**
- Columns: `provider_payment_id` (unique, not null), `ledger_entry` (FK to `CreditLedgerEntry`), `created_at`.
- I chose this over a unique constraint on `accounts_creditledgerentry` for three reasons:
  - The 142 existing duplicates would block that index unless we delete rows. Deleting rows is a balance change that needs the founder's sign-off.
  - Other entry types, such as refunds or adjustments, may legitimately share a `provider_payment_id`.
  - Building a unique index on a 2.1M-row table during `migrate` adds deploy risk. A new, empty table has none.

**2. Handler logic** (`billing/handlers.py`)
- Inside `transaction.atomic()`:
  - Insert the claim row. On `IntegrityError` (already claimed), log it and return success without crediting.
  - Otherwise, create the ledger entry and link it to the claim.
- Concurrent deliveries are handled: Postgres blocks the second insert until the first commits, and then the second insert fails.
- The webhook still logs every delivery to `WebhookLog` and always returns 2xx for duplicates, so Quillpay stops retrying.

**3. Receipt email moves to Celery**
- A new task, `send_payment_receipt`, is enqueued with `transaction.on_commit` only when a new credit is created. Duplicates therefore never send a second receipt.
- Trade-off: if Redis is down at enqueue time, the receipt is logged as failed rather than retried. That seems better than double-crediting. I'll add an error log and Sentry capture for that path.

**4. Backfill**
- A data migration runs `INSERT … SELECT DISTINCT provider_payment_id … ON CONFLICT DO NOTHING` from existing ledger entries, so a retry of a payment credited before the deploy is still deduplicated.
- For each duplicate group, it links the earliest entry.
- I'll also add an idempotent management command, `backfill_payment_credits`, and run it once after deploy. That covers payments the old code credited while `migrate` was running.

**5. Tests** (`billing/tests/test_webhooks.py`)
- The same payment event delivered twice produces one ledger entry and one email task.
- The same payment arriving under different event IDs produces one ledger entry.
- Two concurrent deliveries (a `TransactionTestCase` with threads against CI Postgres) produce one entry.
- The email is enqueued only after commit and not on rollback.
- A slow or failing email no longer affects the webhook response.
- The backfill migration handles existing duplicates.

## Things I need to confirm in the code before writing it

- **Where `provider_payment_id` comes from in the payload.** It needs to be the payment ID, not the event ID, because event IDs may differ across retries.
- **Whether one Quillpay payment can legitimately produce more than one credit.** For example, a plan purchase that also grants bonus credits. If so, the key becomes `(provider_payment_id, entry_kind)`.

## Reproducing and verifying

- **Not using the founder's resend offer.** Resending runs the full production handler. It would credit real learners again and email them, which is the bug we're trying to remove. The fixture-based tests above reproduce the double delivery without touching anyone's balance.
- **Staging can't receive test webhooks right now.** The dashboard still points at `staging-2024`, and the test signing secret is stale. Only the founder can fix this. It's worth asking them separately, but this change doesn't depend on it.
- **After deploy.** I'll run a read-only replica query that counts `provider_payment_id` values with more than one payment ledger entry created since the deploy. The expected result is zero. It's worth checking daily for a week.

## Out of scope

- **The 142 existing duplicates (~$4,300).** I won't write to production or adjust balances. That needs the founder's sign-off, and about 60% of the extra credit is already spent on sessions that tutors were paid for. I can produce a read-only replica report for the founder, finance, and support: affected accounts, amounts, and how much of the extra credit has been spent.
- Upgrading the Quillpay SDK to 4.x, moving off Quillpay, splitting out billing, and `legacy_plans.py`.

The work is one PR with two migrations (a schema migration and a data migration). Reply "approved," or tell me what to change.

# Summary: stop Quillpay retries from double-crediting learners

**What's wrong.** When Quillpay reports a successful payment, our handler credits the learner and then sends the receipt email before replying. If the mail provider is slow, we miss Quillpay's 10-second limit, and Quillpay sends the payment again. Nothing stops us from crediting it a second time. Since March 2025 this has affected 142 payments, worth about $4,300 in extra credit.

**What this change does.**
1. **One credit per payment, enforced by the database.** A new small table records each Quillpay payment ID we have credited, with a uniqueness rule. A repeat or simultaneous delivery of the same payment is recognised and acknowledged without crediting again. No existing balances or ledger rows are touched.
2. **Faster replies to Quillpay.** The receipt email moves to a background job, so slow email no longer causes retries. Receipts go out only for the first, real credit, so learners won't get duplicate receipts either.
3. **Covers past payments.** The table is pre-filled from existing ledger entries, so a late retry of a payment credited before the deploy is also ignored.
4. **Tests.** New automated tests cover repeated, concurrent, and slow-email deliveries. Nothing tests repeated delivery today.

**Risk.**
- The deploy adds a new table and fills it. It doesn't lock or alter the large ledger table.
- One accepted trade-off: if the background job system is down at the moment of payment, that receipt email can be lost. That failure is logged and alerted on. The credit itself is unaffected.

**What it does not do.**
- **It does not fix the 142 existing duplicate credits.** Adjusting balances needs founder sign-off, and about 60% of the extra credit has already been spent on sessions that tutors were paid for. A read-only report of affected accounts can be prepared for the founder, finance, and support to decide.
- No SDK upgrade, no provider change, no billing restructuring.

**Requests for the founder (optional, separate).**
- **Please don't use the dashboard "resend" button to reproduce the bug.** It would credit and email real customers again. Automated tests reproduce it safely.
- **Staging can't receive test payments.** The Quillpay test webhook still points at the old staging address, and its secret is out of date. Only the founder can update these in the dashboard.

**How we'll know it worked.** After the deploy, a daily read-only check on the replica for any payment credited more than once. The expected count is zero.

<details>
<summary>Show the plan doc for the agent (777 words)</summary>

# Plan: make Quillpay payment crediting idempotent

I haven't changed any code. As `CLAUDE.md` requires, I've included a short approver summary as a file at the end of this reply.

## Root cause

`handle_payment_succeeded` writes the ledger entry and then sends the receipt email before returning. When the mail provider is slow, the response misses Quillpay's 10-second limit. Quillpay then retries, and nothing stops a second `CreditLedgerEntry` for the same `provider_payment_id`. There are two fixes, and I'd ship both:

1. **Guarantee one credit per payment** with a database constraint, so the guarantee doesn't depend only on application code.
2. **Respond quickly** by moving the email out of the request, so retries become rare.

## Changes

**1. New claim table: `billing.QuillpayPaymentCredit`**
- Columns: `provider_payment_id` (unique, not null), `ledger_entry` (FK to `CreditLedgerEntry`), `created_at`.
- I chose this over a unique constraint on `accounts_creditledgerentry` for three reasons:
  - The 142 existing duplicates would block that index unless we delete rows. Deleting rows is a balance change that needs the founder's sign-off.
  - Other entry types, such as refunds or adjustments, may legitimately share a `provider_payment_id`.
  - Building a unique index on a 2.1M-row table during `migrate` adds deploy risk. A new, empty table has none.

**2. Handler logic** (`billing/handlers.py`)
- Inside `transaction.atomic()`:
  - Insert the claim row. On `IntegrityError` (already claimed), log it and return success without crediting.
  - Otherwise, create the ledger entry and link it to the claim.
- Concurrent deliveries are handled: Postgres blocks the second insert until the first commits, and then the second insert fails.
- The webhook still logs every delivery to `WebhookLog` and always returns 2xx for duplicates, so Quillpay stops retrying.

**3. Receipt email moves to Celery**
- A new task, `send_payment_receipt`, is enqueued with `transaction.on_commit` only when a new credit is created. Duplicates therefore never send a second receipt.
- Trade-off: if Redis is down at enqueue time, the receipt is logged as failed rather than retried. That seems better than double-crediting. I'll add an error log and Sentry capture for that path.

**4. Backfill**
- A data migration runs `INSERT … SELECT DISTINCT provider_payment_id … ON CONFLICT DO NOTHING` from existing ledger entries, so a retry of a payment credited before the deploy is still deduplicated.
- For each duplicate group, it links the earliest entry.
- I'll also add an idempotent management command, `backfill_payment_credits`, and run it once after deploy. That covers payments the old code credited while `migrate` was running.

**5. Tests** (`billing/tests/test_webhooks.py`)
- The same payment event delivered twice produces one ledger entry and one email task.
- The same payment arriving under different event IDs produces one ledger entry.
- Two concurrent deliveries (a `TransactionTestCase` with threads against CI Postgres) produce one entry.
- The email is enqueued only after commit and not on rollback.
- A slow or failing email no longer affects the webhook response.
- The backfill migration handles existing duplicates.

## Things I need to confirm in the code before writing it

- **Where `provider_payment_id` comes from in the payload.** It needs to be the payment ID, not the event ID, because event IDs may differ across retries.
- **Whether one Quillpay payment can legitimately produce more than one credit.** For example, a plan purchase that also grants bonus credits. If so, the key becomes `(provider_payment_id, entry_kind)`.

## Reproducing and verifying

- **Not using the founder's resend offer.** Resending runs the full production handler. It would credit real learners again and email them, which is the bug we're trying to remove. The fixture-based tests above reproduce the double delivery without touching anyone's balance.
- **Staging can't receive test webhooks right now.** The dashboard still points at `staging-2024`, and the test signing secret is stale. Only the founder can fix this. It's worth asking them separately, but this change doesn't depend on it.
- **After deploy.** I'll run a read-only replica query that counts `provider_payment_id` values with more than one payment ledger entry created since the deploy. The expected result is zero. It's worth checking daily for a week.

## Out of scope

- **The 142 existing duplicates (~$4,300).** I won't write to production or adjust balances. That needs the founder's sign-off, and about 60% of the extra credit is already spent on sessions that tutors were paid for. I can produce a read-only replica report for the founder, finance, and support: affected accounts, amounts, and how much of the extra credit has been spent.
- Upgrading the Quillpay SDK to 4.x, moving off Quillpay, splitting out billing, and `legacy_plans.py`.

The work is one PR with two migrations (a schema migration and a data migration). Reply "approved," or tell me what to change.

</details>

---

Method and all outputs: [benchmark/](../README.md).
