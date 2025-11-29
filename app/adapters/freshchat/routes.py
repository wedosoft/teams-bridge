"""Freshchat Webhook 라우트"""
from fastapi import APIRouter, Request, Response, HTTPException

from app.config import get_settings
from app.adapters.freshchat.webhook import FreshchatWebhookHandler
from app.core.router import get_message_router
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# 웹훅 핸들러 싱글톤
_webhook_handler: FreshchatWebhookHandler | None = None


def get_webhook_handler() -> FreshchatWebhookHandler:
    """Freshchat Webhook 핸들러 싱글톤"""
    global _webhook_handler
    if _webhook_handler is None:
        settings = get_settings()
        _webhook_handler = FreshchatWebhookHandler(
            public_key=settings.freshchat_webhook_public_key,
        )
    return _webhook_handler


@router.post("")
async def freshchat_webhook(request: Request) -> Response:
    """Freshchat Webhook 엔드포인트

    Freshchat에서 들어오는 웹훅 이벤트 처리:
    - message_create: 상담원 메시지
    - conversation_resolution: 대화 종료
    """
    try:
        # Raw body 읽기 (서명 검증용)
        raw_body = await request.body()

        # 서명 검증
        signature = request.headers.get("x-freshchat-signature", "")
        handler = get_webhook_handler()

        if signature:
            if not handler.verify_signature(raw_body, signature):
                logger.warning("Invalid webhook signature")
                raise HTTPException(status_code=401, detail="Invalid signature")
        else:
            # 개발 환경에서는 서명 없이도 허용 (설정에 따라)
            settings = get_settings()
            if settings.freshchat_webhook_public_key:
                logger.warning("Missing webhook signature")
                # 프로덕션에서는 거부해야 함
                # raise HTTPException(status_code=401, detail="Missing signature")

        # 페이로드 파싱
        payload = await request.json()
        action = payload.get("action", "")

        logger.debug(
            "Received Freshchat webhook",
            action=action,
        )

        # Webhook 이벤트 파싱
        event = handler.parse_webhook(payload)
        if not event:
            # 무시할 이벤트 (user 메시지 등)
            return Response(status_code=200)

        # 메시지 라우터로 전달
        message_router = get_message_router()
        await message_router.handle_freshchat_webhook(event)

        return Response(status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Freshchat webhook error", error=str(e))
        return Response(status_code=500)


@router.get("/health")
async def webhook_health() -> dict:
    """Webhook 헬스 체크

    Freshchat 웹훅 설정 확인용
    """
    settings = get_settings()
    return {
        "status": "ok",
        "webhook": "freshchat",
        "public_key_configured": bool(settings.freshchat_webhook_public_key),
    }
