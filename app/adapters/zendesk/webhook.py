"""Zendesk Webhook 처리

Zendesk 웹훅 이벤트 파싱:
- 티켓 코멘트 생성
- 티켓 상태 변경 (해결)

API 문서: https://developer.zendesk.com/api-reference/webhooks/webhooks/
"""
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# 중복 메시지 TTL (10분)
DEDUP_TTL_SECONDS = 600
MAX_PROCESSED_MESSAGES = 2000


@dataclass
class ZendeskAttachment:
    """Zendesk 첨부파일"""
    type: str  # "image", "file"
    url: Optional[str] = None
    name: Optional[str] = None
    content_type: Optional[str] = None


@dataclass
class ZendeskMessage:
    """Zendesk 메시지"""
    id: str
    text: Optional[str] = None
    attachments: list[ZendeskAttachment] = field(default_factory=list)
    actor_type: str = "agent"  # "agent", "user", "system"
    actor_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class ZendeskWebhookEvent:
    """Zendesk 웹훅 이벤트"""
    action: str  # "ticket_comment_created", "ticket_solved", etc.
    ticket_id: Optional[str] = None
    message: Optional[ZendeskMessage] = None
    raw_data: dict = field(default_factory=dict)


class ZendeskWebhookHandler:
    """Zendesk Webhook 핸들러"""

    def __init__(self, webhook_secret: str = ""):
        """
        Args:
            webhook_secret: 웹훅 서명 검증 시크릿
        """
        self.webhook_secret = webhook_secret
        self._processed_messages: dict[str, float] = {}

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Webhook 서명 검증 (HMAC-SHA256)

        Args:
            payload: 요청 본문
            signature: X-Zendesk-Webhook-Signature 헤더

        Returns:
            검증 성공 여부
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured")
            return True  # 시크릿 없으면 검증 스킵

        if not signature:
            logger.warning("Missing webhook signature")
            return False

        try:
            expected = hmac.new(
                self.webhook_secret.encode(),
                payload,
                hashlib.sha256,
            ).hexdigest()

            # 타이밍 공격 방지
            return hmac.compare_digest(expected, signature)

        except Exception as e:
            logger.error("Signature verification error", error=str(e))
            return False

    def is_duplicate_message(self, message_id: str) -> bool:
        """메시지 중복 체크"""
        if not message_id:
            return False

        current_time = time.time()

        # 만료된 항목 정리
        if len(self._processed_messages) > MAX_PROCESSED_MESSAGES:
            expired = [
                mid for mid, ts in self._processed_messages.items()
                if current_time - ts > DEDUP_TTL_SECONDS
            ]
            for mid in expired:
                del self._processed_messages[mid]

        # 중복 체크
        if message_id in self._processed_messages:
            return True

        self._processed_messages[message_id] = current_time
        return False

    def parse_webhook(self, payload: dict) -> Optional[ZendeskWebhookEvent]:
        """
        Webhook 페이로드 파싱

        Args:
            payload: Webhook JSON 페이로드

        Returns:
            ZendeskWebhookEvent 또는 None
        """
        try:
            # Zendesk 웹훅 트리거 형식에 따라 다름
            # 일반적으로 ticket 정보가 포함됨

            ticket = payload.get("ticket", {})
            if not ticket:
                # 다른 형식 시도
                ticket = payload.get("data", {}).get("ticket", {})

            if not ticket:
                logger.debug("No ticket in webhook payload")
                return None

            ticket_id = str(ticket.get("id", ""))
            status = ticket.get("status", "")

            # 티켓 해결 이벤트
            if status in ["solved", "closed"]:
                return ZendeskWebhookEvent(
                    action="ticket_solved",
                    ticket_id=ticket_id,
                    message=ZendeskMessage(
                        id="resolution",
                        text="[대화가 종료되었습니다]",
                        actor_type="system",
                    ),
                    raw_data=payload,
                )

            # 최신 코멘트 확인
            comments = ticket.get("comments", [])
            if not comments:
                # via 객체에서 확인
                via = ticket.get("via", {})
                comment = payload.get("comment", {})
                if comment:
                    comments = [comment]

            if not comments:
                return None

            # 마지막 코멘트
            latest_comment = comments[-1] if isinstance(comments, list) else comments

            comment_id = str(latest_comment.get("id", ""))
            if self.is_duplicate_message(comment_id):
                return None

            # 작성자 확인 (에이전트만 처리)
            author_id = str(latest_comment.get("author_id", ""))
            is_public = latest_comment.get("public", True)

            # 사용자의 코멘트는 에코 방지
            requester_id = str(ticket.get("requester_id", ""))
            if author_id == requester_id:
                logger.debug("Ignoring user comment (echo prevention)")
                return None

            # 메시지 파싱
            message = self._parse_comment(latest_comment)

            logger.info(
                "Parsed Zendesk webhook",
                ticket_id=ticket_id,
                comment_id=comment_id,
                actor_type=message.actor_type,
            )

            return ZendeskWebhookEvent(
                action="ticket_comment_created",
                ticket_id=ticket_id,
                message=message,
                raw_data=payload,
            )

        except Exception as e:
            logger.error("Failed to parse Zendesk webhook", error=str(e))
            return None

    def _parse_comment(self, comment: dict) -> ZendeskMessage:
        """코멘트 파싱"""
        attachments: list[ZendeskAttachment] = []

        # 첨부파일 파싱
        for att in comment.get("attachments", []):
            content_type = att.get("content_type", "")

            if content_type.startswith("image/"):
                att_type = "image"
            else:
                att_type = "file"

            attachments.append(ZendeskAttachment(
                type=att_type,
                url=att.get("content_url"),
                name=att.get("file_name"),
                content_type=content_type,
            ))

        return ZendeskMessage(
            id=str(comment.get("id", "")),
            text=comment.get("body") or comment.get("plain_body"),
            attachments=attachments,
            actor_type="agent",
            actor_id=str(comment.get("author_id", "")),
            created_at=comment.get("created_at"),
        )
