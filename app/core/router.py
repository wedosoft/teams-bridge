"""메시지 라우터 (Orchestrator)

Express poc-bridge.js의 handleTeamsMessage, handleFreshchatWebhook 포팅
주요 기능:
- Teams → Freshchat 메시지/파일 중계
- Freshchat → Teams 메시지/파일 중계
- 대화 생성 및 매핑 관리
- Greeting 메시지 처리
- 첨부파일 양방향 전송
"""
from typing import Any, Optional
import asyncio

from botbuilder.core import TurnContext
from botbuilder.schema import Attachment as BotAttachment

from app.adapters.freshchat.client import FreshchatClient
from app.adapters.freshchat.webhook import ParsedMessage, ParsedAttachment, WebhookEvent
from app.config import get_settings
from app.core.store import (
    ConversationStore,
    ConversationMapping,
    get_conversation_store,
)
from app.teams.bot import (
    TeamsBot,
    TeamsMessage,
    TeamsAttachment,
    get_teams_bot,
    build_file_card,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MessageRouter:
    """메시지 라우터 - Teams와 헬프데스크 플랫폼 간 메시지 중계

    Express poc-bridge.js의 handleTeamsMessage, handleFreshchatWebhook 기능 통합
    """

    def __init__(self):
        self._settings = get_settings()
        self._store: Optional[ConversationStore] = None
        self._freshchat: Optional[FreshchatClient] = None
        self._bot: Optional[TeamsBot] = None

    @property
    def store(self) -> ConversationStore:
        """대화 매핑 스토어 (지연 초기화)"""
        if self._store is None:
            self._store = get_conversation_store()
        return self._store

    @property
    def freshchat(self) -> FreshchatClient:
        """Freshchat 클라이언트 (지연 초기화)"""
        if self._freshchat is None:
            self._freshchat = FreshchatClient(
                api_key=self._settings.freshchat_api_key,
                api_url=self._settings.freshchat_api_url,
                inbox_id=self._settings.freshchat_inbox_id,
            )
        return self._freshchat

    @property
    def bot(self) -> TeamsBot:
        """Teams Bot (지연 초기화)"""
        if self._bot is None:
            self._bot = get_teams_bot()
        return self._bot

    # ===== Teams → Freshchat =====

    async def handle_teams_message(
        self,
        context: TurnContext,
        message: TeamsMessage,
    ) -> None:
        """
        Teams에서 받은 메시지 처리

        Express poc-bridge.js의 handleTeamsMessage 포팅

        Flow:
        1. 기존 대화 매핑 조회 (Teams ID → Freshchat ID)
        2. 없으면: Freshchat 사용자 생성 → 대화 생성 → 매핑 저장
        3. 있으면: 기존 대화에 메시지/첨부파일 전송
        4. 대화가 종료된 경우: 새 대화 자동 생성

        Args:
            context: TurnContext
            message: TeamsMessage (파싱된 메시지)
        """
        teams_conversation_id = message.conversation_id
        teams_user_id = message.user.id if message.user else ""
        conversation_reference = message.conversation_reference or {}

        logger.info(
            "Processing Teams message",
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
            has_text=bool(message.text),
            attachment_count=len(message.attachments),
        )

        try:
            # 1. 기존 대화 매핑 확인
            mapping = await self.store.get_by_teams_id(teams_conversation_id, "freshchat")

            # 2. 매핑이 없거나 종료된 경우 → 새 대화 생성
            if not mapping or mapping.is_resolved:
                mapping = await self._create_new_conversation(
                    context=context,
                    message=message,
                    conversation_reference=conversation_reference,
                )
                if not mapping:
                    await context.send_activity(
                        "죄송합니다. 상담 연결에 실패했습니다. 잠시 후 다시 시도해 주세요."
                    )
                    return

                # Greeting 메시지 (새 대화 시에만)
                if not mapping.greeting_sent:
                    await context.send_activity(
                        "안녕하세요! IT 헬프데스크입니다. 상담원이 곧 연결됩니다. 🙂"
                    )
                    mapping.greeting_sent = True
                    await self.store.upsert(mapping)

            else:
                # 3. 기존 대화에 메시지 전송 시도
                success = await self._send_to_freshchat(
                    context=context,
                    message=message,
                    mapping=mapping,
                )

                if not success:
                    # 대화가 종료되었거나 전송 실패 → 새 대화 생성
                    logger.info("Message send failed, creating new conversation")
                    await self.store.mark_resolved(
                        mapping.platform_conversation_id or "",
                        "freshchat",
                        True,
                    )

                    mapping = await self._create_new_conversation(
                        context=context,
                        message=message,
                        conversation_reference=conversation_reference,
                    )

                    if not mapping:
                        await context.send_activity(
                            "죄송합니다. 상담 연결에 실패했습니다."
                        )
                        return

                    await context.send_activity(
                        "이전 상담이 종료되어 새로운 상담이 시작되었습니다. 🙂"
                    )

            # ConversationReference 업데이트 (항상)
            if conversation_reference:
                await self.store.update_conversation_reference(
                    teams_conversation_id,
                    "freshchat",
                    conversation_reference,
                )

        except Exception as e:
            logger.error(
                "Failed to process Teams message",
                error=str(e),
                teams_conversation_id=teams_conversation_id,
            )
            await context.send_activity(
                "죄송합니다. 메시지 처리 중 오류가 발생했습니다."
            )

    async def _create_new_conversation(
        self,
        context: TurnContext,
        message: TeamsMessage,
        conversation_reference: dict,
    ) -> Optional[ConversationMapping]:
        """
        새 Freshchat 대화 생성

        1. Freshchat 사용자 생성/조회
        2. 대화 생성 (초기 메시지 포함)
        3. 매핑 저장
        """
        user = message.user
        if not user:
            logger.error("No user info in message")
            return None

        # 사용자 프로필 구성
        properties = {}
        if user.tenant_id:
            properties["tenant_id"] = user.tenant_id

        # 1. Freshchat 사용자 생성/조회
        freshchat_user_id = await self.freshchat.get_or_create_user(
            reference_id=user.id,
            name=user.name,
            email=user.email,
            properties=properties if properties else None,
        )

        if not freshchat_user_id:
            logger.error("Failed to create Freshchat user")
            return None

        # Teams 대화 ID를 사용자 프로필에 저장 (복구용)
        await self.freshchat.update_user_teams_conversation(
            user_id=freshchat_user_id,
            teams_conversation_id=message.conversation_id,
        )

        # 2. 첫 번째 메시지 구성
        message_text = message.text
        attachments = []

        # 첨부파일 처리
        if message.attachments:
            for att in message.attachments:
                downloaded = await self.bot.download_attachment(context, att)
                if downloaded:
                    file_buffer, content_type, filename = downloaded
                    uploaded = await self.freshchat.upload_file(
                        file_buffer=file_buffer,
                        filename=filename,
                        content_type=content_type,
                    )
                    if uploaded:
                        attachments.append(uploaded)

        # 3. 대화 생성 (초기 메시지 포함)
        result = await self.freshchat.create_conversation(
            user_id=freshchat_user_id,
            message_text=message_text,
            attachments=attachments if attachments else None,
        )

        if not result:
            logger.error("Failed to create Freshchat conversation")
            return None

        conversation_id = result.get("conversation_id", "")
        numeric_id = str(result.get("id", "")) if result.get("id") else None

        logger.info(
            "Created new Freshchat conversation",
            conversation_id=conversation_id,
            numeric_id=numeric_id,
            freshchat_user_id=freshchat_user_id,
        )

        # 4. 매핑 저장
        mapping = ConversationMapping(
            teams_conversation_id=message.conversation_id,
            teams_user_id=user.id,
            conversation_reference=conversation_reference,
            platform="freshchat",
            platform_conversation_id=conversation_id,
            platform_conversation_numeric_id=numeric_id,
            platform_user_id=freshchat_user_id,
            is_resolved=False,
            greeting_sent=False,
            tenant_id=user.tenant_id,
        )

        saved = await self.store.upsert(mapping)
        return saved

    async def _send_to_freshchat(
        self,
        context: TurnContext,
        message: TeamsMessage,
        mapping: ConversationMapping,
    ) -> bool:
        """
        기존 Freshchat 대화에 메시지/첨부파일 전송

        Returns:
            성공 여부
        """
        conversation_ids = []
        if mapping.platform_conversation_id:
            conversation_ids.append(mapping.platform_conversation_id)
        if mapping.platform_conversation_numeric_id:
            conversation_ids.append(mapping.platform_conversation_numeric_id)

        if not conversation_ids:
            return False

        user_id = mapping.platform_user_id
        if not user_id:
            return False

        # 메시지 텍스트
        message_text = message.text

        # 첨부파일 처리
        attachments = []
        if message.attachments:
            for att in message.attachments:
                downloaded = await self.bot.download_attachment(context, att)
                if downloaded:
                    file_buffer, content_type, filename = downloaded
                    uploaded = await self.freshchat.upload_file(
                        file_buffer=file_buffer,
                        filename=filename,
                        content_type=content_type,
                    )
                    if uploaded:
                        attachments.append(uploaded)

        # 사용자 이름
        user_name = message.user.name if message.user else None

        # 메시지 전송 (fallback 포함)
        result = await self.freshchat.send_message_with_fallback(
            conversation_ids=conversation_ids,
            user_id=user_id,
            message_text=message_text,
            attachments=attachments if attachments else None,
            user_name=user_name,
        )

        return result.get("success", False)

    # ===== Freshchat → Teams =====

    async def handle_freshchat_webhook(
        self,
        event: WebhookEvent,
    ) -> None:
        """
        Freshchat 웹훅 이벤트 처리

        Express poc-bridge.js의 handleFreshchatWebhook 포팅

        Flow:
        1. 대화 매핑 조회 (Freshchat ID → Teams ID)
        2. conversation_resolution: 종료 메시지 전송 + 매핑 업데이트
        3. message_create: Teams로 메시지/첨부파일 전송

        Args:
            event: WebhookEvent (파싱된 웹훅 이벤트)
        """
        # 대화 ID 확인
        conversation_id = event.conversation_id or event.conversation_numeric_id
        if not conversation_id:
            logger.warning("No conversation ID in webhook event")
            return

        logger.info(
            "Processing Freshchat webhook",
            action=event.action,
            conversation_id=conversation_id,
        )

        try:
            # 1. 대화 매핑 조회
            mapping = await self._find_mapping(event)
            if not mapping:
                logger.warning(
                    "No conversation mapping found",
                    conversation_id=conversation_id,
                )
                return

            # 2. 대화 종료 이벤트
            if event.action == "conversation_resolution":
                await self._handle_resolution(mapping)
                return

            # 3. 메시지 이벤트
            if event.action == "message_create" and event.message:
                await self._send_to_teams(event, mapping)

        except Exception as e:
            logger.error(
                "Failed to process Freshchat webhook",
                error=str(e),
                conversation_id=conversation_id,
            )

    async def _find_mapping(self, event: WebhookEvent) -> Optional[ConversationMapping]:
        """대화 매핑 조회 (여러 ID 시도)"""
        # GUID로 조회
        if event.conversation_id:
            mapping = await self.store.get_by_platform_id(
                event.conversation_id, "freshchat"
            )
            if mapping:
                return mapping

        # Numeric ID로 조회
        if event.conversation_numeric_id:
            mapping = await self.store.get_by_platform_id(
                event.conversation_numeric_id, "freshchat"
            )
            if mapping:
                return mapping

        return None

    async def _handle_resolution(self, mapping: ConversationMapping) -> None:
        """대화 종료 처리"""
        # 매핑 업데이트
        await self.store.mark_resolved(
            mapping.platform_conversation_id or "",
            "freshchat",
            True,
        )

        # Teams에 종료 메시지 전송
        if mapping.conversation_reference:
            await self.bot.send_proactive_message(
                conversation_reference=mapping.conversation_reference,
                text="✅ 상담이 종료되었습니다. 새로운 문의가 있으시면 메시지를 보내주세요.",
            )

        logger.info(
            "Conversation resolved",
            teams_conversation_id=mapping.teams_conversation_id,
            platform_conversation_id=mapping.platform_conversation_id,
        )

    async def _send_to_teams(
        self,
        event: WebhookEvent,
        mapping: ConversationMapping,
    ) -> None:
        """Freshchat 메시지를 Teams로 전송"""
        if not mapping.conversation_reference:
            logger.error("No conversation reference for Teams")
            return

        message = event.message
        if not message:
            return

        # 상담원 이름 조회
        agent_name = None
        if message.actor_type == "agent" and message.actor_id:
            agent_name = await self.freshchat.get_agent_name(message.actor_id)

        # 텍스트 메시지
        if message.text:
            await self.bot.send_proactive_message(
                conversation_reference=mapping.conversation_reference,
                text=message.text,
                sender_name=agent_name,
            )

        # 첨부파일
        if message.attachments:
            await self._send_attachments_to_teams(
                message.attachments,
                mapping,
                agent_name,
            )

        logger.info(
            "Sent message to Teams",
            teams_conversation_id=mapping.teams_conversation_id,
            actor_type=message.actor_type,
            has_text=bool(message.text),
            attachment_count=len(message.attachments),
        )

    async def _send_attachments_to_teams(
        self,
        attachments: list[ParsedAttachment],
        mapping: ConversationMapping,
        agent_name: Optional[str] = None,
    ) -> None:
        """Freshchat 첨부파일을 Teams로 전송"""
        for att in attachments:
            # URL이 없으면 스킵
            if not att.url:
                logger.warning("Attachment has no URL", name=att.name)
                continue

            # 이미지: 마크다운으로 전송
            if att.type == "image":
                image_text = f"![{att.name or 'image'}]({att.url})"
                await self.bot.send_proactive_message(
                    conversation_reference=mapping.conversation_reference,
                    text=image_text,
                    sender_name=agent_name,
                )

            # 파일/비디오: Adaptive Card로 전송
            else:
                card = build_file_card(
                    filename=att.name or "file",
                    file_url=att.url,
                    content_type=att.content_type,
                )
                await self.bot.send_proactive_card(
                    conversation_reference=mapping.conversation_reference,
                    card=card,
                    sender_name=agent_name,
                )


# ===== 싱글톤 인스턴스 =====

_router_instance: Optional[MessageRouter] = None


def get_message_router() -> MessageRouter:
    """MessageRouter 싱글톤 인스턴스 반환"""
    global _router_instance
    if _router_instance is None:
        _router_instance = MessageRouter()
    return _router_instance
