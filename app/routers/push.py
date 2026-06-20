from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    PushChannelCreate,
    PushChannelUpdate,
    PushChannelResponse,
    DeliveryRecordResponse,
    DeliveryRecordListQuery,
    DeliveryRecordListResponse,
    ManualPushRequest,
)
from app.services.batch_service import PushChannelService, DeliveryService

router = APIRouter(prefix="/push", tags=["外部推送"])


@router.post(
    "/channels",
    response_model=PushChannelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建推送通道",
    description="为企业App或消息网关配置回调地址，通知生成时自动投递",
)
def create_channel(
    req: PushChannelCreate,
    db: Session = Depends(get_db),
):
    svc = PushChannelService(db)
    channel = svc.create_channel(req)
    return channel


@router.put(
    "/channels/{channel_id}",
    response_model=PushChannelResponse,
    summary="更新推送通道",
)
def update_channel(
    channel_id: int,
    req: PushChannelUpdate,
    db: Session = Depends(get_db),
):
    svc = PushChannelService(db)
    channel, err = svc.update_channel(channel_id, req)
    if err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    return channel


@router.delete(
    "/channels/{channel_id}",
    summary="删除推送通道",
)
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
):
    svc = PushChannelService(db)
    ok, err = svc.delete_channel(channel_id)
    if err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    return {"message": "删除成功"}


@router.get(
    "/channels",
    response_model=list[PushChannelResponse],
    summary="查询推送通道列表",
)
def list_channels(
    project_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    svc = PushChannelService(db)
    return svc.list_channels(project_id=project_id, enabled=enabled)


@router.post(
    "/deliveries",
    response_model=DeliveryRecordListResponse,
    summary="查询投递记录（支持多维度筛选）",
    description="按通知ID、通道ID、投递状态、批次号、接收人ID/角色、项目ID筛选，按尝试编号升序展示，可看到每次投递耗时和是否最终闭环",
)
def list_deliveries(
    query: DeliveryRecordListQuery,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    svc = DeliveryService(db)
    total, items = svc.list_records(query, skip=skip, limit=limit)
    result = []
    success_cnt = 0
    last_time = None
    for item in items:
        resp = DeliveryRecordResponse.model_validate(item)
        resp.channel_name = item.channel.name if item.channel else None
        notif = item.notification
        if notif:
            resp.notification_type = notif.type.value if notif.type else None
            resp.recipient_id = notif.recipient_id
            resp.recipient_role = notif.recipient_role.value if notif.recipient_role else None
            if notif.batch:
                resp.batch_id = notif.batch.id
                resp.batch_no = notif.batch.batch_no
        result.append(resp)
        if item.status == "success":
            success_cnt += 1
        if last_time is None or (item.created_at and item.created_at > last_time):
            last_time = item.created_at
    return DeliveryRecordListResponse(
        total=total,
        items=result,
        final_closed=success_cnt > 0,
        last_attempt_at=last_time,
        success_attempts=success_cnt,
        failed_attempts=len(result) - success_cnt,
    )


@router.post(
    "/manual",
    response_model=DeliveryRecordListResponse,
    summary="手动重试投递（返回所有尝试记录）",
    description="对指定通知通过指定通道手动重新推送，返回该通道该通知的所有投递记录（含历史）",
)
def manual_push(
    req: ManualPushRequest,
    db: Session = Depends(get_db),
):
    svc = DeliveryService(db)
    records, err = svc.manual_push(req.notification_id, req.channel_id)
    if err and not records:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    result = []
    success_cnt = 0
    last_time = None
    for record in records:
        resp = DeliveryRecordResponse.model_validate(record)
        resp.channel_name = record.channel.name if record.channel else None
        notif = record.notification
        if notif:
            resp.notification_type = notif.type.value if notif.type else None
            resp.recipient_id = notif.recipient_id
            resp.recipient_role = notif.recipient_role.value if notif.recipient_role else None
            if notif.batch:
                resp.batch_id = notif.batch.id
                resp.batch_no = notif.batch.batch_no
        result.append(resp)
        if record.status == "success":
            success_cnt += 1
        if last_time is None or (record.created_at and record.created_at > last_time):
            last_time = record.created_at

    return DeliveryRecordListResponse(
        total=len(result),
        items=result,
        final_closed=success_cnt > 0,
        last_attempt_at=last_time,
        success_attempts=success_cnt,
        failed_attempts=len(result) - success_cnt,
    )
