from dataclasses import dataclass

from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import supabase, DatabaseConfigurationError, explain_supabase_api_error

security = HTTPBearer()

@dataclass
class AuthenticatedUser:
    id: str
    access_token: str
    raw_user: object


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        user_res = supabase.auth.get_user(token)
        if not user_res or not user_res.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token or expired session"
            )
        return AuthenticatedUser(
            id=user_res.user.id,
            access_token=token,
            raw_user=user_res.user
        )
    except DatabaseConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {explain_supabase_api_error(e)}"
        )
