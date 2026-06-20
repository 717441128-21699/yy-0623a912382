from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    NotificationResponse,
    NotificationListQuery,
    NotificationListResponse,
    NotificationHandleRequest,
    NotificationRuleSetRequest,
    NotificationRuleToggleRequest,
    NotificationRuleListResponse,
)
from app.services.batch_service import NotificationService, NotificationRuleService, UserService
from app.services.notification_service import scan_and_notify_overdue
from app.enums import RoleEnum, NotificationTypeEnum

router = APIRouter(prefix="/notifications", tags=["通知待办"])


@router.post(
    "/list",
    response_model=NotificationListResponse,
    summary="查询通知待办列表",
    description="按接收人、角色、处理状态、通知类型筛选",
)
def list_notifications(
    query: NotificationListQuery,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    svc = NotificationService(db)
    total, items = svc.list_notifications(query, skip=skip, limit=limit)

    result_items = []
    for item in items:
        resp = NotificationResponse.model_validate(item)
        resp.batch_no = item.batch.batch_no if item.batch else ""
        result_items.append(resp)

    return NotificationListResponse(total=total, items=result_items)


@router.post(
    "/{notif_id}/read",
    response_model=NotificationResponse,
    summary="标记通知为已读",
)
def mark_read(
    notif_id: int,
    user_id: int = Query(..., description="当前操作用户ID"),
    db: Session = Depends(get_db),
):
    svc = NotificationService(db)
    notif, err = svc.mark_read(notif_id, user_id)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    resp = NotificationResponse.model_validate(notif)
    resp.batch_no = notif.batch.batch_no if notif.batch else ""
    return resp


@router.post(
    "/{notif_id}/handle",
    response_model=NotificationResponse,
    summary="处理通知待办（标记已处理+备注）",
)
def handle_notification(
    notif_id: int,
    req: NotificationHandleRequest,
    user_id: int = Query(..., description="当前操作用户ID"),
    db: Session = Depends(get_db),
):
    svc = NotificationService(db)
    notif, err = svc.handle_notification(notif_id, user_id, req)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    resp = NotificationResponse.model_validate(notif)
    resp.batch_no = notif.batch.batch_no if notif.batch else ""
    return resp


@router.post(
    "/scan-overdue",
    summary="定时扫描复检逾期批次并发送通知",
    description="供调度器/定时器调用，扫描所有处于待复检且超过期限的批次并推送通知",
)
def scan_overdue(db: Session = Depends(get_db)):
    result = scan_and_notify_overdue(db)
    return {
        "message": "扫描完成",
        "scanned_count": result["scanned"],
        "notified_count": result["notified"],
    }


@router.get(
    "/rules",
    response_model=NotificationRuleListResponse,
    summary="查询项目通知规则（事件→角色）",
    description="返回指定项目所有事件的通知规则，含自定义规则+默认值（未配置的返回默认）",
)
def list_notification_rules(
    project_id: str = Query(..., description="项目ID"),
    db: Session = Depends(get_db),
):
    svc = NotificationRuleService(db)
    return svc.list_rules(project_id)


@router.post(
    "/rules",
    response_model=NotificationRuleListResponse,
    summary="设置项目通知规则（仅项目经理）",
    description="为指定事件配置要推送的角色列表，若传入空数组则表示该事件不推送给任何角色；仅项目所属项目经理可操作",
)
def set_notification_rule(
    req: NotificationRuleSetRequest,
    created_by: int = Query(..., description="当前操作人用户ID（项目经理）"),
    db: Session = Depends(get_db),
):
    user_svc = UserService(db)
    user = user_svc.get_user(created_by)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="操作用户不存在")
    if user.role != RoleEnum.PROJECT_MANAGER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅项目经理可配置通知规则")
    if user.project_id != req.project_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅可配置所属项目的通知规则")

    svc = NotificationRuleService(db)
    data, err = svc.set_rule(req.project_id, req.event_type, req.roles, created_by)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return data


@router.post(
    "/rules/toggle",
    response_model=NotificationRuleListResponse,
    summary="启用/停用指定事件的通知规则（仅项目经理）",
    description="临时停用或恢复某个事件的推送，停用后该事件不再生成任何通知；仅项目所属项目经理可操作",
)
def toggle_notification_rule(
    req: NotificationRuleToggleRequest,
    operator_id: int = Query(..., description="当前操作人用户ID（项目经理）"),
    db: Session = Depends(get_db),
):
    user_svc = UserService(db)
    user = user_svc.get_user(operator_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="操作用户不存在")
    if user.role != RoleEnum.PROJECT_MANAGER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅项目经理可配置通知规则")
    if user.project_id != req.project_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅可配置所属项目的通知规则")

    svc = NotificationRuleService(db)
    data, err = svc.toggle_rule(req.project_id, req.event_type, req.enabled, operator_id)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return data
