# Process design: Grupo Sazón delivery-driver screening

## Problem

Grupo Sazón receives about 1,000 delivery-driver applications a week across 45 restaurants in Spain and Mexico. Thirteen recruiters screen by phone. Six in ten candidates never answer. Eight in ten recruiter hours go to candidates who cannot be hired. The agent takes the first screening off the recruiters and hands them only candidates who pass two objective checks.

## Channel policy

WhatsApp carries the whole screening. First contact is a WhatsApp template sent minutes after the application. It names the assistant, says it is an AI, says the conversation is recorded, and asks for a good moment. The reply is the opt-in and opens the 24-hour WhatsApp service window. The engine takes text and returns text, so another channel (a browser voice call) is an adapter on the same flow. It is not built and is listed under improvements in the README. A channel switch never restarts the flow.

## Conversation stages

Ordered cheapest disqualifier first. Both hard stops come before any field a recruiter would read.

| # | Stage | Tool exposed to the LLM | Branch |
| --- | --- | --- | --- |
| 1 | Consent | `record_consent` | No: close politely, `needs_recruiter_review` |
| 2 | Full name | `record_full_name` | Invalid: re-ask once |
| 3 | Driving licence | `record_licence` | No: `disqualified`, reason `no_licence` |
| 4 | City or zone | `record_zone`, `confirm_zone` | No match: `disqualified`, reason `outside_service_area`. Fuzzy match: confirm, then `needs_recruiter_review` if denied |
| 5 | Availability | `record_availability` | Invalid: re-ask once |
| 6 | Preferred shift | `record_schedule` | Invalid: re-ask once |
| 7 | Delivery experience | `record_experience` | 0 years is valid |
| 8 | Start date | `record_start_date` | Past date: re-ask once |
| 9 | Outcome | none | `qualified`: summary and interview handoff |

The current stage is the first required field still missing. Every tool for a still-missing field after the current stage is exposed at once, so a candidate who answers three questions in one message advances three stages. The LLM cannot skip the licence check because later tools do not exist until code exposes them.

## Agent personality

Named assistant ("Sazón"). Warm, informal-professional, uses tú in Spanish. Never pretends to be human. One question per message. At most two sentences and one emoji. Says briefly why it asks each thing.

## Data fields and validation

Rules live in code, not prompts. Every rule is a Pydantic validator on one model, `CandidateProfile`.

| Field | Validation | On failure |
| --- | --- | --- |
| Full name | Two or more alphabetic words | Re-ask with an example |
| Driving licence | Yes or no | No: disqualify |
| City or zone | Exact match on a service area name or alias (case and accent insensitive): accept. Fuzzy score 70 or more: confirm. Below 70: out | Out: disqualify. Confirm denied: recruiter review |
| Availability | One or more of full-time, part-time, weekends | Re-ask with options |
| Preferred shift | One of morning, afternoon, evening, flexible | Re-ask with options |
| Experience | Years 0 to 40, platforms as a list, empty allowed | Re-ask |
| Start date | ISO date, today or later. Relative phrases resolved by the LLM against today's date | Re-ask with a date example |

Structured output is the JSON dump of `CandidateProfile`.

## Edge cases

- **Silence.** No reply to the opener: one template retry at about 24 hours, then `abandoned` at stage `consent`. Silence after a reply: a free-form nudge at 2 hours and a last one at about 23 hours, inside the window, then `abandoned` with the stage recorded.
- **Invalid or ambiguous answer.** The validator rejects the tool call. Code sends a fixed re-ask message with an example. After two rejections on the same stage the candidate goes to `needs_recruiter_review` instead of looping.
- **Language switch.** Language is detected per message. The agent replies in that message's language. The history of languages is stored. Code-switched messages work because the tools are language-agnostic.
- **Off-topic or inappropriate input.** A guardrail check runs before the turn. Redirect once, then close politely to `needs_recruiter_review`.
- **Candidate answers several questions at once.** All matching tools are called in one turn and the flow skips the satisfied stages.
- **Confused or frustrated candidate.** The guardrail check also reads the candidate's tone. A confused or frustrated candidate gets simpler, calmer wording for that turn. A failed check counts as neutral.

## Outcomes

| Status | Who decides | What the candidate hears | What the recruiter sees |
| --- | --- | --- | --- |
| `qualified` | Code, all fields valid | Fixed message: a recruiter will book a short interview | Summary, profile JSON, transcript |
| `disqualified` | Code, on no licence or out of zone only | The real reason, in their language. Application kept on file | Reason code. Override button |
| `needs_recruiter_review` | Code, on anything ambiguous | A recruiter will follow up | Reason code, transcript |
| `abandoned` | Code, on silence | Nothing further | Drop-off stage |

Only the two objective criteria disqualify automatically. Everything judgement-shaped goes to a human. Every outcome and override is written to an append-only event log with its reason.

## Tone and length

Messaging, not email. One to two sentences. One question. No bullet lists. Reply within seconds. Never more than two agent messages in a row without a candidate reply. Closing messages are fixed text owned by code, so a disqualified candidate always hears the real reason.

Code checks every model reply before it is sent: one question, at most one emoji, a length limit, the candidate's language, no markdown and no links. A reply that fails a check is replaced by the fixed question for the current stage. There is no second LLM call, so the check adds no latency.
