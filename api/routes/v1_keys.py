"""
api/routes/v1_keys.py — Gestion des clés API Bearer (cookie-protected).

Ces endpoints sont consommés depuis le dashboard (session cookie), pas depuis
l'app mobile : ils permettent à l'utilisateur de minter / lister / révoquer
les clés qu'il utilisera ensuite avec /api/v1/*.
"""

from fastapi import APIRouter, Depends, HTTPException

from api import api_keys
from api.dependencies import get_current_user
from api.v1_schemas import (
    ApiKeyListItem, ApiKeyListResponse,
    ApiKeyMintBody, ApiKeyMintResponse,
)

router = APIRouter(prefix="/api/auth/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyMintResponse, summary="Génère une nouvelle clé API")
def mint(body: ApiKeyMintBody, user: dict = Depends(get_current_user)):
    result = api_keys.mint(user["id"], body.label)
    return ApiKeyMintResponse(**result)


@router.get("", response_model=ApiKeyListResponse, summary="Liste les clés de l'utilisateur")
def list_keys(user: dict = Depends(get_current_user)):
    rows = api_keys.list_for_user(user["id"])
    return ApiKeyListResponse(keys=[ApiKeyListItem(**r) for r in rows])


@router.delete("/{key_id}", summary="Révoque une clé API")
def revoke(key_id: str, user: dict = Depends(get_current_user)):
    ok = api_keys.revoke(user["id"], key_id)
    if not ok:
        raise HTTPException(404, detail={"error": "not_found", "message": "Clé inconnue."})
    return {"ok": True}
