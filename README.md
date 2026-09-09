# Cooperative Savings & Loans App — Phase 1–6 Scaffold (Complete)

Matches the locked system design end to end. Phase 1 (core ledger, auth,
manual entry, PWA shell), Phase 2 (PayVessel integration + receipt
upload), Phase 3 (loans, repayment schedules, profit-sharing
distribution), Phase 4 (loan eligibility rules), Phase 5 (weekly ledger
PDF export + PayVessel reconciliation tooling), Phase 6 (bulk reports,
personal statements, audit log viewer, role-based admin permissions).

## What's implemented

### Phase 1
- **`apps/accounts`** — custom `User` (role: member/treasurer/secretary/
  chairman/superadmin) + `MemberProfile` (BVN/NIN encrypted at rest,
  status: pending/active/suspended/exited, gender + DOB for identity
  verification).
- **`apps/ledger`** — `LedgerEntry` (immutable, append-only),
  `CooperativeSettings` (singleton — holds the Shared Capital requirement
  used in Phase 4), `LedgerExport` (model only — the weekly PDF job itself
  is a later phase). `LedgerService` is the *only* sanctioned way to touch
  the ledger: row-locks to avoid race conditions, requires a reason on
  every adjustment/reversal, writes an `AuditLog` row on every write.
- **`apps/transactions`** — manual entry fallback tool, HTMX-driven,
  admin-only. Only `deposit` and `share_capital_contribution` — loan
  entry types aren't usable until Phase 3.
- **`apps/core`** — `AuditLog`, `Notification`, `EncryptedCharField`
  (Fernet-based), member/admin dashboards, root-scope service worker view.
- **PWA shell** — `manifest.json`, `service-worker.js` (static shell only,
  never HTML/financial data), install-ready `base.html`.

### Phase 2 (`apps/payments`)
- **`client.py`** — `PayVesselClient`. Reserved-account creation and NIN
  verification endpoints are confirmed against PayVessel's published docs.
  **The BVN verification endpoint is inferred by symmetry, not
  independently confirmed** — see the docstring in `client.py`. Confirm it
  against `docs.payvessel.com/api-reference/verification/` before using
  this in production; only `BVN_VERIFY_PATH` needs to change if it's wrong.
- **`services.py`** — `WebhookService`: HMAC-SHA512 signature verification
  on the *raw* request body, IP allowlist check, idempotent processing via
  `WebhookEvent.transaction_reference` (unique constraint). A verified,
  new webhook posts straight to the ledger as `confirmed` — no human step.
- **`tasks.py`** — `verify_identity_task` (fired at registration, async,
  never blocks) and `create_reserved_account_task` (fired when an admin
  approves a member via `MemberProfileAdmin.approve_members`).
- **Receipt upload (Section 5c)** — `PaymentProof` model, member upload
  view, admin review queue + detail view. Deliberately **no OCR, no
  extraction, no confidence score** — an admin reads the file and types in
  what they see. File-hash duplicate detection only (not content-based).

### Phase 3 (`apps/loans`)
- **`Loan`** — one model covers the whole lifecycle (the design's
  "LoanApplication → Loan" shorthand): `pending` → optionally
  `guarantor_pending` → `approved` → `active` → `completed` /
  `defaulted` / `rejected`. `Qard Hasan` (interest-free) and `Murabaha`
  (fixed, agreed-upfront profit margin — never a rate over time, never
  compounding) are the only two financing structures, per the Shariah
  compliance principle from Section 2.
- **`RepaymentSchedule`** — generated on disbursement, one row per monthly
  installment. Any rounding remainder from splitting `total_repayable`
  evenly is absorbed into the *last* installment so the schedule always
  sums exactly right — never silently over- or under-collects a few kobo.
- **`LoanService`** — `apply_for_loan`, guarantor accept/decline,
  `approve_loan`/`reject_loan`, `disburse_loan` (posts the disbursement
  entry + generates the schedule in one transaction), `record_repayment`
  (allocates a payment oldest-installment-first, auto-marks the loan
  `completed` once the loan's ledger stream nets to zero).
- **Ledger extended, not bolted on** — `LedgerEntry` gained a nullable
  `loan` FK. A member's savings balance and each of their loans' 
  outstanding balances are now separate "streams" in the same immutable
  table, discriminated by whether `loan` is null or set — *not* by
  `entry_type`, specifically so a reversal (always typed `ADJUSTMENT`)
  still lands in the correct stream instead of silently vanishing from a
  loan's balance. See the module docstring in `ledger/services.py`.
- **Celery Beat tasks**: `distribute_profit_sharing` (Mudarabah-style —
  proportional to each member's current savings balance, not a fixed
  promised rate, which would function like interest; the profit pool
  amount itself is a cooperative governance decision passed in as an
  argument, not invented here) and `scan_overdue_repayments` +
  `remind_upcoming_repayments` (Section 3C's due-date scan — creates
  `Notification` rows for the member and every admin-tier user; actually
  sending them is Phase 2's SMS/email/push provider wiring, not this
  task's job).

### Phase 4 (`apps/loans/eligibility.py`)
- **`LoanEligibilityPolicy`** — admin-editable tiers (name, min tenure in
  months, min savings balance, max loan multiple). Committees add/adjust
  tiers via Django admin, no code change or deploy needed. `Loan` now has
  a required `policy` FK recording which tier an application was checked
  against.
- **`EligibilityService.check()`** — the actual gate, called from
  `LoanService.apply_for_loan()`:
  1. **Shared Capital gate first** — `LedgerService.has_paid_share_capital`
     (this existed since Phase 1; Phase 4 is the first thing that actually
     calls it). Fails here, stops here — tenure/savings aren't even checked.
  2. Membership tenure against the chosen tier's `min_tenure_months`.
  3. Savings balance against the chosen tier's `min_savings_balance`.
  4. Requested `principal` against `savings_balance × max_loan_multiple`.
  Any failure raises a plain-language reason the member sees directly
  (Section 6) — re-raised as `LoanError` so `LoanService` callers only
  ever catch one exception type.
- **`django-waffle` switch — `enforce_loan_eligibility_rules`** — the
  *only* thing that turns the whole check above on or off. `settings.py`
  sets `WAFFLE_SWITCH_DEFAULT = True` specifically so this defaults to
  **enforcing** even before an admin has ever opened Django admin's
  "Switches" page — matching Section 6's "When on (default)" wording.
  Turning it off doesn't touch `LoanEligibilityPolicy` rows at all; it
  just means every application skips straight to manual admin judgment.
- The loan application page now shows the member's own standing (Shared
  Capital status, membership duration, savings balance) *before* they
  submit — reusing the same `EligibilityService.snapshot()` the actual
  check uses, so what they see and what gets enforced can never drift
  apart into two different implementations of the same rule.

### Phase 5 (`ledger/exports.py` + `payments/reconciliation.py`)
- **Weekly ledger PDF export** — `generate_weekly_ledger_export` (Celery
  Beat, same admin-configured-schedule pattern as Phase 3/4's periodic
  tasks) renders every `confirmed` `LedgerEntry` from the past 7 days into
  one combined PDF via `reportlab` (pure Python — no `cairo`/`pango`
  system dependency, unlike `weasyprint`, so the Docker image stays
  simple) and creates a `LedgerExport` row.
- **Download-triggered cleanup, not a blind schedule** — `export_download_view`
  marks `downloaded_by`/`downloaded_at` only on the *first* download, then
  queues `cleanup_downloaded_export` with a 2-minute countdown (not
  immediate — gives a slow connection time to finish). The cleanup task
  itself refuses to touch a file that was never downloaded, so a
  forgotten weekly export just sits there flagged "not yet downloaded"
  instead of silently vanishing (Section 3C — this exact guarantee was
  the reason the PDF-export idea replaced DO Spaces several turns ago in
  the design phase).
- **PayVessel reconciliation — CSV upload, not a direct API call.**
  PayVessel's docs (as fetched during this build) confirm reserved-account
  creation, webhook verification, and NIN verification endpoints, but not
  a settlement/statement-export endpoint — rather than invent one,
  `ReconciliationService` works from a CSV an admin exports manually from
  the PayVessel merchant dashboard. Column names are matched
  case-insensitively against a short alias list (`reconciliation.py`'s
  `COLUMN_ALIASES`) rather than a hardcoded exact header, since the real
  export format wasn't confirmed. If PayVessel later documents a
  settlement API, this is the natural place to fetch it automatically
  instead.
- Flags three kinds of discrepancy: amount mismatch, present in PayVessel's
  file but not found locally (a possible missed/failed webhook worth
  investigating), and processed locally but absent from the file (worth
  checking it wasn't a test/duplicate). Every run is persisted
  (`ReconciliationRun` + `ReconciliationDiscrepancy`) as an audit trail,
  not just shown once and discarded.

### Phase 6 (role permissions, reports, statements, audit log)
- **Role-based admin tiers — a REASONABLE DEFAULT, not a spec.** The
  design said "different permission levels" without naming exactly which
  action belongs to which tier, so `setup_roles.py`'s mapping is a
  sensible cooperative-society default: **Treasurer** = money movement
  (manual entries, loan repayments, receipt review, reconciliation);
  **Secretary** = membership admin (approve members) + oversight (audit
  log); **Chairman** = loan approval/disbursement + membership approval +
  oversight (audit log, reports). This is meant to be **adjusted via
  Django admin's Groups UI** afterward, not treated as fixed — that's why
  it's built on Django's real Group/Permission system rather than
  hardcoded `if user.role == "treasurer"` checks scattered through views.
- **`User.role` stays the single source of truth** for which Group a user
  is in — a signal (`accounts/signals.py`) syncs Group membership
  automatically on every save, so changing someone's role via the
  existing dropdown (no new UI to learn) is enough; nobody needs to
  separately manage Groups by hand unless they want to customize beyond
  the default mapping.
- **Superadmin is deliberately NOT a Group.** Django's real `is_superuser`
  flag already bypasses every permission check. `User.Role.SUPERADMIN` is
  a label for display purposes; pair it with `is_superuser=True` via
  Django admin or `createsuperuser` for it to actually mean anything
  permission-wise. Two different concerns (our app's role label vs.
  Django's real superuser flag) kept explicit rather than conflated.
- **Defense in depth, not either/or.** Every sensitized view still checks
  the existing coarse `is_admin_tier` gate (from Phase 1) *and* the new
  fine-grained `@permission_required`. A misconfigured/empty Group
  right after a fresh install can't accidentally grant a plain member
  access — the coarse gate catches that regardless of Group state.
- **Bulk reports (CSV, not Excel)** — member statements, loan book,
  savings summary, overdue list. Kept dependency-light (no `openpyxl`)
  since CSV opens fine in Excel/Sheets and nothing in the design
  specifically asked for native `.xlsx`; a reasonable follow-up if it
  turns out to matter in practice.
- **Personal statement (PDF/CSV)**, member-facing — generated fresh
  per-request, entirely **in memory** (`io.BytesIO`, not a temp file on
  disk). Worth calling out: my first draft of this used
  `tempfile.mkstemp()` with no cleanup path, which would have leaked a
  file on every single download — caught and fixed in this same pass by
  switching `generate_member_statement_pdf` to render into a buffer and
  return bytes directly, matching the "no orphaned files" discipline the
  weekly export already had to earn the hard way in Phase 5.
- **Audit log viewer** — filterable (actor/action/target), paginated,
  read-only. Uses Django's auto-generated `view_auditlog` permission
  directly — no custom `Meta.permissions` entry needed for this one,
  unlike the other Phase 6 gates.

## Known gaps (intentional, flagged rather than silently guessed at)

- **BVN-only STATIC accounts.** PayVessel's STATIC reserved accounts
  require a BVN. A member who registers with a NIN instead currently gets
  no reserved account at all (`create_reserved_account_task` no-ops for
  them) — they're limited to the receipt-upload/manual-entry paths until
  this is resolved one way or another.
- **Webhook deposits always post as plain `deposit`.** There's no
  reliable signal in a bank transfer for "this was meant as my Share
  Capital contribution" — an admin has to reverse and re-post via the
  adjustment tool if a member intended that. See the comment in
  `payments/services.py` for the full reasoning.
- **PayVessel client failures are mostly silent no-ops for now**
  (`except PayVesselError: return`, no retry/alerting). Flagged as a
  Phase 2 hardening TODO in `tasks.py` rather than guessed at with a
  retry/backoff policy nobody's confirmed.
- BVN/NIN verification result does **not** auto-approve or auto-block
  membership — an admin always makes the final call (Section 3B:
  mismatches are flagged for follow-up, not hard-blocked).
- **No loan eligibility enforcement yet.** `LoanService.apply_for_loan()`
  accepts any active member's application regardless of Shared Capital,
  tenure, or savings balance — that gate, plus the `django-waffle` switch
  to toggle it, is explicitly Phase 4 scope per the build order. Adding it
  only touches the top of `apply_for_loan()`, nothing else.
- **At most one guarantor per loan.** A cooperative wanting multiple
  guarantors, or quorum-based guarantor rules, would need a separate
  per-loan guarantor-request model — flagged as a reasonable extension,
  not built here without being asked for.
- **Manual/webhook/receipt-upload repayments aren't unified yet.** Only
  the admin's "Record Repayment" tool (`loans/record_repayment`) posts
  against a specific loan's stream. A PayVessel webhook or an uploaded
  receipt still always posts as a savings `deposit` (Phase 2's existing
  simplification) — routing one of those to a specific loan's repayment
  stream instead is a real follow-up, not silently assumed to work.
- **`distribute_profit_sharing`'s pool amount is an external input**, not
  computed by the app — the cooperative decides how much profit to
  distribute each period; this task only handles the proportional
  allocation once that number exists.
- Tailwind is still loaded via CDN (Play CDN) for this scaffold — replace
  with a compiled build before production (see Phase 1 README notes,
  unchanged in Phase 2).
- No test suite yet.
- **`Loan.policy` is a required FK with no default.** Fine for a fresh
  database, but if Phase 3 was already migrated against a populated dev
  DB before Phase 4 landed, `makemigrations` will prompt for a one-off
  default for existing rows — expected, not a bug, just worth knowing
  before running it against data you care about.
- The eligibility snapshot shown on the application page and the actual
  enforcement both call `EligibilityService`, so they can't drift apart —
  but there's still a small TOCTOU gap: a member's savings balance could
  change between viewing the form and submitting it. Not handled with a
  lock, since the application itself doesn't move money — worth revisiting
  only if that gap ever causes a real dispute in practice.
- **Reconciliation's `MISSING_IN_FILE` check compares against ALL processed
  `WebhookEvent` rows ever**, not just ones in the period the uploaded file
  covers — if you upload a settlement file for last week but processed
  webhooks go back months, older ones will show as "not in this file"
  even though they were never meant to be. Fine for now since runs are
  ad hoc, not period-scoped, but worth adding a date-range filter if this
  becomes a recurring weekly habit rather than an occasional check.
- **The weekly PDF export has no pagination limit built in.** For a
  cooperative-society transaction volume this is a non-issue; if the
  member base grows into the thousands with heavy weekly volume, the
  single combined table could get large enough to matter — `reportlab`
  handles it (multi-page tables work fine via `repeatRows`), just flagging
  that "one file, all transactions" was a deliberate simplicity choice for
  the scale this app is designed for (Section 1).
- **The Treasurer/Secretary/Chairman permission mapping is a default, not
  a decision the cooperative made.** Nobody specified exactly which
  action belongs to which tier — review `setup_roles.py`'s
  `ROLE_PERMISSIONS` dict against how your actual committee splits
  responsibilities, and adjust via Django admin's Groups UI (or edit the
  command and re-run it — it's idempotent).
- **Loan disbursement is gated under `can_review_loans` (Chairman-level)**,
  even though it's arguably Treasurer-level money movement — it's bundled
  with approve/reject in the same `loan_review_view` because disbursement
  follows immediately after approval in that flow. Splitting disbursement
  out to accept `ledger.can_record_manual_transaction` as an alternative
  acceptable permission is a reasonable follow-up, not built here since
  the exact boundary wasn't specified.
- **No test suite covers the new permission checks.** Given they can't be
  executed against a real database in this environment (see the note at
  the end of this README), the `has_perm`/`permission_required` wiring is
  syntax-checked and cross-referenced by hand (every permission string
  used matches a declared one — verified), not run against Django's
  actual permission backend. Worth a real test pass before relying on it.

## Local setup

```bash
cp .env.example .env
# edit .env — set real values, especially:
#   DJANGO_SECRET_KEY, POSTGRES_PASSWORD
#   FIELD_ENCRYPTION_KEY — generate with:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   PAYVESSEL_API_KEY / PAYVESSEL_API_SECRET — from your PayVessel sandbox dashboard

docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py setup_roles
docker compose up
```

`setup_roles` creates the Treasurer/Secretary/Chairman permission groups
with the default mapping described in Phase 6 above — safe to re-run any
time (idempotent). Assign a user to a tier by setting their `role` field
(via Django admin's User form) to `treasurer`/`secretary`/`chairman` —
Group membership updates automatically.

Then visit `http://localhost:8000`. Register a member, then log into
`/admin/` as the superuser and use the "Approve selected members" action on
`MemberProfile` — this activates the member AND queues PayVessel reserved
account creation. Check `KYCVerification` in admin to see the BVN/NIN
match result before deciding.

To test the webhook locally, PayVessel needs a publicly reachable URL — use
a tunnel (e.g. ngrok) pointed at `/payments/webhook/payvessel/` and
register that URL in your PayVessel sandbox dashboard.

Before applying for a loan, create at least one `LoanEligibilityPolicy` in
Django admin (e.g. "Starter Loan" — 3 months tenure, ₦0 min savings, 2.00x
cap) — the application form has nothing to select otherwise. Enforcement
is ON by default (`WAFFLE_SWITCH_DEFAULT = True`); to turn it off, go to
Django admin's Waffle "Switches" section, create one named
`enforce_loan_eligibility_rules`, and set it inactive.

To try the loan flow: apply for a loan as a member (`/loans/apply/`),
approve + disburse it as an admin (`/loans/admin/queue/`), then record a
repayment against it.

To schedule the Phase 3 Celery Beat tasks (`distribute_profit_sharing`,
`scan_overdue_repayments`, `remind_upcoming_repayments`) plus Phase 5's
`generate_weekly_ledger_export`: the `beat` service already runs with
`django_celery_beat`'s `DatabaseScheduler` (see `docker-compose.yml`), so
schedules are configured via Django admin — Periodic Tasks — rather than
hardcoded in this repo, so the cooperative can adjust frequency without a
deploy. `distribute_profit_sharing` also needs a `total_pool_amount`
argument (a JSON string, e.g. `["50000.00"]`) set on its periodic task
entry.

To try the weekly export without waiting for the schedule: run
`docker compose run --rm web python manage.py shell -c
"from apps.ledger.tasks import generate_weekly_ledger_export;
generate_weekly_ledger_export.delay()"`, then check `/ledger/exports/`.

To try reconciliation: export a settlement/transaction CSV from your
PayVessel sandbox dashboard (or hand-craft one with `reference` and
`amount` columns to test the matching logic) and upload it at
`/payments/reconciliation/`.

## Directory structure

```
config/            Django project settings, celery app, root urls
apps/
  accounts/        User, MemberProfile, KYCVerification, auth, registration,
                   role->Group sync signal + setup_roles command (Phase 6)
  core/            AuditLog, Notification, EncryptedCharField, dashboards,
                   audit log viewer (Phase 6)
  ledger/          LedgerEntry, CooperativeSettings, LedgerService,
                   weekly PDF export + cleanup tasks (Phase 5),
                   personal statements + bulk reports (Phase 6)
  transactions/    Manual entry fallback tool (HTMX)
  payments/        PayVessel client, webhook receiver, receipt upload/review,
                   settlement reconciliation (Phase 5)
  loans/           Loan, RepaymentSchedule, LoanEligibilityPolicy, LoanService,
                   EligibilityService (Phase 4), profit-sharing + overdue tasks
templates/         base.html (PWA shell) + per-app templates
static/            manifest.json, service-worker.js, icons, custom.css
nginx.conf          Reverse proxy config for the DigitalOcean VPS deploy
docker-compose.yml  web / worker / beat / db / redis
```
