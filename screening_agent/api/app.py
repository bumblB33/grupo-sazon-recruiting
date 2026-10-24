import logging
from contextlib import asynccontextmanager
from functools import cache

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

from screening_agent.channels.whatsapp import (
    InboundWhatsAppMessage,
    twiml_reply,
    verify_twilio_signature,
)
from screening_agent.config import settings
from screening_agent.domain.enums import Status
from screening_agent.flow.engine import ScreeningEngine
from screening_agent.storage.models import Candidate
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


@cache
def get_repository() -> Repository:
    return Repository()


@cache
def get_engine() -> ScreeningEngine:
    return ScreeningEngine(get_repository())


def require_recruiter(x_api_key: str | None = Header(default=None)) -> None:
    """Fails closed: no configured key means no access, unless dev mode is on."""
    if settings.recruiter_api_key is None:
        if settings.dev_mode:
            return
        raise HTTPException(status_code=503, detail="recruiter api key not configured")
    if x_api_key != settings.recruiter_api_key:
        raise HTTPException(status_code=401, detail="recruiter api key required")


async def verified_webhook_message(
    request: Request, x_twilio_signature: str | None = Header(default=None)
) -> InboundWhatsAppMessage:
    form = {key: str(value) for key, value in (await request.form()).items()}
    if settings.twilio_auth_token is None:
        if not settings.dev_mode:
            raise HTTPException(status_code=503, detail="twilio auth token not configured")
    else:
        url = settings.twilio_webhook_url or str(request.url)
        if not verify_twilio_signature(url, form, x_twilio_signature, settings.twilio_auth_token):
            raise HTTPException(status_code=401, detail="invalid twilio signature")
    try:
        return InboundWhatsAppMessage.from_twilio_form(form)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"missing form field {exc}") from exc


class OverrideRequest(BaseModel):
    status: Status | None = None
    notes: str | None = None


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


@app.get("/candidates", dependencies=[Depends(require_recruiter)])
def list_candidates(
    status: str | None = None,
    stage: str | None = None,
    repository: Repository = Depends(get_repository),
) -> list[Candidate]:
    return repository.list_candidates(status=status, stage=stage)


@app.get("/candidates/{candidate_id}", dependencies=[Depends(require_recruiter)])
def get_candidate(candidate_id: str, repository: Repository = Depends(get_repository)) -> Candidate:
    candidate = repository.get_candidate(candidate_id)
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
    repository.record_event(candidate_id, "recruiter_override", body.model_dump(mode="json"))
    return candidate


@app.get("/analytics", dependencies=[Depends(require_recruiter)])
def analytics(repository: Repository = Depends(get_repository)) -> dict:
    return repository.funnel()
