from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    BatchRegisterRequest,
    BatchRegisterResponse,
    BatchDetailResponse,
    BatchListQuery,
    BatchListResponse,
    BatchListItem,
)
from app.services.batch_service import BatchService

router = APIRouter(prefix="/batches", tags=["批次管理"])


@router.post(
    "/register",
    response_model=BatchRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="项目App提交材料批次登记",
    description="传入供应商、材料类别、规格、数量、合同编号和附件，返回唯一批次号",
)
def register_batch(
    req: BatchRegisterRequest,
    db: Session = Depends(get_db),
):
    svc = BatchService(db)
    batch, err = svc.register_batch(req)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return BatchRegisterResponse(batch_no=batch.batch_no)


@router.get(
    "/{batch_no}",
    response_model=BatchDetailResponse,
    summary="按批次号查询详情（含当前责任人+可流转节点）",
    description="查询当前节点、责任人角色、下一步可走哪些节点及对应有权限的角色、历史流转记录、附件等",
)
def get_batch_detail(
    batch_no: str,
    db: Session = Depends(get_db),
):
    svc = BatchService(db)
    detail = svc.get_batch_detail(batch_no)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批次不存在")
    return detail


@router.post(
    "/list",
    response_model=BatchListResponse,
    summary="按条件查询批次列表",
    description="支持按项目、状态、供应商、材料类别、合同编号筛选",
)
def list_batches(
    query: BatchListQuery,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    svc = BatchService(db)
    total, items = svc.list_batches(query, skip=skip, limit=limit)
    return BatchListResponse(total=total, items=[BatchListItem.model_validate(i) for i in items])
