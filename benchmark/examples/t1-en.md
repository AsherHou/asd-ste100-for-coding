# T1: Add Google sign-in to an existing email/password web app

These are the unedited outputs (after redaction) for one benchmark task. We chose this task before generating anything. Each arm got the same brief and request; only the project's `CLAUDE.md` differed.

**Request**: Add "Sign in with Google" to Tallybook's login and signup pages so people can use their Google account instead of a password, and make it work with our existing email/password accounts. Show me a plan to approve before you change anything.

## A · Plain agent

<details>
<summary>Show the full reply (1143 words)</summary>

# Plan: Sign in with Google

I haven't changed anything yet. Below is the plan, the decisions I need from you, and the setup work only you can do.

## Decisions I need from you

1. **How to handle existing accounts whose email was never verified (about 9,000).** This is the main security risk. Someone could sign up with a victim's address and a password they choose, without verifying it. If we then merge the victim's Google login into that account automatically, the attacker's password keeps working and they can read the victim's invoices.
   **My recommendation:** link automatically only when Google reports `email_verified: true`. If the Tallybook account was never verified, still link it, but in the same transaction:
   - mark the account verified,
   - remove the existing password,
   - end all of that user's existing sessions,
   - email them a notice.

   That is equivalent to a password reset, which Google's verified email justifies. The cost is that a legitimate user who never clicked the verification link loses their password and must use Google or "forgot password". The alternative is to refuse to link and send these users through password reset first. That is safer but adds friction.
2. **Preview deploys.** Google doesn't allow wildcard redirect URIs, so `pr-<n>.preview…` can't use Google sign-in. I'd keep the feature flag off on previews and test on local and staging. Is that acceptable?
3. **Which Google Cloud project to use.** I'd reuse `tallybook-prod` for the production client and create separate OAuth clients for staging and local, ideally in a separate non-prod project. While you're in that project, it's worth checking for API keys left over from the autocomplete experiment.

## Work only you (or counsel) can do

These block a production launch, not development:
- **Google Cloud console** (you're the only Owner). Set up:
  - an "External" OAuth consent screen with app name, logo, support email, the authorized domain `tallybook.example.com`, and links to the homepage and privacy policy;
  - scopes `openid email profile` only, which are non-sensitive, so no security review is needed;
  - publishing status "In production". In testing mode, only listed test users can sign in;
  - one Web OAuth client per environment, with these redirect URIs:
    - `http://localhost:3000/auth/google/callback`
    - `https://staging.tallybook.example.com/auth/google/callback`
    - `https://app.tallybook.example.com/auth/google/callback`
- **Privacy policy.** It must say that users can sign in through Google and that we receive their Google account ID, email, name and possibly profile photo from Google. Google also checks this policy when it reviews the brand. I can draft the wording for you and counsel, but I won't edit `public/legal/privacy.html` myself.
- **Secrets.** Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` to the staging and production environment settings (you or the lead engineer), and put the local or staging values in the vault.

## Implementation (a single PR behind `FEATURE_GOOGLE_SIGNIN`)

**Data (`db/migrations/`)**
- Add a new `user_identities` table:
  - columns `id`, `user_id` (foreign key to `users`, `ON DELETE CASCADE`), `provider`, `provider_subject`, `email_at_link`, `created_at`;
  - `UNIQUE(provider, provider_subject)` and `UNIQUE(user_id, provider)`.
  
  A generic table means issue #388 (Microsoft and Apple) won't need another schema change.
- Make `users.password_hash` nullable, so Google-only accounts can exist. This is additive and safe while the old code is still running during the release.

**OAuth flow (new `src/auth/google.ts`)**
- Use `openid-client` with authorization code flow plus PKCE, `state` and `nonce`, and validate the ID token. After matching or creating the user, call `req.login`, which regenerates the session. I prefer this over `passport-google-oauth20` because it supports PKCE and nonce and is actively maintained.
- After the first link, look users up by Google `sub`, never by email. Google emails can change, and Workspace addresses can be reassigned.
- `GET /auth/google` starts the flow. I'm making it a GET link, not a form POST, because Chrome applies CSP `form-action 'self'` to the redirect that follows a form POST, so a POST to Google would be blocked. Login CSRF is still prevented by `state`.
- `GET /auth/google/callback` finishes it. The existing POST CSRF middleware is unaffected.
- **SameSite issue.** `tb.sid` is `sameSite: 'strict'`, so the browser won't send it when Google redirects back. State stored in the session would be lost. To fix this:
  - store `state`, `nonce` and the PKCE verifier in a separate short-lived signed cookie, `tb.oauth` (`SameSite=Lax`, `httpOnly`, `secure`, 10 minutes, path `/auth/google`);
  - have the callback render a small "Signing you in…" page that then navigates to the app, rather than a 302. This makes sure the strict session cookie is sent on the next request.
  
  `tb.sid` itself stays strict.

**Account matching in the callback**
| Case | Result |
|---|---|
| Google `email_verified` is false | Reject with a message |
| Google `sub` already linked | Log in as that user |
| No link, email matches a verified account | Link, log in, send "Google was linked" email |
| No link, email matches an unverified account | Depends on your answer to decision 1 |
| No match | Create the user (`email_verified_at = now()`, `password_hash = NULL`, `display_name` from Google), then log in |

For the "end existing sessions" step: sessions live in `connect-pg-simple`, so I'll delete them with `sess->'passport'->>'user'`. That query will need porting if issue #412 (Redis sessions) goes ahead.

**Other auth code affected by password-less accounts**
- `password.ts` and the local strategy: if `password_hash` is NULL, fail login cleanly instead of passing NULL to argon2.
- `reset.ts`: no change in logic. For Google-only users, it works as "set a password".
- `security.ejs`: if there's no password, show "Set a password" (through the reset flow) instead of "Change password". Add a Google section with link and unlink. Only allow unlinking if a password exists. Linking from settings rejects a `sub` that is already linked to a different user.

**UI**
- Add a "Continue with Google" button to `login.ejs` and `signup.ejs`, following Google's branding guidelines and shown only when the flag is on.

**Config**
- In `config.ts`, require `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `APP_BASE_URL` (used for the redirect URI) only when the flag is on, so CI and previews boot without them.

## Testing and rollout
- **Tests:** add Jest and supertest coverage in `test/auth/google.test.ts`, with Google's token and JWKS endpoints stubbed. Cover every row in the table above, plus:
  - bad or missing `state`,
  - nonce mismatch,
  - sessions ended after an unverified link,
  - logging in with a NULL password hash,
  - unlink rules.
- The Playwright smoke tests stay as they are, because driving a real Google login in CI isn't practical.
- **Rollout:**
  1. Merge with the flag off everywhere.
  2. Turn it on in staging and test manually with real Google accounts: gmail, Workspace, and an existing unverified account.
  3. Turn it on in production after the consent screen is published and the privacy policy change is live.

Tell me your answers to the three decisions, or just "go with your recommendations", and I'll start the migration and code.

</details>

## B · 80%-STE prompt (paraphrased from a public tip)

<details>
<summary>Show the full reply (1367 words)</summary>

# Plan: "Sign in with Google" for Tallybook

I have not changed any files. Below is the plan for your approval. Six facts about the current system change the design, so I list them first.

## Facts that change the design

1. **A plain email match lets an attacker take over accounts.** About 9,000 accounts have never verified their email. An attacker can sign up with a victim's address and a password the attacker knows. If Google sign-in then links to that account by email alone, the victim uses an account the attacker can also open. For this reason, I key Google accounts on Google's `sub` (a stable user ID), not on email. A link to an existing account always needs proof.
2. **`sameSite: 'strict'` breaks the Google callback.** Google returns the user with a cross-site redirect, so the browser does not send `tb.sid`. Any OAuth `state` in the session is lost. Also, the redirect to the app after login arrives without the new cookie. To fix this:
   - Keep the OAuth `state`, nonce, and PKCE verifier in a separate cookie, `tb.oauth`. It is short-lived, signed, `httpOnly`, `secure`, and `SameSite=Lax`, with path `/auth/google`.
   - After login, the callback shows a small same-origin page. That page goes to the app with `<meta http-equiv="refresh">`. CSP does not block this.
   - `tb.sid` does not change.
3. **`password_hash` is `NOT NULL`.** Google-only users have no password, so a migration must make this column nullable. The login code must also accept a null value.
4. **Preview deploys cannot use Google sign-in.** Google needs an exact redirect URI for each host, and it does not accept wildcards. Previews use staging's config, so the button would show but fail. I hide the button if the request host is not the host in `GOOGLE_OAUTH_REDIRECT_URI`.
5. **The privacy policy does not cover this feature.** It says nothing about sign-in through another service. Google's consent screen also needs a privacy policy URL. Production launch must wait for your approval and counsel's review of `public/legal/privacy.html`. I will not edit that file.
6. **Only you can do the Google setup.** No OAuth client or consent screen exists, and only you have access to `tallybook-prod`.

The button is a plain link to `GET /auth/google`, not a form. This avoids a conflict with `form-action 'self'`, because Chrome applies that directive to redirects after a form submit.

## Account rules

| Google result | Tallybook state | Action |
|---|---|---|
| `email_verified` is false | any | Refuse, and show a clear message. |
| `sub` is already linked | any | Log in. |
| No user has this email | — | Create the user. Set `email_verified_at` to now and leave `password_hash` null. Link and log in. |
| A user has this email, and the email is verified | — | Show a link page. The user enters the Tallybook password, or gets a confirmation email. Then link and log in. |
| A user has this email, and the email is not verified | — | Send a confirmation email only. On confirm: link, set `email_verified_at`, clear the password, and end all other sessions for that user. Tell the user. |

The last row blocks the takeover in fact 1. If an attacker made the password, the attacker loses access.

Google-only users can set a password with the existing forgot-password flow. That flow already proves control of the email.

## Work, in order

### Step 0: Google setup (you)

1. In `tallybook-prod`, create an OAuth consent screen:
   - Type: External.
   - Scopes: `openid`, `email`, `profile` only. These are non-sensitive scopes, so Google does not do a security review.
   - Fields: app name, support email, home page, privacy policy URL, and authorized domain `tallybook.example.com`.
2. Create two "Web application" OAuth clients:
   - Non-production, with redirect URIs `http://localhost:3000/auth/google/callback` and `https://staging.tallybook.example.com/auth/google/callback`.
   - Production, with redirect URI `https://app.tallybook.example.com/auth/google/callback`.
3. Put the non-production client ID and secret in staging's environment settings and in the shared vault. Put the production values in production's settings later, in step 3.
4. Before launch, set the publish status to "In production". In "Testing" status, only listed test users can sign in.

While you are in that project, also look for old API keys from the autocomplete experiment. If you find keys that nobody uses, delete them.

### Step 1: Code (one PR, flag off)

- **Migration** in `db/migrations/`:
  - Create the table `user_identities` with these columns: `id`, `user_id` (FK to `users`, `ON DELETE CASCADE`), `provider`, `subject`, `email` (citext, at link time), and `created_at`.
  - Add `UNIQUE(provider, subject)` and `UNIQUE(user_id, provider)`. This shape also works for Microsoft and Apple in #388.
  - Change `users.password_hash` to `DROP NOT NULL`. This is a metadata-only change, so the table lock is short.
  - The down migration fails if a user has no password. I document that limit in the migration.
- **Dependency:** add `openid-client`. It checks the ID token signature, nonce, and PKCE. I do not use `passport-google-oauth20`, because it does not check an ID token.
- **`src/config.ts`:** add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_OAUTH_REDIRECT_URI`. They are required only if the flag is on.
- **`src/flags.ts`:** add `GOOGLE_SIGNIN`, which comes from `FEATURE_GOOGLE_SIGNIN`.
- **`src/auth/google.ts` (new):** the start route, the callback, the link page, and the email confirm route. Each login calls `req.login`, which makes a new session ID.
- **`src/auth/passport.ts` and `src/auth/password.ts`:** if `password_hash` is null, the local login fails with the same generic error as a wrong password.
- **`src/auth/reset.ts`:** allow a reset for Google-only users. The reset sets their first password.
- **Views:**
  - Add the button to `login.ejs` and `signup.ejs`.
  - Add `auth/google-link.ejs` and `auth/google-continue.ejs`.
  - Add a link-confirm email template.
  - In `security.ejs`, show the linked Google account. Add "Connect" and "Disconnect". "Disconnect" works only if a password exists, so a user cannot lose all ways to log in.
- **Tests:** add `test/auth/google.test.ts`, which uses a fake OIDC issuer with a local key set. The test cases are:
  - Each row of the account rules table.
  - A bad `state`, a bad nonce, an expired `tb.oauth` cookie, and a wrong audience.
  - A local login with a null `password_hash`.
  - A reset for a Google-only user.
  - The end of other sessions after an unverified-account link.
  - A hidden button on a host that does not match.
- **E2E:** add a Playwright check that the button shows on staging. It also checks that `/auth/google` redirects to `accounts.google.com` with the correct `client_id` and `redirect_uri`. A real Google login is not automated, because Google blocks bots.

We store only the Google `sub`, the email, and the name for new accounts. We do not store Google access tokens or refresh tokens.

### Step 2: Staging

1. Merge the PR. The flag is off, so production behavior does not change.
2. Set `FEATURE_GOOGLE_SIGNIN=true` on staging. You or the lead engineer must do this.
3. I test all table rows by hand in Chrome, Firefox, and Safari, because their cookie rules differ.

### Step 3: Production

1. Publish the approved privacy policy.
2. You or the lead engineer set the production client values and the flag.
3. Promote the staging build.
4. I watch the callback errors in the logs for one week.

CAUTION: If you turn the flag off after launch, Google-only users cannot log in until they reset their password. Use the flag for an emergency stop only.

## Decisions I need from you

1. **Link rule.** I recommend the strict rule above (password or email confirmation). The other option is an automatic link if both emails are verified. That option has fewer steps, but it is less safe for custom-domain addresses. These addresses are about 45% of your users, and a domain can change owners.
2. **Connect and disconnect on the Security page.** I recommend that we include them now, because the work is small.
3. **Privacy policy.** Do you want me to write draft text for you and counsel? I will put it in the PR description, not in `privacy.html`.
4. **Google project.** I recommend `tallybook-prod` with two clients. Tell me if you prefer a new project.

After you approve, I start with the migration and `src/auth/google.ts`. I do not need the Google client values until I test on staging.

</details>

## C · andrej-karpathy-skills CLAUDE.md (multica-ai, unofficial)

<details>
<summary>Show the full reply (1098 words)</summary>

# Plan: Sign in with Google

I haven't changed anything. Here's the plan, plus a few decisions I need from you.

## Blockers outside the code

1. **Google OAuth client (founder only).** No OAuth client or consent screen exists yet, and only the founder can create them. They would need to:
   - Configure an External consent screen with scopes `openid email profile` only. Include the app name, support email, homepage, a privacy policy URL, and `tallybook.example.com` as an authorized domain.
   - Create two Web OAuth clients:
     - **Production:** redirect URI `https://app.tallybook.example.com/auth/google/callback`
     - **Dev/staging:** redirect URIs `http://localhost:3000/auth/google/callback` and `https://staging.tallybook.example.com/auth/google/callback`
   - Decide whether to reuse `tallybook-prod`. I'd use a fresh project, or at least confirm the leftover autocomplete API keys are cleaned up.
   - Have the founder or lead engineer set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the hosting settings, and put the dev client's values in the vault.
2. **Privacy policy.** `public/legal/privacy.html` says accounts use email and password only, and says nothing about receiving data from another service. Google's consent screen also needs a policy link. Production launch has to wait for the founder and outside counsel to approve an update. I can write a factual summary for counsel of what we'd receive and store: Google account ID (`sub`), email, whether the email is verified, and name. I won't edit the legal file myself.
3. **Preview deploys won't work with Google.** Google doesn't allow wildcard redirect URIs, so `pr-<n>.preview…` can't complete the flow. I'll leave the feature flag off there and test on local and staging.

## Account linking

This is the main security decision. The risk is pre-account hijacking. About 9,000 accounts have never verified their email, so an attacker could already have signed up with a victim's address and set a password. If we auto-link by email when the real owner later uses Google, the attacker's password still works on that account.

**Recommendation:**
- **Match on Google's `sub`, never on email.**
- **Google email matches an existing account that isn't linked yet:** don't log them in. Show "An account with this email exists. Enter your Tallybook password to link Google." Include a "forgot password" link, which goes through the existing emailed reset. That reset replaces any password an attacker set.
- **Logged-in users** can link or unlink Google from `account/security.ejs`. Unlinking is blocked if it would leave the account with no way to log in.
- **No matching email:** create a new account with no password. Set `email_verified_at` only if Google's `email_verified` claim is true.
- **Email when Google is linked:** send a short "Google sign-in was linked to your account" notice. It's cheap and catches the takeover case. Tell me if you'd rather drop it.

## Technical constraints

- **`sameSite: 'strict'` on `tb.sid`.** Google's redirect back is a cross-site navigation, so the session cookie isn't sent on the callback.
  - I'll store `state`, `nonce` and the PKCE verifier in a separate short-lived (10 min), signed, `httpOnly`, `sameSite=lax` cookie, `tb.oauth`.
  - A new `tb.sid` set during a cross-site redirect chain may also be withheld on the next hop. So the callback will render a small same-origin page that continues to the dashboard, rather than issuing a 302. I'll confirm the real behavior with Playwright before deciding the final approach.
- **CSP `form-action 'self'`.** Chrome applies it to redirects after a form submit. A POST form that redirects to `accounts.google.com` would be blocked, so the button will be a plain GET link to `/auth/google`. That's safe because login CSRF is prevented by the `state` check on the callback. The CSP stays as it is, and the existing CSRF middleware is unaffected because the callback is a GET.
- **Session fixation.** Regenerate the session on Google login. I'll check whether our Passport version already does this in `req.login`.
- **Library.** I'd use `openid-client` (PKCE, nonce and ID-token validation built in), called from a small route module. Passport only needs `req.login()`, so no new Passport strategy.

## Changes

1. **Migration in `db/migrations/`** → verify: migrate up/down locally; existing tests pass.
   - New table `user_identities (id, user_id FK → users ON DELETE CASCADE, provider text, subject text, email_at_link citext, created_at, UNIQUE(provider, subject))`. I'm using a table rather than a `google_sub` column because #388 will need the same structure, and it costs about the same.
   - `ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL`. This is a metadata-only change with a brief lock.
2. **Null passwords** → verify: new tests.
   - `password.ts` and the local strategy reject login when the hash is null, with a generic error and no crash.
   - The `security.ejs` change-password form becomes "set a password" when the user has none.
   - The reset flow already sets a password, so Google-only users can add one through it.
3. **Config and flag** → verify: `tsc`; the app boots with the flag off and no Google variables set.
   - `config.ts`: optional `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, required only when `FEATURE_GOOGLE_SIGNIN` is on.
4. **`src/auth/google.ts`**, mounted from `routes.ts` → verify: supertest against a stubbed issuer.
   - Routes: `GET /auth/google`, `GET /auth/google/callback`, `GET/POST /auth/google/link` (password-confirm step, CSRF-protected), and `POST /account/google/unlink`.
5. **Views** → verify: e2e screenshot check on staging.
   - "Continue with Google" button on `login.ejs` and `signup.ejs`, following Google's branding guidelines and shown only when the flag is on.
   - Linked status on `security.ejs`.
6. **Tests in `test/auth/google.test.ts`.** Cases:
   - Bad or missing `state`, nonce mismatch, `email_verified=false`.
   - Existing `sub` logs in.
   - Matching email requires the password, the wrong password fails, and the email is never auto-linked.
   - New user gets a null hash.
   - Password login with a null hash fails cleanly.
   - Unlinking the last login method is blocked.
   - Session ID changes after login.
7. **Rollout.**
   - Merge with the flag off.
   - Turn it on in staging and test with real Google accounts: one Gmail and one custom-domain Google account.
   - Turn it on in production only after the privacy policy update is live.
   - **Rollback:** if we revert the code after Google-only users exist, they can't log in until we re-enable it or they reset their password. Step 2 makes sure the old password path rejects null hashes rather than crashing.

**Out of scope:** Microsoft/Apple (#388), Redis sessions (#412), and requiring email verification for password logins.

## Decisions I need from you

1. Approve the linking policy (password confirmation, no auto-link by email) and the link notification email.
2. Will the founder set up the OAuth clients? Which GCP project should we use?
3. OK that production launch waits on the privacy policy update, and that previews won't support Google sign-in?

Once you approve, I'll start with steps 1–3.

</details>

## D · plan-first

**What the approver reads** (1179 words):

I've written the two planning documents below. No code changes yet.

- Human doc: `docs/human/2026-10-07-google-sign-in.md`
- Plan doc: `docs/plan/2026-10-07-google-sign-in.md`

**Summary**

- **The plan:** I'll add Google sign-in and signup behind an on/off switch. You can connect Google to an existing account, and accounts made only with Google still work with the password features.
- **Takeover risk:** I connect an existing account automatically only when both Tallybook and Google have confirmed the email address. About 9,000 accounts have never verified their email, and someone else could have created them with that address.
- **Two browser limits:** Your strict session cookie and the form rule in your security policy would both break a standard Google sign-in. I work around both without weakening either one.
- **Three decisions for you:** when to connect accounts automatically, which Google Cloud project to use, and whether production waits for a privacy policy update.
- **Founder tasks:** Only the founder can set up Google Cloud and the server settings, and only the founder can arrange the privacy policy change. That is about 1.5 hours of their time.

Reply "approve" to start, or something like "1: alternative" to change one decision.

# Let people sign in to Tallybook with their Google account

> Status: Awaiting approval · v1 · 2026-10-07
>
> Plan doc for the agent: [../plan/2026-10-07-google-sign-in.md](../plan/2026-10-07-google-sign-in.md)

## What this does

1. **Add Google sign-in and signup**
   - Purpose: People can sign in or create an account with Google instead of a password. Without this, every user must create and remember a Tallybook password.
   - When done:
     - The login and signup pages show a "Sign in with Google" button when the feature is on (your requirement).
     - A new person who uses the button gets a new account and is logged in. Tallybook marks their email address as verified.
     - A person who already connected Google gets the same account each time they use the button.
     - All automated checks pass, and I open a pull request for review.

2. **Connect Google to existing accounts** (depends on feature 1)
   - Purpose: Current users can use Google with the account they already have (your requirement). Without care, a stranger could take over an account through a matching email address.
   - When done:
     - A user whose email address both Tallybook and Google have confirmed is connected automatically and logged in.
     - Other users with a matching address see a message. It tells them to log in with their password and connect Google on the Security page.
     - On the Security page, a logged-in user can connect or disconnect Google.
     - Tallybook emails the user each time Google is connected to their account.

3. **Keep passwords working for Google-only accounts** (depends on feature 1)
   - Purpose: Accounts made with Google have no password. Without changes, the password pages could fail or lock these users out.
   - When done:
     - A Google-only user can get a "set a password" email from the Security page or from "Forgot password".
     - A password login on a Google-only account shows the normal "wrong email or password" error.
     - A user cannot disconnect Google until their account has a password.

Not doing: Microsoft or Apple sign-in, Google sign-in on pull-request preview sites, and changes to the privacy policy text.

## Decisions for you

1. **When should Tallybook connect Google to an existing account automatically?** (feature 2, can undo)
   - Recommended: Connect only when Tallybook has verified the address and Google controls it, as with Gmail or Google Workspace. About 9,000 accounts never verified their address, so a stranger could have created some of them.
   - Alternative: Connect every matching account automatically. For unverified accounts, I would also remove the old password and log out all other sessions.

2. **Which Google Cloud project should hold the Google sign-in settings?** (can undo)
   - Recommended: Use the existing tallybook-prod project with two clients. A client is the set of keys that Google gives to one app. One client serves production, and one serves local and staging.
   - Alternative: Create a new, empty project only for sign-in. This keeps sign-in apart from the old autocomplete experiment.

3. **Should Google sign-in stay off in production until counsel approves a privacy policy change?** (feature 1, hard to undo)
   - Recommended: Yes. The current policy says nothing about sign-in through another service. Google also asks for a privacy policy link on its consent screen.
   - Cost: After people create accounts with Google in production, turning the feature off locks them out. They can get back in only through "Forgot password".

To accept all recommendations, reply "approve" to start. To change one and keep the other recommendations, reply like "1: alternative" to start.

## What you need to do

Only the founder has access to Google Cloud and the server settings. If you are not the founder, please give these tasks to the founder.

- Before the staging test, set up the Google consent screen and the two clients in Google Cloud. The plan doc lists each value. This takes about 30 minutes.
- After that setup, add the Google keys to the staging server settings and to the team vault. This takes about 10 minutes.
- After the pull request reaches staging, sign in on staging with a real Google account. This takes about 10 minutes.
- Before the production launch, ask counsel to update the privacy policy. I list the data facts for counsel in the plan doc. Then add the production keys and turn the feature on. Your part takes about 40 minutes.

## Impact

- Changes: About 15 existing files change:
  - the login, signup, and Security pages;
  - the code for login, password reset, settings, and app setup;
  - the list of libraries.
- Adds:
  - A new database table records which Google account belongs to which Tallybook account. Google gives each person a fixed account ID, and I match on that ID.
  - A new library, openid-client, checks every answer from Google. It handles the security checks that Google requires.
  - An on/off switch in the server settings controls the feature, so you can turn it on without a new release.
  - Three new server settings hold the Google keys and the return address. The app needs them to talk to Google.
  - A new email tells a user when Google is connected to their account. It warns them if someone else did it.
  - About 3 new test files check the new flows without contacting Google.
- Removes: The database no longer requires a password for every account. I delete no data.
- Visible behavior:
  - When the switch is on, the login, signup, and Security pages show Google options.
  - Tallybook receives each Google user's ID, name, and email address. It never stores Google photos or Google access keys.
  - Accounts made with Google count as verified and have no password at first.
  - The database change runs on staging when the pull request merges, and on production at the next promotion.

Estimated time: AI about 6 hours; you about 1.5 hours.

<details>
<summary>Show the plan doc for the agent (2750 words)</summary>

# Plan: Google sign-in for Tallybook

Human doc: [../human/2026-10-07-google-sign-in.md](../human/2026-10-07-google-sign-in.md)

## 1. Status

Awaiting approval · v1 · 2026-10-07

## 2. Goals and completion criteria

Feature numbers match the human doc. "Tests" means Jest + supertest under `test/auth/`, run against the fake OIDC provider (step 4). Nothing contacts Google in CI.

**F1 Add Google sign-in and signup**
- 1.1 Flag on + Google config set + request host == host of `GOOGLE_CALLBACK_URL` → `login.ejs` and `signup.ejs` render a "Sign in with Google" `<a href="/auth/google">` link.
  - Flag off, or host mismatch (preview deploys) → no button, and `/auth/google*` returns 404.
- 1.2 Callback with valid code, unknown `sub`, unknown email and `email_verified=true`:
  - inserts a `users` row: `password_hash` NULL, `email_verified_at`=now(), `display_name`=Google `name` or email local part;
  - inserts a `user_identities` row;
  - ends with the user logged in.
- 1.3 Callback with a known `sub` logs into the linked user and updates `last_used_at`.
- 1.4 The callback fails safely in each of these cases:
  - Cases: missing `tb.oauth` cookie, state mismatch, nonce mismatch, ID token with bad iss/aud/exp/signature, `email_verified=false`, Google error param.
  - Result in every case: redirect to `/login?error=google`, generic message, no session, no DB rows.
- 1.5 After a successful callback, the response sets `tb.sid` and returns 200 `auth/continue.ejs`, which uses `<meta http-equiv="refresh">` to go to the target.
  - The next same-site request is authenticated: a test sends the cookie to `/dashboard` and gets 200.
- 1.6 The session ID changes on Google login (no session fixation).
- 1.7 `returnTo` accepts only relative paths starting with a single `/`. Anything else falls back to the dashboard.

**F2 Connect Google to existing accounts**
- 2.1 Auto-link at sign-in only when all three hold (Decision 1 recommended). Then: insert the identity, log in, send the "Google connected" email.
  - `users.email_verified_at IS NOT NULL`;
  - Google `email_verified=true`;
  - email domain is `gmail.com` or `googlemail.com`, OR the `hd` claim equals the email domain.
- 2.2 Email matches an existing user but 2.1 fails → no link, no session.
  - The user is redirected to `/login` with: "An account with this email already exists. Log in with your password, then connect Google on the Security page."
- 2.3 A logged-in user starts `GET /auth/google/link` from `security.ejs`.
  - Callback → the identity links to that user even if the Google email differs.
  - If the `sub` is already linked to another user → error, no change.
  - On success, the "Google connected" email is sent.
- 2.4 `POST /account/security/google/unlink` (CSRF-protected):
  - deletes the identity when `password_hash IS NOT NULL`;
  - otherwise returns 400 with the message "Set a password before you disconnect Google."

**F3 Keep passwords working for Google-only accounts**
- 3.1 Password login for a user with NULL `password_hash` gives the same response as a wrong password, after a dummy argon2 verify for timing parity. It does not throw.
- 3.2 Forgot-password for a Google-only user sends the reset email. The reset sets `password_hash`, and the next password login succeeds.
- 3.3 `security.ejs` for a NULL `password_hash` shows a "Send me a link to set a password" button, which posts to the existing reset flow, instead of the change-password form.

**General**
- G.1 `npx eslint .`, `npx tsc --noEmit` and `npm test` pass locally; CI is green on the PR.
- G.2 The migration runs up → down → up cleanly on a local DB seeded with one Google-only user.
- G.3 The PR from `feat/google-sign-in` to `main` is open, with a description that links both docs.

## 3. Background and constraints

- Stack: Node 20, Express 4, EJS, Passport (local only), express-session + connect-pg-simple, Postgres 15, Knex migrations, zod config, flags from `FEATURE_<NAME>`.
- The `tb.sid` cookie is `sameSite: 'strict'`.
  - The return navigation from accounts.google.com is cross-site, so `tb.sid` is not sent to the callback. OAuth state stored in the session would be lost.
  - Strict cookies are also withheld on a 302 that continues a cross-site navigation, so a plain redirect after the callback would look logged-out.
- helmet CSP has `form-action 'self'`, and Chrome applies form-action to redirects after a form submit. A POST form that 302s to Google is blocked, so the flow must start with a GET link.
- The CSRF middleware checks every POST. The callback is a GET; unlink is a POST and uses the existing token.
- Google `sub` is stable per Google account and the same across OAuth clients. Match on `sub`; use email only for the first link.
- Login has never required verification. About 9,000 of 40,000 accounts are unverified, which makes account pre-hijacking possible if linking trusts the email alone.
- Google forbids wildcard redirect URIs, so `pr-<n>.preview` hosts cannot complete sign-in.
- `public/legal/privacy.html` (March 2025) does not mention third-party sign-in. The founder approves changes; outside counsel reviews them. The Google consent screen requires a privacy policy URL.
- Only the founder (Owner of `tallybook-prod`) can create OAuth clients. Only the founder and the lead engineer can edit hosting env settings.
- `main` is protected: 1 approving review + green CI. A merge deploys to staging and runs `npm run migrate`. Production is a manual promotion.
- Must not:
  - change `tb.sid` settings or the CSP;
  - touch the session store (#412);
  - add Microsoft/Apple (#388);
  - require verification for password login;
  - edit `privacy.html`;
  - merge the PR, promote to production, or edit hosting env settings;
  - store Google tokens or the profile picture.

## 4. Approach and key decisions

- **OIDC library:** `openid-client` (panva), used directly in our own route handlers, then `req.login()` from Passport. It provides discovery, PKCE, state, nonce and ID-token validation.
  - Rejected `passport-google-oauth20`: plain OAuth2 + userinfo, no nonce, and it keeps state in the session, which the strict cookie breaks.
  - Rejected the openid-client Passport Strategy: same session-state problem.
  - Rejected Google Identity Services / One Tap: needs CSP `script-src`/`frame-src` for accounts.google.com.
- **ESM:** openid-client v6 is ESM-only; load it with a real dynamic `import()`. If TS compiles that to `require()` and it fails, use openid-client v5.x (CJS) and log a small deviation.
- **Scopes:** `openid email profile`.
  - Store: `sub`, email at link time, `created_at`, `last_used_at`.
  - Use `name` once, as the initial `display_name`.
  - Discard `picture`, access tokens and refresh tokens.
- **Transaction cookie `tb.oauth`:**
  - Attributes: signed with `COOKIE_SIGNING_KEY`, httpOnly, secure in prod, `sameSite: 'lax'`, path `/auth/google`, maxAge 10 min.
  - Content: state, nonce, PKCE verifier, intent (`login`|`link`), returnTo, and for link: user_id + session id.
  - Cleared at the callback.
- **Link intent:** at `/auth/google/link` (same-site, so `tb.sid` is present), record the user_id and sid in `tb.oauth`. At the callback, `sessionStore.get(sid)` must exist and its passport user must equal user_id; otherwise reject.
- **After the callback:** `req.session.regenerate` → `req.login` → render `auth/continue.ejs` with a meta refresh plus a visible link. The meta refresh is a same-site navigation, so `tb.sid` is sent.
  - Rejected: switching `tb.sid` to lax, because it weakens defense in depth.
- **Linking policy:** as in F2 (Decision 1). The gmail/`hd` rule follows Google's guidance that only Gmail and Workspace (`hd`) addresses are authoritatively controlled by Google.
  - Logged-in linking (2.3) is always allowed because the user has proved both sides.
- **Schema:**
  - New table `user_identities`:
    - columns: `id bigserial pk`, `user_id` fk → users `ON DELETE CASCADE`, `provider text`, `provider_subject text`, `email citext`, `created_at`, `last_used_at`;
    - constraints: unique(`provider`,`provider_subject`), unique(`user_id`,`provider`).
  - `users.password_hash` DROP NOT NULL. This is metadata-only and instant on 40k rows.
  - Rejected a random placeholder hash: it hides the "no password" state that F3 needs.
  - Rejected a `google_sub` column on `users`: #388 would need one column per provider.
- **Down migration:** set NULL `password_hash` rows to an argon2 hash of 32 random bytes, then SET NOT NULL, then drop `user_identities`.
- **Config:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_CALLBACK_URL`. zod requires them when `FEATURE_GOOGLE_SIGNIN=true`; startup fails otherwise. Discovery is lazy and cached; on failure, show a generic error and log it.
- **Preview hosts:** the button shows and the routes serve only when `req.hostname` equals the host of `GOOGLE_CALLBACK_URL`.
- **Button:** static markup + local `public/img/google-g.svg` per Google branding guidelines. No external requests.
- **Email notice:** a new "Google connected" template, sent through the existing SMTP mailer, placed next to the existing verify/reset templates.
- **Tests:** `test/helpers/fake-oidc.ts` is a local Express server on a random port that serves discovery, JWKS and token endpoints, with RSA keys from `jose`. Add `jose` as an explicit devDependency.
- **Google Cloud (Decision 2 recommended):** two OAuth clients in `tallybook-prod`.
  - "Tallybook production": redirect `https://app.tallybook.example.com/auth/google/callback`.
  - "Tallybook dev and staging": redirects `http://localhost:3000/auth/google/callback` and `https://staging.tallybook.example.com/auth/google/callback`.
- **Production gate (Decision 3 recommended):** `FEATURE_GOOGLE_SIGNIN` stays unset in production until counsel approves a privacy policy change.
- **Git:** branch `feat/google-sign-in`, logical commits, push, open a PR. A reviewer merges.

## 5. Change list and Impact

New:
- `db/migrations/<timestamp>_google_identities.ts`
- `src/auth/google.ts`: OIDC client and routes `/auth/google`, `/auth/google/link`, `/auth/google/callback`
- `src/auth/identities.ts`: data access and linking policy
- `src/views/auth/continue.ejs`
- `src/views/auth/_google-button.ejs`
- `public/img/google-g.svg`
- "Google connected" email template, next to the existing email templates
- `test/helpers/fake-oidc.ts`
- `test/auth/google.test.ts`
- `test/auth/google-link.test.ts`
- `test/auth/google-only-password.test.ts`

Modified:
- `package.json`, `package-lock.json`
- `src/config.ts`, `src/flags.ts`, `src/app.ts`
- `src/auth/passport.ts`: NULL hash handling
- `src/auth/reset.ts`: works for NULL hash
- `src/auth/routes.ts`: login error message
- `src/views/auth/login.ejs`, `src/views/auth/signup.ejs`, `src/views/account/security.ejs`
- the route handler that renders `security.ejs`: add the unlink route
- `.env.example`, if it exists

Deleted: none.

Impact:
- Changes:
  - login, signup and Security pages;
  - auth, reset, config, flags and app setup code;
  - dependencies;
  - about 15 existing files.
- Adds:
  - `user_identities` table: maps Google `sub` to a user;
  - `openid-client` dependency: OIDC validation;
  - `jose` devDependency: fake provider in tests;
  - `FEATURE_GOOGLE_SIGNIN` flag;
  - 3 env settings: Google keys and callback URL;
  - "Google connected" email: warns about unexpected links;
  - about 3 test files.
- Removes: the NOT NULL constraint on `users.password_hash`. No data is deleted.
- Visible behavior:
  - Google options on login, signup and Security when the flag is on;
  - Tallybook receives `sub`, name, email, `email_verified` and `hd`, and does not store the picture or tokens;
  - Google-created accounts are verified and have no password;
  - new security email;
  - the migration runs on staging at merge and on production at the next promotion.

## 6. Steps

0. Confirm the working tree is clean apart from the two docs (git rule 3). Check `git config user.name/user.email`; ask the user if either is missing. Create `feat/google-sign-in`. Set both docs to In progress.
1. `npm i openid-client` and `npm i -D jose`.
   - Verify: a scratch import in `src/auth/google.ts` compiles (`npx tsc --noEmit`) and loads under `npm test`. Use the v5 fallback if needed.
2. Write the migration.
   - Verify on local DB: `npm run migrate`, rollback, migrate again (G.2), with one seeded NULL-hash user.
3. Add config + flag.
   - Verify: the app starts with the flag off and no Google vars. It refuses to start with the flag on and vars missing (test).
4. Write `fake-oidc.ts`.
   - Verify: a helper self-test fetches discovery and gets a signed ID token.
5. Write `identities.ts` + linking policy.
   - Verify: unit tests for 2.1/2.2 rule combinations (verified/unverified × gmail/hd/custom).
6. Write the F1 routes + `continue.ejs` + button partial + host check.
   - Verify: tests 1.1–1.7.
7. Write link start, callback link branch, unlink route, Security page section, email.
   - Verify: tests 2.1–2.4. The mailer mock receives one "Google connected" email per link.
8. Add F3 changes in `passport.ts`, `reset.ts` and `security.ejs`.
   - Verify: tests 3.1–3.3, and existing `test/auth/` still passes.
9. Manual local check with the flag on against the fake provider: button, sign-up, continue page, logged-in dashboard. If the founder has already created the dev client, repeat with real Google. Otherwise, log "real-Google check deferred to staging".
10. Run `npx eslint .`, `npx tsc --noEmit` and `npm test` (G.1).
11. Set both docs to Done and write the execution log. Commit in logical units, staging only listed files with no `git add -A`. Push the branch, open the PR linking both docs, and wait for CI green (G.3).

Total estimated time: about 6 hours.

## 7. Risk handling and stop conditions

Removed by changing the approach:
- Pre-hijack via unverified accounts (linking policy, 2.1).
- Recycled custom-domain addresses (gmail/`hd` rule).
- Strict cookie dropping OAuth state (`tb.oauth` lax cookie + continue page).
- CSP blocking redirect (GET link).
- Preview hosts showing a broken button (host check).
- Login CSRF (state + nonce + PKCE).
- Open redirect (1.7).
- Lockout on unlink (2.4).

Turned into user decisions:
- Linking policy (1).
- Google Cloud project (2).
- Production gate and legal (3).

Stop conditions (stop and ask the user):
- Neither openid-client v6 nor v5 loads in this build setup.
- The work would need any change to the CSP, `tb.sid` settings or session store.
- `sessionStore.get(sid)` cannot confirm link intent.
- More than 5 existing test files need changes beyond those listed.
- The mailer cannot send a new template without a refactor.
- Google consent-screen requirements (for example brand verification) would change the scopes or the data facts in section 10.

Small deviations, logged in the execution log:
- The `security.ejs` route lives in a different file than expected.
- `.env.example` is absent.

Not undone by reverting the commit:
- Migration: stays applied. Recovery: run the down migration.
- `user_identities` rows and Google-only users: Recovery: unset `FEATURE_GOOGLE_SIGNIN`. Google-only users then use "Forgot password", which works with the old code because reset just writes `password_hash`. Then run the down migration, which gives NULL rows a random hash.

## 8. Not doing

- Microsoft/Apple sign-in (#388). The table is provider-generic, but no code for them.
- Redis sessions (#412).
- Google sign-in on preview deploys.
- Editing `privacy.html` or any legal text.
- One Tap / Google Identity Services JS.
- Requiring email verification for password login, or bulk changes to unverified accounts.
- Storing Google tokens or the profile photo, or calling other Google APIs.
- Merging the PR, staging/production env changes, production promotion.
- New Playwright e2e for Google, since real Google login cannot run in CI.

## 9. Decisions for the user

1. **Auto-link policy** (F2, can undo).
   - Recommended: link only when Tallybook has verified the email and Google controls it (gmail/`hd`), because about 9,000 unverified accounts could be attacker-created.
   - Alternative: link every match where `email_verified=true`; for unverified accounts, also null `password_hash` and delete the user's other sessions.
2. **Google Cloud project** (can undo; `sub` is the same across clients).
   - Recommended: reuse `tallybook-prod` with two clients (prod; dev+staging) to keep one project to manage.
   - Alternative: a new dedicated project, to keep sign-in apart from the abandoned experiment.
3. **Production gate** (F1, hard to undo).
   - Recommended: keep the flag off in production until counsel approves a privacy policy change. The policy is silent on third-party sign-in, and the consent screen needs a policy URL.
   - Cost: once Google-only users exist in production, turning the feature off locks them out until they use "Forgot password".

## 10. What the user needs to do

The founder does all of these; if the user is not the founder, they hand them over.

1. Google Cloud setup, about 30 min, before the staging test:
   - In `tallybook-prod` (per Decision 2), configure the OAuth consent screen:
     - type External;
     - app name "Tallybook";
     - support email;
     - homepage `https://app.tallybook.example.com`;
     - privacy policy URL `https://app.tallybook.example.com/legal/privacy.html`;
     - authorized domain `tallybook.example.com`;
     - scopes `openid`, `email`, `profile`.
   - Create 2 Web OAuth clients with the redirect URIs in section 4.
   - Publish the app to production status. Google may ask for brand verification.
2. Staging keys, about 10 min: set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_CALLBACK_URL=https://staging.tallybook.example.com/auth/google/callback` and `FEATURE_GOOGLE_SIGNIN=true` in staging env settings. Put the dev/staging client in the team vault.
3. Staging check, about 10 min, after the merge: sign up with a fresh Google account, sign out, sign in again; connect Google from Security on a password account.
4. Production launch, about 40 min:
   - Send counsel the data facts below and get the privacy policy change approved.
   - Set the production client vars + flag, then promote.
   - Data facts for counsel:
     - Received: Google account ID, email, whether Google verified it, name, Workspace domain.
     - Stored: account ID, email at connection time, connection/last-use timestamps, name as initial display name.
     - Not stored: photo, Google tokens, Google password.
     - No access to Gmail, Drive, contacts or other Google data.
     - Used only for sign-in.

## 11. Change log

- v1 · 2026-10-07: first draft.

## 12. Execution log

none
=== END ===

</details>

## E · Plan + short summary (ablation)

**What the approver reads** (1717 words):

# Plan: "Sign in with Google" for Tallybook

Nothing in the app has changed yet. The only file I've written is the approver summary that `CLAUDE.md` asks for. It's at the end, uncommitted.

## The constraints

1. **Your session cookie blocks the usual OAuth flow.** `tb.sid` is `sameSite: 'strict'`. When Google redirects back to `/auth/google/callback`, the browser treats that as a cross-site navigation and doesn't send `tb.sid`. It also withholds the cookie on any further redirect in that chain. So OAuth state can't live in the session, and a plain `302 → /dashboard` after login would land the user logged out.
2. **Linking by email can enable account takeover.** Login has never required verification, and about 9,000 accounts are unverified. An attacker could have registered `[REDACTED-EMAIL]` with their own password. If we auto-link the victim's Google login to that account, the attacker keeps a working password on it. Some Google accounts also use non-Gmail addresses that Google isn't authoritative for.
3. **Google doesn't allow wildcard redirect URIs**, so `pr-<n>.preview…` deploys can't complete the flow.
4. **`password_hash` is NOT NULL**, but Google-only users won't have a password.
5. **CSP `form-action 'self'`** blocks a form POST that redirects to `accounts.google.com`. The button must be a plain link.
6. **External dependencies.** Only you can configure Google Cloud, and the privacy policy has to change before launch, which goes through you and counsel.

## Design

**Library:** `openid-client`, using authorization code flow with PKCE, `state` and `nonce`. It validates the ID token's signature, `iss`, `aud`, `exp` and nonce. Scopes are `openid email profile` only. These are non-sensitive scopes, so Google's restricted-scope review isn't needed.

**Routes** (in a new `src/auth/google.ts`, mounted from `src/auth/routes.ts`):
- `GET /auth/google?intent=login|link`
  - Generates state, nonce and PKCE verifier.
  - Stores them, plus the intent and a return path, in a short-lived signed cookie `tb.oauth`. That cookie is `httpOnly`, `secure`, **`sameSite: 'lax'`**, 10-minute lifetime, scoped to `/auth/google`.
  - Redirects to Google.
  - For `link`, it requires an authenticated session and records the user id in `tb.oauth`.
- `GET /auth/google/callback`
  - Verifies `state` against `tb.oauth`, exchanges the code, validates the ID token and clears `tb.oauth`.
  - Applies the linking rules below.
  - Calls `req.session.regenerate()` and logs the user in.
  - Returns a **200 page that does a same-site navigation** (meta refresh plus a fallback link) to the destination, so `tb.sid` is sent on the next request.
- No changes to the CSRF middleware are needed. The callback is a GET, and state is the CSRF protection for it.

**Data** (one Knex migration, backward-compatible with the running version):
- New table `user_identities`:
  - Columns: `id`, `user_id` (FK, cascade), `provider`, `provider_subject`, `email_at_link`, `created_at`, `last_used_at`.
  - Unique on `(provider, provider_subject)`, and unique on `(user_id, provider)`.
  - Lookups key on Google's `sub`, never on email. The table is generic, so issue #388 (Microsoft/Apple) can reuse it.
- `users.password_hash` becomes nullable.

**Linking rules on callback:**
1. If `sub` is already linked, log in as that user.
2. If not linked and no user has that email, create a user with `password_hash = NULL` and `email_verified_at = now()`. The email must be Google-verified.
3. If not linked and a user with that email exists, auto-link **only if all three hold**:
   - the Google `email_verified` claim is true;
   - the email is authoritative, meaning `@gmail.com` or an `hd` (Workspace) claim matching the domain;
   - the local account has `email_verified_at` set.

   Otherwise, show: "An account with this email exists. Log in with your password, then connect Google from Security settings." The forgot-password flow covers users who no longer know their password.
4. For `intent=link`, attach the identity to the logged-in user. This fails if the `sub` already belongs to someone else.

**Google-only accounts:**
- `password.ts` and the local strategy treat a null hash as "no password". There's no argon2 call and no crash. The login form says "This account uses Google sign-in."
- `reset.ts` lets these users *set* a password.
- `security.ejs` shows "Set password" instead of "Change password" when there's no hash. It also gets "Connect / Disconnect Google". Disconnect is only allowed if a password exists.
- I'll check that a password reset destroys the user's other sessions in the `session` table. If it doesn't, I'll add that, because it's the remedy for the pre-registration case above.

**UI:** A "Sign in with Google" link-button following Google's branding guidelines on `login.ejs` and `signup.ejs`. It's a plain link with no Google JS, so the CSP is unchanged.

**Config and flags:**
- `config.ts` (zod) adds `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI`. They are required only when `FEATURE_GOOGLE_SIGNIN` is on.
- The button and routes are active only when the flag is on **and** the request host matches `GOOGLE_REDIRECT_URI`'s origin. That hides it on preview deploys, which share staging's config.

**Tests:**
- Jest/supertest in `test/auth/google.test.ts` against a stubbed OIDC issuer. Cases:
  - state mismatch, bad nonce and expired token
  - each linking branch, including unverified local account and non-authoritative email
  - null-password login
  - set-password via reset
  - disconnect guard
  - session regeneration
  - the callback not relying on `tb.sid`
- Existing Playwright smoke tests stay as they are. I'll add a check that the button renders on staging. Automating a real Google login isn't practical.

**Rollout:**
1. Merge with the flag off everywhere. The migration runs in the release step, and the nullable column plus new table are safe for the old code.
2. Enable on staging and test manually with real Google accounts.
3. You publish the consent screen and the privacy policy update goes live.
4. You or the lead engineer enable the flag in production.

## What I need from you (only you can do these)

- **Google Cloud:**
  - I recommend a fresh project, e.g. `tallybook-auth`, instead of reusing the leftover `tallybook-prod`, so access and audit history stay clean.
  - Configure the OAuth consent screen as External, with app name, logo, support email, homepage, privacy policy URL, and `tallybook.example.com` verified as an authorized domain.
  - Create two Web OAuth clients:
    - **prod:** `https://app.tallybook.example.com/auth/google/callback`
    - **non-prod:** staging callback plus `http://localhost:3000/auth/google/callback`
  - Publish the app. Testing mode caps it at 100 test users.
- **Secrets:** Set the prod and staging values in the hosting environment settings (you or the lead engineer). Put the non-prod client in the vault for local `.env`.
- **Privacy policy:** It needs to state that users can sign in with Google and that we receive their Google account ID, email, name and email-verification status. We won't store profile photos. I can draft wording for counsel, but I won't edit `public/legal/privacy.html` myself.
- **Decisions:**
  - Are you OK with the strict linking rule in step 3? Some unverified users will be asked to log in with their password once.
  - Is it acceptable that preview deploys won't show the button?

If you approve, I'll do it as one PR: migration, Google routes, null-password handling, UI and tests, all behind the flag. I'll open it as a draft and won't merge or change any environment settings.

# Summary for approval: "Sign in with Google"

**What:** Add a "Sign in with Google" button to the login and signup pages. People can create an account or log in with Google, and existing email/password users can connect Google to their account.

**How it works for users**
- New users can sign up with Google without choosing a password. Their email counts as verified.
- An existing user who clicks the button is connected to their account automatically if their Tallybook email is verified and Google can vouch for that address. That means a Gmail address, or a company domain run on Google Workspace.
- Otherwise they're asked to log in with their password once and connect Google from Security settings. Users who forgot their password can use the normal reset flow.
- Google-only users can add a password later, and can disconnect Google only once they have one.

**Why the cautious linking rule:** Tallybook has never required email verification, so about 9,000 accounts were never verified. Someone could have registered another person's address in advance. Blindly linking by email would hand that person's Google login an account the attacker still has a password for. The rule prevents that, and the only cost is a one-time password login for some users.

**Technical notes (for the reviewer)**
- Uses the standard OpenID Connect code flow (`openid-client`, with PKCE, state and nonce).
- Google identities are stored in a new `user_identities` table keyed by Google's account ID, not by email. The same table can serve Microsoft/Apple sign-in later (issue #388).
- `users.password_hash` becomes nullable. The migration is backward-compatible.
- The session cookie is `SameSite=Strict`, which browsers don't send on the redirect back from Google. The flow therefore keeps its temporary state in a separate short-lived cookie and finishes with a same-site page load.
- No changes to the Content Security Policy or CSRF protection.
- Everything sits behind the `FEATURE_GOOGLE_SIGNIN` flag. The button is hidden on preview deploys, because Google does not allow wildcard redirect addresses.
- New automated tests cover the security-relevant paths. Real Google login is tested manually on staging.

**What the founder needs to do**
1. Create the Google Cloud setup. I recommend a fresh project rather than the leftover `tallybook-prod`. This covers the consent screen (app name, logo, support email, privacy policy link, verified domain) and two OAuth clients, one for production and one for staging and local development. Then publish the app.
2. Put the client credentials in the hosting environment settings and the team vault (founder or lead engineer).
3. Update the privacy policy with counsel. It must say that users can sign in with Google and that we receive their Google account ID, name, email and verification status. This must be live before the feature is turned on in production.
4. Confirm two decisions: the cautious linking rule, and no Google sign-in on preview deploys.

**Rollout**
1. Merge with the feature off.
2. Turn it on in staging and test with real Google accounts.
3. After the Google setup and the privacy policy update are done, the founder or lead engineer turns it on in production.

Turning it off again is a single environment-setting change. Accounts created through Google can still sign in by email reset after adding a password.

**Out of scope:** Microsoft/Apple sign-in (#388), Redis sessions (#412), and requiring verification for existing unverified accounts.

<details>
<summary>Show the plan doc for the agent (1156 words)</summary>

# Plan: "Sign in with Google" for Tallybook

Nothing in the app has changed yet. The only file I've written is the approver summary that `CLAUDE.md` asks for. It's at the end, uncommitted.

## The constraints

1. **Your session cookie blocks the usual OAuth flow.** `tb.sid` is `sameSite: 'strict'`. When Google redirects back to `/auth/google/callback`, the browser treats that as a cross-site navigation and doesn't send `tb.sid`. It also withholds the cookie on any further redirect in that chain. So OAuth state can't live in the session, and a plain `302 → /dashboard` after login would land the user logged out.
2. **Linking by email can enable account takeover.** Login has never required verification, and about 9,000 accounts are unverified. An attacker could have registered `[REDACTED-EMAIL]` with their own password. If we auto-link the victim's Google login to that account, the attacker keeps a working password on it. Some Google accounts also use non-Gmail addresses that Google isn't authoritative for.
3. **Google doesn't allow wildcard redirect URIs**, so `pr-<n>.preview…` deploys can't complete the flow.
4. **`password_hash` is NOT NULL**, but Google-only users won't have a password.
5. **CSP `form-action 'self'`** blocks a form POST that redirects to `accounts.google.com`. The button must be a plain link.
6. **External dependencies.** Only you can configure Google Cloud, and the privacy policy has to change before launch, which goes through you and counsel.

## Design

**Library:** `openid-client`, using authorization code flow with PKCE, `state` and `nonce`. It validates the ID token's signature, `iss`, `aud`, `exp` and nonce. Scopes are `openid email profile` only. These are non-sensitive scopes, so Google's restricted-scope review isn't needed.

**Routes** (in a new `src/auth/google.ts`, mounted from `src/auth/routes.ts`):
- `GET /auth/google?intent=login|link`
  - Generates state, nonce and PKCE verifier.
  - Stores them, plus the intent and a return path, in a short-lived signed cookie `tb.oauth`. That cookie is `httpOnly`, `secure`, **`sameSite: 'lax'`**, 10-minute lifetime, scoped to `/auth/google`.
  - Redirects to Google.
  - For `link`, it requires an authenticated session and records the user id in `tb.oauth`.
- `GET /auth/google/callback`
  - Verifies `state` against `tb.oauth`, exchanges the code, validates the ID token and clears `tb.oauth`.
  - Applies the linking rules below.
  - Calls `req.session.regenerate()` and logs the user in.
  - Returns a **200 page that does a same-site navigation** (meta refresh plus a fallback link) to the destination, so `tb.sid` is sent on the next request.
- No changes to the CSRF middleware are needed. The callback is a GET, and state is the CSRF protection for it.

**Data** (one Knex migration, backward-compatible with the running version):
- New table `user_identities`:
  - Columns: `id`, `user_id` (FK, cascade), `provider`, `provider_subject`, `email_at_link`, `created_at`, `last_used_at`.
  - Unique on `(provider, provider_subject)`, and unique on `(user_id, provider)`.
  - Lookups key on Google's `sub`, never on email. The table is generic, so issue #388 (Microsoft/Apple) can reuse it.
- `users.password_hash` becomes nullable.

**Linking rules on callback:**
1. If `sub` is already linked, log in as that user.
2. If not linked and no user has that email, create a user with `password_hash = NULL` and `email_verified_at = now()`. The email must be Google-verified.
3. If not linked and a user with that email exists, auto-link **only if all three hold**:
   - the Google `email_verified` claim is true;
   - the email is authoritative, meaning `@gmail.com` or an `hd` (Workspace) claim matching the domain;
   - the local account has `email_verified_at` set.

   Otherwise, show: "An account with this email exists. Log in with your password, then connect Google from Security settings." The forgot-password flow covers users who no longer know their password.
4. For `intent=link`, attach the identity to the logged-in user. This fails if the `sub` already belongs to someone else.

**Google-only accounts:**
- `password.ts` and the local strategy treat a null hash as "no password". There's no argon2 call and no crash. The login form says "This account uses Google sign-in."
- `reset.ts` lets these users *set* a password.
- `security.ejs` shows "Set password" instead of "Change password" when there's no hash. It also gets "Connect / Disconnect Google". Disconnect is only allowed if a password exists.
- I'll check that a password reset destroys the user's other sessions in the `session` table. If it doesn't, I'll add that, because it's the remedy for the pre-registration case above.

**UI:** A "Sign in with Google" link-button following Google's branding guidelines on `login.ejs` and `signup.ejs`. It's a plain link with no Google JS, so the CSP is unchanged.

**Config and flags:**
- `config.ts` (zod) adds `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI`. They are required only when `FEATURE_GOOGLE_SIGNIN` is on.
- The button and routes are active only when the flag is on **and** the request host matches `GOOGLE_REDIRECT_URI`'s origin. That hides it on preview deploys, which share staging's config.

**Tests:**
- Jest/supertest in `test/auth/google.test.ts` against a stubbed OIDC issuer. Cases:
  - state mismatch, bad nonce and expired token
  - each linking branch, including unverified local account and non-authoritative email
  - null-password login
  - set-password via reset
  - disconnect guard
  - session regeneration
  - the callback not relying on `tb.sid`
- Existing Playwright smoke tests stay as they are. I'll add a check that the button renders on staging. Automating a real Google login isn't practical.

**Rollout:**
1. Merge with the flag off everywhere. The migration runs in the release step, and the nullable column plus new table are safe for the old code.
2. Enable on staging and test manually with real Google accounts.
3. You publish the consent screen and the privacy policy update goes live.
4. You or the lead engineer enable the flag in production.

## What I need from you (only you can do these)

- **Google Cloud:**
  - I recommend a fresh project, e.g. `tallybook-auth`, instead of reusing the leftover `tallybook-prod`, so access and audit history stay clean.
  - Configure the OAuth consent screen as External, with app name, logo, support email, homepage, privacy policy URL, and `tallybook.example.com` verified as an authorized domain.
  - Create two Web OAuth clients:
    - **prod:** `https://app.tallybook.example.com/auth/google/callback`
    - **non-prod:** staging callback plus `http://localhost:3000/auth/google/callback`
  - Publish the app. Testing mode caps it at 100 test users.
- **Secrets:** Set the prod and staging values in the hosting environment settings (you or the lead engineer). Put the non-prod client in the vault for local `.env`.
- **Privacy policy:** It needs to state that users can sign in with Google and that we receive their Google account ID, email, name and email-verification status. We won't store profile photos. I can draft wording for counsel, but I won't edit `public/legal/privacy.html` myself.
- **Decisions:**
  - Are you OK with the strict linking rule in step 3? Some unverified users will be asked to log in with their password once.
  - Is it acceptable that preview deploys won't show the button?

If you approve, I'll do it as one PR: migration, Google routes, null-password handling, UI and tests, all behind the flag. I'll open it as a draft and won't merge or change any environment settings.

</details>

---

Method and all outputs: [benchmark/](../README.md).
