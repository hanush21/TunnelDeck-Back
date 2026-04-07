from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_admin_user, get_settings_dependency
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
) -> ContainerListResponse:
    items = docker_service.list_containers()
    return ContainerListResponse(items=items)


@router.get("/{container_id}", response_model=ContainerSummaryResponse)
def get_container(
    container_id: str,
    _: Annotated[AuthenticatedUser, Depends(get_current_admin_user)],
    docker_service: Annotated[DockerService, Depends(get_docker_service)],
) -> ContainerSummaryResponse:
    return docker_service.get_container(container_id)
