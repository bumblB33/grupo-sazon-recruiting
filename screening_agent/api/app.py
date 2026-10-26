import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from screening_agent.api.deps import (
    get_engine,
    get_repository,
    get_whatsapp_outbound,
    require_recruiter,
)
from screening_agent.channels.whatsapp import (
    InboundWhatsAppMessage,
    twiml_reply,
    verify_twilio_signature,
)
from screening_agent.config import settings
from screening_agent.domain.enums import Language, Status
from screening_agent.flow.engine import OutboundChannel, ScreeningEngine
from screening_agent.recruiter.router import recruiter_router
from screening_agent.storage.models import Candidate, CandidateDetail
from screening_agent.storage.repository import Repository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.dev_mode:
        logger.warning("SCREENING_DEV_MODE is on: unauthenticated recruiter routes and webhook")
    if not settings.recruiter_api_key:
        logger.warning("SCREENING_RECRUITER_API_KEY is unset")
    if not settings.twilio_auth_token:
        logger.warning("SCREENING_TWILIO_AUTH_TOKEN is unset")
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


class StartResponse(BaseModel):
    candidate_id: str
    status: Status = Status.IN_PROGRESS


@app.post("/webhook/whatsapp")
def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    message: InboundWhatsAppMessage = Depends(verified_webhook_message),
    engine: ScreeningEngine = Depends(get_engine),
) -> Response:
    result = engine.handle(
        message.from_phone, message.text, channel="whatsapp", external_id=message.message_id
    )
    if result.terminal:
        background_tasks.add_task(engine.summarize_outcome, message.from_phone)
    return Response(
        content=twiml_reply(result.reply),
        media_type="application/xml",
        headers={"X-Screening-Outcome": result.outcome},
    )


@app.post("/candidates", status_code=201, dependencies=[Depends(require_recruiter)])
def start_candidate(
    body: StartRequest,
    engine: ScreeningEngine = Depends(get_engine),
    outbound: OutboundChannel = Depends(get_whatsapp_outbound),
) -> StartResponse:
    started = engine.start_conversation(body.phone, "whatsapp", body.language, outbound)
    if not started:
        raise HTTPException(status_code=409, detail="candidate already exists")
    return StartResponse(candidate_id=body.phone)


@app.get("/candidates", dependencies=[Depends(require_recruiter)])
def list_candidates(
    status: str | None = None,
    stage: str | None = None,
    repository: Repository = Depends(get_repository),
) -> list[Candidate]:
    return repository.list_candidates(status=status, stage=stage)


@app.get("/candidates/{candidate_id}", dependencies=[Depends(require_recruiter)])
def get_candidate(
    candidate_id: str, repository: Repository = Depends(get_repository)
) -> CandidateDetail:
    candidate = repository.get_candidate_detail(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate


@app.patch("/candidates/{candidate_id}", dependencies=[Depends(require_recruiter)])
def override_candidate(
    candidate_id: str, body: OverrideRequest, repository: Repository = Depends(get_repository)
) -> Candidate:
    candidate = repository.override(candidate_id, body.status, body.notes)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate


@app.get("/analytics", dependencies=[Depends(require_recruiter)])
def analytics(repository: Repository = Depends(get_repository)) -> dict:
    return repository.funnel()
