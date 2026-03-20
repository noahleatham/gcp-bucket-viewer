from google.oauth2 import id_token
from google.auth.transport import requests
from fastapi import HTTPException, Header, Depends, Query
from typing import Optional
import os
import logging

from .permissions import get_user_rules

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
logger = logging.getLogger("uvicorn")

async def verify_google_token(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
):
    """
    Verifies the Google ID token sent in the Authorization header or token query parameter.
    Format: "Bearer <token>" or "?token=<token>"
    """
    if not CLIENT_ID:
        logger.warning("GOOGLE_CLIENT_ID not set. Skipping auth verification (INSECURE).")
        return {"sub": "dev-user", "email": "dev@example.com"}

    id_token_str = None
    if authorization and authorization.startswith("Bearer "):
        id_token_str = authorization.split(" ")[1]
    elif token:
        id_token_str = token

    if not id_token_str:
        raise HTTPException(status_code=401, detail="Missing Authorization header or token")

    try:
        # Verify token
        id_info = id_token.verify_oauth2_token(id_token_str, requests.Request(), CLIENT_ID)

        # Verify user exists in permissions.json
        user_email = id_info.get('email')
        if get_user_rules(user_email) is None:
            logger.warning(f"Unauthorized access attempt by {user_email}")
            raise HTTPException(status_code=403, detail="User not authorized")

        return id_info
    except ValueError as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
