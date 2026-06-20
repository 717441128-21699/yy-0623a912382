from typing import Optional
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
    summary="查询投递记录",
    description="按通知ID、通道ID、投递状态筛选，追踪每次投递的成功/失败/重试",
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
    for item in items:
        resp = DeliveryRecordResponse.model_validate(item)
        resp.channel_name = item.channel.name if item.channel else None
        result.append(resp)
    return DeliveryRecordListResponse(total=total, items=result)


@router.post(
    "/manual",
    response_model=DeliveryRecordResponse,
    summary="手动重试投递",
    description="对指定通知通过指定通道手动重新推送（已成功投递的不会重复）",
)
def manual_push(
    req: ManualPushRequest,
    db: Session = Depends(get_db),
):
    svc = DeliveryService(db)
    record, err = svc.manual_push(req.notification_id, req.channel_id)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    resp = DeliveryRecordResponse.model_validate(record)
    resp.channel_name = record.channel.name if record.channel else None
    return resp
