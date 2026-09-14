from __future__ import annotations

from application.use_cases.connect_google_credentials_use_case import (
    ConnectGoogleCredentialsInput,
    ConnectGoogleCredentialsUseCase,
)
from domain.entities.user import User
from fastapi import APIRouter, Depends

from api.deps import (
    get_connect_google_credentials_use_case,
    get_current_user,
)
from api.schemas.google_credentials import (
    ConnectGoogleCredentialsRequest,
    ConnectGoogleCredentialsResponse,
)

router = APIRouter(prefix="/api/v1/google", tags=["google"])


@router.post("/credentials", response_model=ConnectGoogleCredentialsResponse)
async def connect_google_credentials(
    body: ConnectGoogleCredentialsRequest,
    current_user: User = Depends(get_current_user),
    use_case: ConnectGoogleCredentialsUseCase = Depends(
        get_connect_google_credentials_use_case
    ),
) -> ConnectGoogleCredentialsResponse:
    await use_case.execute(
        ConnectGoogleCredentialsInput(
            user_id=current_user.id,
            authorization_code=body.authorization_code,
            redirect_uri=body.redirect_uri,
            code_verifier=body.code_verifier,
        )
    )
    return ConnectGoogleCredentialsResponse(status="connected")
