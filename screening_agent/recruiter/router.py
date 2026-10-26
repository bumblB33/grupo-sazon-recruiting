import json
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from screening_agent.api.deps import RECRUITER_COOKIE, get_repository, recruiter_key_is_valid
from screening_agent.domain.enums import Stage, Status
from screening_agent.storage.repository import Repository

RECRUITER_PREFIX = "/recruiter"
LOGIN_PATH = f"{RECRUITER_PREFIX}/login"
STATUSES = list(Status)
STAGES = list(Stage)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def require_recruiter_page(
    recruiter_key: str | None = Cookie(default=None, alias=RECRUITER_COOKIE),
) -> None:
    """A browser without a valid cookie is sent to the login form instead of a 401."""
    if not recruiter_key_is_valid(recruiter_key):
        raise HTTPException(status_code=303, headers={"Location": LOGIN_PATH})


recruiter_router = APIRouter(prefix=RECRUITER_PREFIX, tags=["recruiter"])
authenticated_pages = APIRouter(dependencies=[Depends(require_recruiter_page)])


@recruiter_router.get("/login")
def login_form(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@recruiter_router.post("/login")
def login(request: Request, key: str = Form()) -> Response:
    if not recruiter_key_is_valid(key):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong key"}, status_code=401
        )
    response = RedirectResponse(f"{RECRUITER_PREFIX}/", status_code=303)
    # Secure follows the scheme the app sees, so a plain-http demo does not loop on login.
    response.set_cookie(
        RECRUITER_COOKIE,
        key,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@recruiter_router.post("/logout")
def logout() -> Response:
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(RECRUITER_COOKIE)
    return response


@authenticated_pages.get("/")
def candidate_list(
    request: Request,
    status: str | None = None,
    stage: str | None = None,
    repository: Repository = Depends(get_repository),
) -> Response:
    return templates.TemplateResponse(
        request,
        "candidates.html",
        {
            "candidates": repository.list_candidates(status=status, stage=stage),
            "funnel": repository.funnel(),
            "status": status,
            "stage": stage,
            "statuses": STATUSES,
            "stages": STAGES,
        },
    )


@authenticated_pages.get("/candidates/{candidate_id}")
def candidate_page(
    request: Request, candidate_id: str, repository: Repository = Depends(get_repository)
) -> Response:
    candidate = repository.get_candidate_detail(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return templates.TemplateResponse(
        request,
        "candidate.html",
        {
            "candidate": candidate,
            "profile_json": json.dumps(candidate.profile, indent=2, ensure_ascii=False),
            "statuses": STATUSES,
            "stages": STAGES,
        },
    )


@authenticated_pages.post("/candidates/{candidate_id}/override")
def override_form(
    candidate_id: str,
    status: str = Form(default=""),
    notes: str = Form(default=""),
    repository: Repository = Depends(get_repository),
) -> Response:
    """An empty status keeps the current one; an empty textarea clears the notes."""
    try:
        new_status = Status(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown status {status!r}") from exc
    if repository.override(candidate_id, new_status, notes) is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return RedirectResponse(f"{RECRUITER_PREFIX}/candidates/{candidate_id}", status_code=303)


recruiter_router.include_router(authenticated_pages)
