"""Model management API routes."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.services import ml_service

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/")
def list_models() -> list[dict[str, Any]]:
    """List all available trained models."""
    return ml_service.list_models()


@router.delete("/{model_id}")
def delete_model(model_id: str) -> dict[str, str]:
    """Delete a model by its filename stem."""
    models = ml_service.list_models()
    matching = [
        m for m in models if Path(m["filename"]).stem == model_id
    ]

    if not matching:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model not found: {model_id}",
        )

    model = matching[0]
    try:
        ml_service.delete_model(model["path"])
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model not found: {model_id}",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    return {"status": "deleted"}
