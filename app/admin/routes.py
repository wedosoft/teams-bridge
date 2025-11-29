"""관리자 설정 API

Teams Tab에서 호출하는 테넌트 설정 API
- 테넌트 설정 조회/저장
- 플랫폼 연동 설정 (Freshchat/Zendesk)
- 웹훅 URL 생성
"""
from typing import Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Header, Depends

from app.config import get_settings
from app.core.tenant import (
    TenantService,
    TenantConfig,
    Platform,
    get_tenant_service,
)
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# ===== Request/Response Models =====

class FreshchatSetup(BaseModel):
    """Freshchat 설정"""
    api_key: str = Field(..., description="Freshchat API Key")
    api_url: str = Field(default="https://api.freshchat.com/v2", description="API URL")
    inbox_id: str = Field(default="", description="Inbox ID (선택)")
    webhook_public_key: str = Field(default="", description="Webhook Public Key (선택)")


class ZendeskSetup(BaseModel):
    """Zendesk 설정"""
    subdomain: str = Field(..., description="Zendesk 서브도메인 (예: mycompany)")
    email: str = Field(..., description="관리자 이메일")
    api_token: str = Field(..., description="API 토큰")


class TenantSetupRequest(BaseModel):
    """테넌트 설정 요청"""
    platform: str = Field(..., description="플랫폼 (freshchat/zendesk)")
    freshchat: Optional[FreshchatSetup] = None
    zendesk: Optional[ZendeskSetup] = None
    bot_name: str = Field(default="IT Helpdesk", description="봇 이름")
    welcome_message: str = Field(
        default="안녕하세요! IT 헬프데스크입니다. 무엇을 도와드릴까요?",
        description="환영 메시지",
    )


class TenantResponse(BaseModel):
    """테넌트 설정 응답"""
    teams_tenant_id: str
    platform: str
    bot_name: str
    welcome_message: str
    webhook_url: str
    is_configured: bool


class WebhookInfo(BaseModel):
    """웹훅 URL 정보"""
    platform: str
    webhook_url: str
    instructions: str


# ===== API Endpoints =====

async def get_tenant_id_from_header(
    x_ms_token_aad_access_token: Optional[str] = Header(None, alias="X-MS-TOKEN-AAD-ACCESS-TOKEN"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> str:
    """요청 헤더에서 테넌트 ID 추출

    Teams SSO 토큰 또는 X-Tenant-ID 헤더에서 추출
    """
    # 개발 환경: X-Tenant-ID 헤더 직접 사용
    if x_tenant_id:
        return x_tenant_id

    # TODO: Teams SSO 토큰에서 tenant_id 추출
    # if x_ms_token_aad_access_token:
    #     return extract_tenant_from_token(x_ms_token_aad_access_token)

    raise HTTPException(
        status_code=401,
        detail="Tenant ID not found. Provide X-Tenant-ID header.",
    )


@router.get("/config", response_model=TenantResponse)
async def get_tenant_config(
    tenant_id: str = Depends(get_tenant_id_from_header),
) -> TenantResponse:
    """현재 테넌트 설정 조회"""
    service = get_tenant_service()
    tenant = await service.get_tenant(tenant_id)

    settings = get_settings()
    base_url = settings.public_url or f"http://localhost:{settings.port}"

    if not tenant:
        return TenantResponse(
            teams_tenant_id=tenant_id,
            platform="",
            bot_name="IT Helpdesk",
            welcome_message="",
            webhook_url="",
            is_configured=False,
        )

    webhook_url = f"{base_url}/api/webhook/{tenant.platform.value}/{tenant_id}"

    return TenantResponse(
        teams_tenant_id=tenant_id,
        platform=tenant.platform.value,
        bot_name=tenant.bot_name,
        welcome_message=tenant.welcome_message,
        webhook_url=webhook_url,
        is_configured=True,
    )


@router.post("/config", response_model=TenantResponse)
async def save_tenant_config(
    request: TenantSetupRequest,
    tenant_id: str = Depends(get_tenant_id_from_header),
) -> TenantResponse:
    """테넌트 설정 저장

    사용자가 앱 설치 시 필수 값 입력 후 호출
    """
    # 플랫폼 검증
    try:
        platform = Platform(request.platform)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid platform: {request.platform}. Use 'freshchat' or 'zendesk'.",
        )

    # 플랫폼별 설정 검증
    platform_config: dict = {}

    if platform == Platform.FRESHCHAT:
        if not request.freshchat:
            raise HTTPException(status_code=400, detail="Freshchat configuration required")
        if not request.freshchat.api_key:
            raise HTTPException(status_code=400, detail="Freshchat API key required")

        platform_config = {
            "api_key": request.freshchat.api_key,
            "api_url": request.freshchat.api_url,
            "inbox_id": request.freshchat.inbox_id,
            "webhook_public_key": request.freshchat.webhook_public_key,
        }

    elif platform == Platform.ZENDESK:
        if not request.zendesk:
            raise HTTPException(status_code=400, detail="Zendesk configuration required")
        if not request.zendesk.subdomain or not request.zendesk.api_token:
            raise HTTPException(status_code=400, detail="Zendesk subdomain and API token required")

        platform_config = {
            "subdomain": request.zendesk.subdomain,
            "email": request.zendesk.email,
            "api_token": request.zendesk.api_token,
        }

    # 테넌트 생성/업데이트
    service = get_tenant_service()
    tenant = await service.create_tenant(
        teams_tenant_id=tenant_id,
        platform=platform,
        platform_config=platform_config,
        bot_name=request.bot_name,
        welcome_message=request.welcome_message,
    )

    if not tenant:
        raise HTTPException(status_code=500, detail="Failed to save configuration")

    settings = get_settings()
    base_url = settings.public_url or f"http://localhost:{settings.port}"
    webhook_url = f"{base_url}/api/webhook/{platform.value}/{tenant_id}"

    logger.info(
        "Tenant configured",
        tenant_id=tenant_id,
        platform=platform.value,
    )

    return TenantResponse(
        teams_tenant_id=tenant_id,
        platform=platform.value,
        bot_name=tenant.bot_name,
        welcome_message=tenant.welcome_message,
        webhook_url=webhook_url,
        is_configured=True,
    )


@router.delete("/config")
async def delete_tenant_config(
    tenant_id: str = Depends(get_tenant_id_from_header),
) -> dict:
    """테넌트 설정 삭제"""
    service = get_tenant_service()
    success = await service.delete_tenant(tenant_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete configuration")

    logger.info("Tenant deleted", tenant_id=tenant_id)

    return {"status": "deleted", "tenant_id": tenant_id}


@router.get("/webhook-info", response_model=WebhookInfo)
async def get_webhook_info(
    tenant_id: str = Depends(get_tenant_id_from_header),
) -> WebhookInfo:
    """웹훅 URL 및 설정 안내 조회"""
    service = get_tenant_service()
    tenant = await service.get_tenant(tenant_id)

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not configured")

    settings = get_settings()
    base_url = settings.public_url or f"http://localhost:{settings.port}"
    webhook_url = f"{base_url}/api/webhook/{tenant.platform.value}/{tenant_id}"

    if tenant.platform == Platform.FRESHCHAT:
        instructions = (
            "Freshchat 웹훅 설정:\n"
            "1. Freshchat Admin > Settings > Webhooks 이동\n"
            "2. 'Add Webhook' 클릭\n"
            f"3. Webhook URL: {webhook_url}\n"
            "4. Events: 'Message Create', 'Conversation Resolve' 선택\n"
            "5. 'Save' 클릭"
        )
    elif tenant.platform == Platform.ZENDESK:
        instructions = (
            "Zendesk 웹훅 설정:\n"
            "1. Zendesk Admin Center > Apps and integrations > Webhooks 이동\n"
            "2. 'Create webhook' 클릭\n"
            f"3. Endpoint URL: {webhook_url}\n"
            "4. Request method: POST\n"
            "5. Request format: JSON\n"
            "6. Trigger: 티켓 업데이트 시"
        )
    else:
        instructions = "Unknown platform"

    return WebhookInfo(
        platform=tenant.platform.value,
        webhook_url=webhook_url,
        instructions=instructions,
    )


@router.get("/validate")
async def validate_connection(
    tenant_id: str = Depends(get_tenant_id_from_header),
) -> dict:
    """플랫폼 연결 검증

    API 키가 유효한지 확인
    """
    service = get_tenant_service()
    tenant = await service.get_tenant(tenant_id)

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not configured")

    from app.core.platform_factory import get_platform_factory
    factory = get_platform_factory()
    client = factory.get_client(tenant)

    if not client:
        return {
            "valid": False,
            "error": "Failed to create client",
        }

    # TODO: 실제 API 호출로 검증
    # 예: Freshchat의 경우 /agents 조회, Zendesk의 경우 /users/me 조회

    return {
        "valid": True,
        "platform": tenant.platform.value,
        "message": "Connection validated successfully",
    }
