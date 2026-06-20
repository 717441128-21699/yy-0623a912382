from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    BatchRegisterRequest,
    BatchRegisterResponse,
    BatchDetailResponse,
    BatchListQuery,
    BatchListResponse,
    BatchListItem,
    DashboardResponse,
    TodolistResponse,
)
from app.services.batch_service import (
    BatchService,
    DashboardService,
    TodolistService,
)

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
    "/dashboard",
    response_model=DashboardResponse,
    summary="项目批次流程看板",
    description="按项目汇总各状态数量、逾期复检数量、待材料员处理数量、待质检员处理数量，供项目 App 首页直接展示",
)
def get_dashboard(
    project_id: str = Query(..., description="项目编号"),
    db: Session = Depends(get_db),
):
    svc = DashboardService(db)
    return svc.get_project_dashboard(project_id)


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


@router.get(
    "/{batch_no}",
    response_model=BatchDetailResponse,
    summary="按批次号查询详情（含当前责任人+可流转节点+流程时间线）",
    description="查询当前节点、责任人角色、下一步可走节点、历史流转、通知、外部投递统一时间线",
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


@router.get(
    "/todolist/mine",
    response_model=TodolistResponse,
    summary="当前登录人待办聚合",
    description=(
        "按登录人角色聚合待办：材料员→待卸货批次、质检员→待验收/复检批次、"
        "监理→待审批批次、项目经理→异常批次（逾期复检+驳回）+ 未处理通知"
    ),
)
def get_my_todolist(
    user_id: int = Query(..., description="当前登录用户ID"),
    db: Session = Depends(get_db),
):
    svc = TodolistService(db)
    data, err = svc.get_todolist(user_id)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return data
