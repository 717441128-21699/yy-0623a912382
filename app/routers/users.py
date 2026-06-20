from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import UserCreate, UserResponse
from app.services.batch_service import UserService
from app.enums import RoleEnum

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建用户",
    description="创建材料员、质检员、项目经理、监理、门禁人员等角色用户",
)
def create_user(
    req: UserCreate,
    db: Session = Depends(get_db),
):
    svc = UserService(db)
    user, created = svc.create_user(
        username=req.username,
        full_name=req.full_name,
        role=req.role,
        phone=req.phone,
        project_id=req.project_id,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )
    return user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="查询单个用户",
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    svc = UserService(db)
    user = svc.get_user(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


@router.get(
    "/",
    response_model=List[UserResponse],
    summary="查询用户列表",
    description="可按项目ID和角色筛选",
)
def list_users(
    project_id: Optional[str] = Query(None, description="项目ID"),
    role: Optional[RoleEnum] = Query(None, description="角色"),
    db: Session = Depends(get_db),
):
    svc = UserService(db)
    return svc.list_users(project_id=project_id, role=role)
