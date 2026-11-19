"""Buttons for the data flow: refresh Kalshi data, refresh FRED, scan now, auto-scan.
Writes require the X-KRT-Request: ops header (CSRF) on top of the Origin allow-list."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Request, Response
from pydantic import BaseModel

from app.api.errors import ApiError, ErrorCode
from app.jobs import JOB_NAMES

router = APIRouter(prefix="/api/jobs")


def _csrf(v: str | None) -> None:
    if v != "ops":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")


class AutoScanIn(BaseModel):
    enabled: bool


@router.get("")
def jobs_status(request: Request) -> dict[str, Any]:
    return request.app.state.jobs.snapshot()


@router.post("/{name}/run", status_code=202)
def run_job(name: Annotated[str, Path(pattern=r"^[a-z]+$", max_length=16)], request: Request,
            response: Response,
            x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
            ) -> dict[str, Any]:
    _csrf(x_krt_request)
    if name not in JOB_NAMES:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"Unknown job; use one of {list(JOB_NAMES)}")
    started = request.app.state.jobs.run(name)
    if not started:
        response.status_code = 409
    return {"started": started, **request.app.state.jobs.snapshot()}


@router.post("/auto-scan")
def auto_scan(body: AutoScanIn, request: Request,
              x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
              ) -> dict[str, Any]:
    _csrf(x_krt_request)
    ok, reason = request.app.state.jobs.set_auto_scan(body.enabled)
    if not ok:
        raise ApiError(409, ErrorCode.VALIDATION_ERROR, reason or "Cannot start auto-scan")
    return request.app.state.jobs.snapshot()
