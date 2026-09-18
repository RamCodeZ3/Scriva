from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectGoogleCredentialsRequest(BaseModel):
    authorization_code: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)
    code_verifier: str | None = Field(default=None, min_length=43)


class ConnectGoogleCredentialsResponse(BaseModel):
    status: str
