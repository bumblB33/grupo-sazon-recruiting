import logging
from contextlib import asynccontextmanager

from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, Field, field_validator

from screening_agent.api.auth import Principal
from screening_agent.api.deps import (
    RECRUITER_COOKIE,
    get_engine,
    get_repository,
    get_whatsapp_outbound,
    require_recruiter,
    require_recruiter_write,
    session_csrf_token,
)
from screening_agent.channels.whatsapp import (
    InboundWhatsAppMessage,
    twiml_reply,
    verify_twilio_signature,
)
from screening_agent.config import settings
from screening_agent.domain.enums import Language, Stage, Status
from screening_agent.domain.names import clean_applicant_name
from screening_agent.flow import replies
from screening_agent.flow.engine import OutboundChannel, Outcome, ScreeningEngine
from screening_agent.observability import configure_observability
from screening_agent.recruiter.router import recruiter_router
from screening_agent.storage.models import Candidate, CandidateDetail
from screening_agent.storage.repository import Repository

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.dev_mode:
        logger.warning("SCREENING_DEV_MODE is on: unauthenticated recruiter routes and webhook")
    if not settings.session_secret:
        logger.warning("SCREENING_SESSION_SECRET is unset")
    if not settings.recruiter_email_domains:
        logger.warning("SCREENING_RECRUITER_EMAIL_DOMAINS is empty: no recruiter can log in")
    if not settings.twilio_auth_token:
        logger.warning("SCREENING_TWILIO_AUTH_TOKEN is unset")
    if settings.logfire_token:
        configure_observability("screening-api", app)
        if not settings.candidate_hash_secret:
            logger.warning("SCREENING_CANDIDATE_HASH_SECRET is unset: traces carry no candidate id")
    else:
        logger.warning("SCREENING_LOGFIRE_TOKEN is unset: tracing is off")
    yield


app = FastAPI(title="Grupo Sazón screening agent", lifespan=lifespan)
app.include_router(recruiter_router)


async def verified_webhook_message(
    request: Request, x_twilio_signature: str | None = Header(default=None)
) -> InboundWhatsAppMessage:
    form = {key: str(value) for key, value in (await request.form()).items()}
    if settings.twilio_auth_token is None:
        if not settings.dev_mode:
            raise HTTPException(status_code=503, detail="twilio auth token not configured")
    else:
        url = settings.twilio_webhook_url or str(request.url)
        if not verify_twilio_signature(
            url, form, x_twilio_signature, settings.twilio_auth_token.get_secret_value()
        ):
            raise HTTPException(status_code=401, detail="invalid twilio signature")
    try:
        return InboundWhatsAppMessage.from_twilio_form(form)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"missing form field {exc}") from exc


class OverrideRequest(BaseModel):
    status: Status | None = None
    notes: str | None = None


class StartRequest(BaseModel):
    """An application arrived; open the WhatsApp screening with the opener template."""

    phone: str = Field(pattern=r"^\+[1-9]\d{6,14}$", description="E.164, the candidate id")
    language: Language = Language.ES
    name: str | None = Field(
        default=None,
        max_length=120,
        description="Applicant name from the application; personalises the opener and is checked "
        "against the name the candidate gives",
    )

    @field_validator("name")
    @classmethod
    def name_is_made_of_words(cls, value: str | None) -> str | None:
        return None if value is None else clean_applicant_name(value)


class StartResponse(BaseModel):
    candidate_id: str
    status: Status = Status.IN_PROGRESS


@app.post("/webhook/whatsapp")
def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    message: InboundWhatsAppMessage = Depends(verified_webhook_message),
    engine: ScreeningEngine = Depends(get_engine),
) -> Response:
    """A number with no application gets a fixed reply and no model call, so the first message a
    candidate ever receives is the opener with its AI disclosure."""
    result = engine.handle(
        message.from_phone,
        message.text,
        channel="whatsapp",
        external_id=message.message_id,
    )
    if result.outcome == Outcome.UNKNOWN:
        return _twiml(replies.unknown_number(), Outcome.UNKNOWN)
    if result.terminal:
        background_tasks.add_task(engine.summarize_outcome, message.from_phone)
    return _twiml(result.reply, result.outcome)


def _twiml(reply: str, outcome: Outcome) -> Response:
    return Response(
        content=twiml_reply(reply),
        media_type="application/xml",
        headers={"X-Screening-Outcome": outcome},
    )


@app.post("/candidates", status_code=201, dependencies=[Depends(require_recruiter_write)])
def start_candidate(
    body: StartRequest,
    engine: ScreeningEngine = Depends(get_engine),
    outbound: OutboundChannel = Depends(get_whatsapp_outbound),
) -> StartResponse:
    started = engine.start_conversation(
        body.phone, "whatsapp", body.language, outbound, applicant_name=body.name
    )
    if not started:
        raise HTTPException(status_code=409, detail="candidate already exists")
    return StartResponse(candidate_id=body.phone)


@app.get("/candidates", dependencies=[Depends(require_recruiter)])
def list_candidates(
    status: Status | None = None,
    stage: Stage | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    repository: Repository = Depends(get_repository),
) -> list[Candidate]:
    return repository.list_candidates(status=status, stage=stage, limit=limit, offset=offset)


@app.get("/candidates/{candidate_id}", dependencies=[Depends(require_recruiter)])
def get_candidate(
    candidate_id: str, repository: Repository = Depends(get_repository)
) -> CandidateDetail:
    candidate = repository.get_candidate_detail(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate


@app.patch("/candidates/{candidate_id}")
def override_candidate(
    candidate_id: str,
    body: OverrideRequest,
    repository: Repository = Depends(get_repository),
    principal: Principal = Depends(require_recruiter_write),
) -> Candidate:
    candidate = repository.override(candidate_id, body.status, body.notes, principal.label)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate


@app.get("/analytics", dependencies=[Depends(require_recruiter)])
def analytics(repository: Repository = Depends(get_repository)) -> dict:
    return repository.funnel()


@app.get("/csrf-token")
def get_csrf_token(
    principal: Principal = Depends(require_recruiter),
    recruiter_session: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
) -> dict[str, str | None]:
    """Cookie callers echo this in X-CSRF-Token on JSON writes; API-key callers get null."""
    return {"csrf_token": session_csrf_token(principal, recruiter_session)}
