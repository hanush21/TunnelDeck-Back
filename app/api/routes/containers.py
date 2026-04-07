from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_admin_user, get_settings_dependency
from app.core.schemas import PaginationMeta
from app.modules.auth.schemas import AuthenticatedUser
from app.modules.docker.schemas import ContainerListResponse, ContainerSummaryResponse
from app.modules.docker.service import DockerService

router = APIRouter()


def get_docker_service(
    settings=Depends(get_settings_dependency),
) -> DockerService:
    return DockerService(settings)


@router.get("", response_model=ContainerListResponse)
def list_containers(
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    docker_service: Annotated[DockerService, Depends(get_docker_service)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ContainerListResponse:
    all_items = sorted(
        docker_service.list_containers(),
        key=lambda container: (container.name, container.id),
    )
    total = len(all_items)
    items = all_items[offset : offset + limit]
    return ContainerListResponse(
        meta=PaginationMeta(total=total, limit=limit, offset=offset),
        items=items,
    )


@router.get("/{container_id}", response_model=ContainerSummaryResponse)
def get_container(
    container_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    docker_service: Annotated[DockerService, Depends(get_docker_service)],
) -> ContainerSummaryResponse:
    return docker_service.get_container(container_id)
