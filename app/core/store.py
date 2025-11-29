"""대화 매핑 스토어

Express poc-bridge.js의 ConversationStore 클래스를 Python으로 포팅
Supabase (영속) + 인메모리 캐시 (성능) 하이브리드 구조

주요 기능:
- Teams 대화 ID ↔ Freshchat 대화 ID 양방향 매핑
- ConversationReference 저장 (proactive 메시지용)
- 사용자별 최신 대화 추적
- 인메모리 캐시로 조회 성능 최적화
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Optional
import json
import time

from app.database import Database
from app.utils.logger import get_logger

logger = get_logger(__name__)


# 캐시 TTL (30분)
CACHE_TTL_SECONDS = 1800
# 캐시 최대 크기
MAX_CACHE_SIZE = 1000


@dataclass
class ConversationMapping:
    """대화 매핑 데이터"""
    # Teams 정보
    teams_conversation_id: str
    teams_user_id: str
    conversation_reference: dict = field(default_factory=dict)

    # 플랫폼 정보
    platform: str = "freshchat"
    platform_conversation_id: Optional[str] = None  # GUID
    platform_conversation_numeric_id: Optional[str] = None  # Numeric ID
    platform_user_id: Optional[str] = None

    # 상태
    is_resolved: bool = False
    greeting_sent: bool = False

    # 메타데이터
    tenant_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # DB ID (Supabase에서 생성)
    id: Optional[str] = None

    def to_dict(self) -> dict:
        """Supabase 저장용 dict 변환"""
        return {
            "teams_conversation_id": self.teams_conversation_id,
            "teams_user_id": self.teams_user_id,
            "conversation_reference": self.conversation_reference,
            "platform": self.platform,
            "platform_conversation_id": self.platform_conversation_id or self.platform_conversation_numeric_id,
            "platform_user_id": self.platform_user_id,
            "is_resolved": self.is_resolved,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationMapping":
        """Supabase 데이터에서 생성"""
        return cls(
            id=data.get("id"),
            teams_conversation_id=data.get("teams_conversation_id", ""),
            teams_user_id=data.get("teams_user_id", ""),
            conversation_reference=data.get("conversation_reference", {}),
            platform=data.get("platform", "freshchat"),
            platform_conversation_id=data.get("platform_conversation_id"),
            platform_user_id=data.get("platform_user_id"),
            is_resolved=data.get("is_resolved", False),
            tenant_id=data.get("tenant_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class CacheEntry:
    """캐시 엔트리"""
    mapping: ConversationMapping
    cached_at: float  # time.time()


class ConversationStore:
    """대화 매핑 스토어 (Supabase + 인메모리 캐시)"""

    def __init__(self):
        self._db = Database()

        # 인메모리 캐시
        self._cache_by_teams: dict[str, CacheEntry] = {}  # teams_conv_id -> entry
        self._cache_by_platform: dict[str, str] = {}  # platform_conv_id -> teams_conv_id
        self._cache_by_user: dict[str, str] = {}  # teams_user_id -> teams_conv_id (최신)

    # ===== 조회 =====

    async def get_by_teams_id(
        self,
        teams_conversation_id: str,
        platform: str = "freshchat",
    ) -> Optional[ConversationMapping]:
        """
        Teams 대화 ID로 매핑 조회

        Args:
            teams_conversation_id: Teams 대화 ID
            platform: 플랫폼 (freshchat, zendesk 등)

        Returns:
            ConversationMapping 또는 None
        """
        cache_key = f"{teams_conversation_id}:{platform}"

        # 1. 캐시 확인
        entry = self._cache_by_teams.get(cache_key)
        if entry and not self._is_cache_expired(entry):
            logger.debug("Cache hit (teams)", teams_conversation_id=teams_conversation_id)
            return entry.mapping

        # 2. DB 조회
        try:
            data = await self._db.get_conversation_by_teams_id(teams_conversation_id, platform)
            if data:
                mapping = ConversationMapping.from_dict(data)
                self._update_cache(mapping)
                return mapping
        except Exception as e:
            logger.error("Failed to get mapping by teams id", error=str(e))

        return None

    async def get_by_platform_id(
        self,
        platform_conversation_id: str,
        platform: str = "freshchat",
    ) -> Optional[ConversationMapping]:
        """
        플랫폼 대화 ID로 매핑 조회

        Args:
            platform_conversation_id: Freshchat/Zendesk 대화 ID
            platform: 플랫폼

        Returns:
            ConversationMapping 또는 None
        """
        # 1. 역방향 캐시 확인
        teams_conv_id = self._cache_by_platform.get(platform_conversation_id)
        if teams_conv_id:
            cache_key = f"{teams_conv_id}:{platform}"
            entry = self._cache_by_teams.get(cache_key)
            if entry and not self._is_cache_expired(entry):
                logger.debug("Cache hit (platform)", platform_conversation_id=platform_conversation_id)
                return entry.mapping

        # 2. DB 조회
        try:
            data = await self._db.get_conversation_by_platform_id(platform_conversation_id, platform)
            if data:
                mapping = ConversationMapping.from_dict(data)
                self._update_cache(mapping)
                return mapping
        except Exception as e:
            logger.error("Failed to get mapping by platform id", error=str(e))

        return None

    async def get_by_user_id(
        self,
        teams_user_id: str,
        platform: str = "freshchat",
    ) -> Optional[ConversationMapping]:
        """
        사용자 ID로 최신 매핑 조회 (fallback용)

        Teams 대화 ID가 변경되는 경우 사용자 ID로 복구

        Args:
            teams_user_id: Teams 사용자 ID
            platform: 플랫폼

        Returns:
            ConversationMapping 또는 None
        """
        # 1. 캐시 확인
        teams_conv_id = self._cache_by_user.get(teams_user_id)
        if teams_conv_id:
            return await self.get_by_teams_id(teams_conv_id, platform)

        # 2. DB 조회 (최신 대화)
        try:
            result = (
                self._db.client.table("conversations")
                .select("*")
                .eq("teams_user_id", teams_user_id)
                .eq("platform", platform)
                .eq("is_resolved", False)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )

            if result.data:
                mapping = ConversationMapping.from_dict(result.data[0])
                self._update_cache(mapping)
                return mapping
        except Exception as e:
            logger.error("Failed to get mapping by user id", error=str(e))

        return None

    # ===== 저장/업데이트 =====

    async def upsert(self, mapping: ConversationMapping) -> Optional[ConversationMapping]:
        """
        매핑 생성 또는 업데이트

        Args:
            mapping: ConversationMapping

        Returns:
            업데이트된 ConversationMapping 또는 None
        """
        try:
            data = mapping.to_dict()
            result = await self._db.upsert_conversation(data)

            if result:
                updated = ConversationMapping.from_dict(result)
                self._update_cache(updated)

                logger.info(
                    "Upserted conversation mapping",
                    teams_conversation_id=mapping.teams_conversation_id,
                    platform_conversation_id=mapping.platform_conversation_id,
                )
                return updated

        except Exception as e:
            logger.error("Failed to upsert mapping", error=str(e))

        return None

    async def update_platform_ids(
        self,
        teams_conversation_id: str,
        platform: str,
        platform_conversation_id: Optional[str] = None,
        platform_conversation_numeric_id: Optional[str] = None,
        platform_user_id: Optional[str] = None,
    ) -> bool:
        """
        플랫폼 ID 업데이트

        Args:
            teams_conversation_id: Teams 대화 ID
            platform: 플랫폼
            platform_conversation_id: 플랫폼 대화 ID (GUID)
            platform_conversation_numeric_id: 플랫폼 대화 ID (Numeric)
            platform_user_id: 플랫폼 사용자 ID

        Returns:
            성공 여부
        """
        mapping = await self.get_by_teams_id(teams_conversation_id, platform)
        if not mapping:
            logger.warning("Mapping not found for update", teams_conversation_id=teams_conversation_id)
            return False

        if platform_conversation_id:
            mapping.platform_conversation_id = platform_conversation_id
        if platform_conversation_numeric_id:
            mapping.platform_conversation_numeric_id = platform_conversation_numeric_id
        if platform_user_id:
            mapping.platform_user_id = platform_user_id

        result = await self.upsert(mapping)
        return result is not None

    async def mark_resolved(
        self,
        platform_conversation_id: str,
        platform: str = "freshchat",
        is_resolved: bool = True,
    ) -> bool:
        """
        대화 해결 상태 업데이트

        Args:
            platform_conversation_id: 플랫폼 대화 ID
            platform: 플랫폼
            is_resolved: 해결 여부

        Returns:
            성공 여부
        """
        try:
            await self._db.update_conversation_resolved(
                platform_conversation_id, platform, is_resolved
            )

            # 캐시 업데이트
            mapping = await self.get_by_platform_id(platform_conversation_id, platform)
            if mapping:
                mapping.is_resolved = is_resolved
                self._update_cache(mapping)

            logger.info(
                "Marked conversation resolved",
                platform_conversation_id=platform_conversation_id,
                is_resolved=is_resolved,
            )
            return True

        except Exception as e:
            logger.error("Failed to mark resolved", error=str(e))
            return False

    async def update_conversation_reference(
        self,
        teams_conversation_id: str,
        platform: str,
        conversation_reference: dict,
    ) -> bool:
        """
        ConversationReference 업데이트

        Args:
            teams_conversation_id: Teams 대화 ID
            platform: 플랫폼
            conversation_reference: 새 ConversationReference

        Returns:
            성공 여부
        """
        mapping = await self.get_by_teams_id(teams_conversation_id, platform)
        if not mapping:
            return False

        mapping.conversation_reference = conversation_reference
        result = await self.upsert(mapping)
        return result is not None

    # ===== 캐시 관리 =====

    def _update_cache(self, mapping: ConversationMapping) -> None:
        """캐시 업데이트"""
        # 캐시 크기 제한
        if len(self._cache_by_teams) >= MAX_CACHE_SIZE:
            self._cleanup_cache()

        cache_key = f"{mapping.teams_conversation_id}:{mapping.platform}"

        # 정방향 캐시
        self._cache_by_teams[cache_key] = CacheEntry(
            mapping=mapping,
            cached_at=time.time(),
        )

        # 역방향 캐시 (플랫폼 ID → Teams ID)
        if mapping.platform_conversation_id:
            self._cache_by_platform[mapping.platform_conversation_id] = mapping.teams_conversation_id
        if mapping.platform_conversation_numeric_id:
            self._cache_by_platform[mapping.platform_conversation_numeric_id] = mapping.teams_conversation_id

        # 사용자별 최신 대화
        if not mapping.is_resolved:
            self._cache_by_user[mapping.teams_user_id] = mapping.teams_conversation_id

    def _is_cache_expired(self, entry: CacheEntry) -> bool:
        """캐시 만료 확인"""
        return time.time() - entry.cached_at > CACHE_TTL_SECONDS

    def _cleanup_cache(self) -> None:
        """만료된 캐시 정리"""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache_by_teams.items()
            if current_time - entry.cached_at > CACHE_TTL_SECONDS
        ]

        for key in expired_keys[:len(expired_keys) // 2]:  # 절반만 정리
            entry = self._cache_by_teams.pop(key, None)
            if entry:
                mapping = entry.mapping
                if mapping.platform_conversation_id:
                    self._cache_by_platform.pop(mapping.platform_conversation_id, None)
                if mapping.platform_conversation_numeric_id:
                    self._cache_by_platform.pop(mapping.platform_conversation_numeric_id, None)

        logger.debug("Cache cleanup", removed=len(expired_keys) // 2, remaining=len(self._cache_by_teams))

    def invalidate_cache(self, teams_conversation_id: str, platform: str = "freshchat") -> None:
        """특정 매핑 캐시 무효화"""
        cache_key = f"{teams_conversation_id}:{platform}"
        entry = self._cache_by_teams.pop(cache_key, None)

        if entry:
            mapping = entry.mapping
            if mapping.platform_conversation_id:
                self._cache_by_platform.pop(mapping.platform_conversation_id, None)
            if mapping.platform_conversation_numeric_id:
                self._cache_by_platform.pop(mapping.platform_conversation_numeric_id, None)

    # ===== 유틸리티 =====

    def get_cache_stats(self) -> dict:
        """캐시 통계"""
        return {
            "teams_cache_size": len(self._cache_by_teams),
            "platform_cache_size": len(self._cache_by_platform),
            "user_cache_size": len(self._cache_by_user),
        }

    async def get_active_conversations_count(self, platform: str = "freshchat") -> int:
        """활성 대화 수 조회"""
        try:
            result = (
                self._db.client.table("conversations")
                .select("id", count="exact")
                .eq("platform", platform)
                .eq("is_resolved", False)
                .execute()
            )
            return result.count or 0
        except Exception as e:
            logger.error("Failed to get active conversations count", error=str(e))
            return 0


# ===== 싱글톤 인스턴스 =====

_store_instance: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    """ConversationStore 싱글톤 인스턴스 반환"""
    global _store_instance
    if _store_instance is None:
        _store_instance = ConversationStore()
    return _store_instance
