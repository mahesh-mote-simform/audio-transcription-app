
import logging

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings


logger = logging.getLogger(__name__)

# JWT configuration
JWT_SECRET_KEY = settings.jwt_secret_key
JWT_ALGORITHM = settings.jwt_algorithm

security = HTTPBearer()


# Verify JWT token and extract user ID
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:

    if not JWT_SECRET_KEY:
        logger.critical("JWT_SECRET_KEY is not configured")
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]}
        )

        user_id = payload.get("sub")

        if not user_id:
            logger.warning("Rejected token without a user ID")
            raise HTTPException(
                status_code=401,
                detail="Invalid token: user ID is missing"
            )

        return user_id

    except jwt.ExpiredSignatureError:
        logger.warning("Rejected expired token")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    except jwt.InvalidTokenError as error:
        logger.warning("Rejected invalid token: %s", error)
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )
