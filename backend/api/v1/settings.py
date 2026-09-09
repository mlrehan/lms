"""System settings endpoints (spec §23).

Addressed by key, not by `public_id` — the one place in this API where the
stored primary key is the right thing to expose, because it is a name the
caller already knows rather than a sequential integer they would have to
enumerate to discover.

Reading is `setting.read` (Administrator and above); writing is
`setting.update`, which spec §2 gives to Super Admin alone: an Administrator
runs the institution's operations and does not change the rules those
operations run under.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.administration import SystemSetting
from backend.schemas.administration import SettingResponse, SettingWriteRequest
from backend.schemas.base import Page, PageParams
from backend.services.setting_service import SettingService

router = APIRouter(prefix="/settings", tags=["Settings"])

SettingKeyPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:[._][a-z0-9]+)*$",
        description="Lowercase dotted key, e.g. 'grading.pass_mark'.",
    ),
]


def _response(setting: SystemSetting) -> SettingResponse:
    return SettingResponse(
        key=setting.key, value=setting.value, description=setting.description
    )


@router.get("", response_model=Page[SettingResponse], summary="List system settings")
async def list_settings(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SETTING, Action.READ)))
    ],
    prefix: Annotated[str | None, Query(max_length=100, description="e.g. 'grading'.")] = None,
) -> Page[SettingResponse]:
    rows, total = await SettingService(session).list(params, prefix=prefix)
    return Page.build([_response(r) for r in rows], total=total, params=params)


@router.get("/{key}", response_model=SettingResponse, summary="Get one setting")
async def get_setting(
    key: SettingKeyPath,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SETTING, Action.READ)))
    ],
) -> SettingResponse:
    return _response(await SettingService(session).get(key))


@router.put("/{key}", response_model=SettingResponse, summary="Set a system setting")
async def put_setting(
    key: SettingKeyPath,
    payload: SettingWriteRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SETTING, Action.UPDATE)))
    ],
) -> SettingResponse:
    """Creates the key or updates it — `PUT` answers both, so there is no 409
    for setting a value that happens not to exist yet. Super Admin only."""
    return _response(await SettingService(session).put(key, payload, actor=actor))


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a setting")
async def delete_setting(
    key: SettingKeyPath,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.SETTING, Action.UPDATE)))
    ],
) -> Response:
    """Reverts the key to whatever the code treats as its default. The removed
    value is written to the audit log, because that is the first thing anyone
    asks afterwards."""
    await SettingService(session).delete(key, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
