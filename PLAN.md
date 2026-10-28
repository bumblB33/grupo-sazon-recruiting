# PLAN

Scope, in priority order: a fixed reply for unknown numbers, applicant name with match check, then GUID candidate ids and an applicant file. The unanswered-limit commit and the demo reset are done. The intake page, the async worker and the other unbuilt designs are in `docs/process-design.md` ("Designed, not built"). WhatsApp is the only candidate channel. Fold this file into `docs/STATUS.md`, `README.md` and `docs/process-design.md` when the work lands, then delete it.

Rule for every step: write the failing test first, then the smallest change that passes it.

## Sequencing

The case study is due 27 Oct 2026. Work ships in slices. Each slice ends with pytest, ruff check, ruff format and pyright green before the next starts.

Done: S0, the unanswered-limit commit (`ecb6b4a`). SR, the demo reset (`fa74e41`), so a retake reuses a phone.

Before the video, in this order:

1. S1. Fixed reply for an unknown number (section 1a).
2. S2. Applicant name with mismatch review (section 2).
3. Adversarial review of the diff.
4. Rebuild the image, run the WhatsApp preflight, run one full screening, write the sample conversations (`docs/STATUS.md`, "Remaining work").
5. Record the video.

After the take:

6. S3. GUID ids and duplicate guard (section 1).
7. S4. Applicant file (section 4).

Cut order if time runs short before the take (proposed): S2 first. S1 stays.

## State

- S0 and SR are committed. S1 to S4 are not built. No code changed in the planning session.
- The demo runs on the WhatsApp sandbox with the code as it stands. The sandbox webhook is saved and both maintainer phones have joined.
- Two candidates exist, keyed by their phones and in progress. The maintainer confirmed an opener arrived. Their names are not stored.

## 1a. Unknown number (S1)

Today a first inbound message from an unknown number skips the opener, so the sender never sees the AI disclosure (`docs/STATUS.md`, known gaps). This slice needs no GUIDs.

- The WhatsApp webhook checks that a candidate exists for the sender before it calls `ScreeningEngine.handle`. `handle` keeps its signature and still serves the CLI, evals and tests.
- No candidate: the webhook answers with a fixed reply and creates nothing. No model call runs.
- The reply is fixed text from `flow/replies.py`, in Spanish and English in one message. It names the assistant, says it is an AI, and says no application was found for this number.
- Test: an unknown number gets the fixed reply, no candidate is stored, and the scripted fake model records no input.
- The per-phone rate limit waits for S3. Without it a stranger can trigger outbound reply messages, but not model calls.

## 2. Applicant name, personalisation, mismatch review (S2)

- `StartRequest.name` is optional. Absent means today's behaviour, the agent asks for the name.
- `applicant_name` (from the application) stays separate from `profile.full_name` (what the candidate said).
- The opener and later replies use the applicant's first name. The sandbox sends text. A template send passes the name as a Content variable.
- Matching is a pure domain function. Normalise with casefold, accent strip (`unicodedata` NFKD), punctuation drop and token sort. Score with a fuzzy ratio. The threshold is a setting, not a literal.
- Proposed placement. The re-confirm turn lives at the `full_name` stage, owned by code:
  - `apply_tools` compares the accepted `record_full_name` value with `applicant_name`.
  - Below threshold and not yet asked: the stage stays `full_name`, a state flag records the question, and the reply is a fixed template from `flow/replies.py` ("Just to confirm, are you X?"). No second LLM call.
  - Still below threshold after the answer: `needs_recruiter_review` with `review_reason = name_mismatch`. Never an automated no.
- `name_mismatch` is a new `ReviewReason` value. `qualify_if_complete` in `flow/transitions.py` stays the only place that sets `qualified`. It routes to review when a mismatch is unresolved.
- Name is personal data. It must not enter log lines, exception messages or span attributes. The scrubber redacts only E.164 numbers and emails, so a name needs its own test. It does reach the LLM provider in prompts.

## 9. Demo reset (SR, built)

Built in `fa74e41`. It archives and re-keys a candidate that is in the `SCREENING_DEMO_PHONES` allowlist, so the phone is free for a new screening. The README "Key design decisions" describes it. The `process-design.md` "append-only" wording already names the exception.

When S3 lands, the reset is reworked: the re-key step goes away, and a reset forces a terminal status and adds a `demo_reset` event. The partial unique index then frees the phone.

## 1. Candidate identity: GUID ids and duplicate guard (S3, after the take)

Contract change. Candidate `_id` was the E.164 phone. Known producers and consumers:

- `POST /candidates` and `StartResponse.candidate_id`.
- The WhatsApp webhook, the sweep, `screening-cli` and `screening-admin`.
- Recruiter pages and URLs, including bookmarked URLs by phone.
- `events.candidate_id`, observability scrubbing (`observability.py`), eval personas, tests.
- The demo reset from SR.
- The README ATS section, which presents `GET /candidates/{id}` as the integration API.
- The `TROUBLESHOOTING.md` 409 row, which says the phone is the id.
- The demo scripts in `~/sazon-demo`, outside the repo.

Design:

- `_id` becomes `uuid4` text. Python 3.12 has no `uuid7`.
- New fields on the candidate document: `phone` (E.164), `channel`, `applicant_name`.
- Inbound webhooks resolve the sender phone to a candidate, then call `ScreeningEngine.handle(candidate_id, ...)`. `handle` keeps its signature.
- Resolution order for a sender phone:
  1. The candidate that holds the phone: status `in_progress` or `needs_recruiter_review`.
  2. Else the most recent terminal candidate for the phone. The late reply is recorded and `handle` returns CLOSED, as it does today.
  3. Else no application. The sender gets the fixed reply from S1 and no candidate is created.
- Duplicate guard: a unique partial index on `phone` for candidates that hold the phone. One conversation per phone. A review-pending candidate still holds it, so a re-application cannot create a duplicate during review. A candidate in `qualified`, `disqualified` or `abandoned` frees the phone, and a re-application creates a new GUID.
- Unverified: the partial filter form. An equality filter works. A filter on two statuses may need `$in` or `$or`, which older MongoDB versions reject. Test the chosen form against `mongo:7`. Fallback: a boolean field `phone_held`, set in the same write that changes status, with an equality filter. A recruiter override that leaves review must update it in that write.
- Add a non-unique index on `(phone, updated_at)` for the late-reply lookup.
- A losing insert raises `DuplicateKeyError`, mapped to the existing 409. This follows the repo rule of one atomic write, never count-then-insert.
- Legacy documents keep their phone `_id`. A backfill sets `phone = _id` where the field is missing. It is idempotent and runs at repository construction, before `create_index`. Without that order the index build fails, because a unique index treats a missing field as null and legacy in-progress candidates would collide. No data is deleted.
- Rate limit the unknown-number reply per phone with one atomic Mongo write. The limit is a setting.

## 4. Applicant file for the demo (S4, after the take)

Folder `applicants/`. The persona dataset in `docs/process-design.md` ("Names and data") is a different feature.

- `applicants.example.json` is committed. It holds fake names and reserved fictional numbers for the interviewer.
- `applicants.local.json` is gitignored. It holds the real test candidates. Confirm with `git check-ignore` before writing real data.
- Entry shape: `name`, `phone`, `language`.
- Command: `screening-admin start-from-file <path> [--dry-run]`. It calls `ScreeningEngine.start_conversation`, the same path as `POST /candidates`. A duplicate phone is reported and skipped.
- Delivery gate: the maintainer confirms both openers arrived before the work is called done.

## 6. Tasks

Before the take:

- [x] S0. Unanswered-limit commit (`ecb6b4a`).
- [x] SR. Demo reset (`fa74e41`).
- [ ] S1. Unknown-number fixed reply with tests (section 1a).
- [ ] S2. Name field, match function, re-confirm turn as a fixed template, review routing, and tests:
  - [ ] Placement of the re-confirm turn confirmed by the maintainer.
  - [ ] No-PII test: neither name appears in spans, log records or exception messages.
- [ ] Adversarial review of the diff: contracts, PII in logs, concurrency.
- [ ] `docs/STATUS.md` remaining work: image rebuild, preflight, one full screening, sample conversations.
- [ ] README and `docs/STATUS.md` updated for what landed. README still says the unknown-number reply, GUID ids and the name match are "planned in `PLAN.md`". Fix that text as each lands.
- [ ] Video recorded.

After the take:

- [ ] S3. GUID ids, `phone` field, backfill before index, partial unique index, phone lookup with late-reply recording, per-phone rate limit on the unknown-number reply, and tests:
  - [ ] Legacy test: two phone-keyed in-progress documents without `phone`. The index builds after the backfill.
  - [ ] Partial filter form verified against `mongo:7`.
  - [ ] Consumer sweep: `~/sazon-demo` scripts, README ATS section, `TROUBLESHOOTING.md` 409 row, recruiter URLs, `screening-cli`, `screening-admin`, the demo reset.
  - [ ] Rework the demo reset to a forced terminal status.
- [ ] S4. `applicants/` files, `.gitignore` entry, `start-from-file` command, and the delivery check.
- [ ] Remove references to this file from the README and `docs/STATUS.md`. Delete this file.

## 7. Out of scope

Voice channel, in-API scheduler, recruiter console, intake page, async worker, SMS channel, WhatsApp Business sender approval. The first six have rationale and tradeoffs in `docs/process-design.md` ("Designed, not built").

## 8. Decisions and open questions

Decided:

1. A message from a number with no application gets a fixed reply and no candidate. S1 builds it on phone ids. The rate limit lands with S3.
2. SMS is dropped. WhatsApp is the only channel.
3. Before the video: S1, S2. After: S3, S4. S0 and SR are done.
4. The intake page and the async worker are documented in `docs/process-design.md`, not built. If the worker is ever built, the queue is Celery with Redis.
5. Retakes use the demo reset, on phone ids.
6. A review-pending candidate keeps its phone once S3 lands. A late reply to a terminal candidate is recorded.
7. The earlier proposal to edit `docs/process-design.md` for name match and `name_mismatch`, the unknown-number reply and GUID ids is superseded. Rationale for deferred and planned work lives in one place, the "Designed, not built" section, and not in the stage tables and outcome rows. The reason is recorded in the README "Key design decisions". The "append-only" exception for the demo reset is already in `docs/process-design.md`.

Open:

1. Cut order if time runs short before the take. Proposed: S2 first.
2. Whether the flow handles a stop request. Unverified. It matters only if the intake page is ever built.
