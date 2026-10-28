LABELS: dict[str, dict[str, str]] = {
    "status": {
        "in_progress": "In progress",
        "qualified": "Qualified",
        "disqualified": "Disqualified",
        "needs_recruiter_review": "Needs review",
        "abandoned": "Abandoned",
    },
    "stage": {
        "consent": "Consent",
        "full_name": "Full name",
        "has_licence": "Driving licence",
        "zone": "Zone",
        "availability": "Availability",
        "schedule": "Schedule",
        "experience": "Experience",
        "start_date": "Start date",
        "outcome": "Outcome",
    },
    "reason": {
        "no_licence": "No driving licence",
        "outside_service_area": "Outside service area",
        "consent_declined": "Declined consent",
        "low_confidence_zone": "Zone unclear",
        "repeated_invalid_answer": "Repeated invalid answers",
        "off_topic_close": "Closed for going off topic",
        "name_mismatch": "Name differs from application",
        "stop_requested": "Candidate asked to stop",
        "recruiter_check": "Flagged for a recruiter check",
    },
    "event": {
        "outcome": "Outcome reached",
        "recruiter_override": "Recruiter override",
        "demo_reset": "Demo reset",
        "nudge": "Silence nudge sent",
        "nudge_failed": "Silence nudge failed",
        "nudge_unrecorded": "Silence nudge not recorded",
        "summary_failed": "Summary failed",
        "guardrail_blocked": "Message blocked",
        "guardrail_failed": "Guardrail unavailable",
    },
    "tool": {
        "record_consent": "Recorded consent",
        "request_stop": "Candidate asked to stop",
        "flag_for_recruiter": "Flagged for a recruiter check",
        "record_questions": "Recorded questions for the recruiter",
        "record_full_name": "Recorded name",
        "confirm_name": "Confirmed name",
        "record_licence": "Recorded licence",
        "record_zone": "Recorded zone",
        "confirm_zone": "Confirmed zone",
        "record_availability": "Recorded availability",
        "record_schedule": "Recorded schedule",
        "record_experience": "Recorded experience",
        "record_start_date": "Recorded start date",
    },
    "guardrail": {
        "on_topic": "On topic",
        "off_topic": "Off topic",
        "abusive": "Abusive",
        "prompt_injection": "Prompt injection attempt",
    },
    "reply_source": {
        "terminal": "Fixed closing message",
        "reask": "Fixed re-ask, model text unusable",
        "zone_confirm": "Fixed zone confirmation, model text unusable",
        "name_confirm": "Fixed name confirmation, model text unusable",
        "consent_deferred": "Fixed wait message, model text unusable",
        "model_text": "Model text, passed the reply rules",
        "model_composed": "Model text, written after the tool results",
        "policy_fallback": "Fixed question, model text broke a reply rule",
        "next_question": "Fixed next question, model wrote nothing",
        "guardrail_redirect": "Fixed guardrail redirect",
    },
    "tone": {
        "neutral": "Neutral",
        "positive": "Positive",
        "confused": "Confused",
        "frustrated": "Frustrated",
    },
    "profile_field": {
        "full_name": "Full name",
        "has_licence": "Driving licence",
        "zone": "Zone",
        "availability": "Availability",
        "schedule": "Schedule",
        "experience_years": "Years of experience",
        "experience_platforms": "Delivery platforms",
        "start_date": "Start date",
    },
}


def humanise(text: str) -> str:
    return text.replace("_", " ").capitalize()


def label(value: object, kind: str) -> str:
    """Unknown values (a retired stage, a new event kind) fall back to the humanised raw value."""
    text = str(value)
    return LABELS[kind].get(text) or humanise(text)
