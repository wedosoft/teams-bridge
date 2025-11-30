# Teams Helpdesk Bridge - 작업 현황 핸드오버

## 프로젝트 개요

Microsoft Teams와 헬프데스크 플랫폼(Freshchat/Zendesk) 간 양방향 메시지 브릿지 서비스.

- **배포 URL**: https://teams-helpdesk-bridge.fly.dev
- **플랫폼**: Fly.io (512MB RAM)
- **데이터베이스**: Supabase (PostgreSQL + Storage)

---

## 최근 완료된 작업 (2024-11-30)

### 1. 첨부파일 통합 전송

**문제**: 텍스트와 첨부파일이 별도 메시지로 전송되어 대화 흐름이 끊김

**해결**: `_send_combined_message_to_teams` 메서드 구현
- 텍스트 + 이미지 + 비디오/파일을 하나의 메시지로 통합
- 이미지: Adaptive Card로 인라인 표시
- 비디오: 🎬 마크다운 링크
- 파일: 📎 마크다운 링크

**파일**: [app/core/router.py](../app/core/router.py) - `_send_combined_message_to_teams()`

---

### 2. 첨부파일 병렬 업로드 최적화

**문제**: 순차적 API 호출로 메시지 전송 지연

**해결**: `asyncio.gather()` 활용한 병렬 처리
- Teams → Freshchat 이미지 전송 시 Supabase + Freshchat 동시 업로드
- 여러 첨부파일도 병렬 처리

**파일**: [app/core/router.py](../app/core/router.py)
- `_process_attachment_parallel()` - 단일 첨부파일 병렬 처리
- `_process_attachments_parallel()` - 다중 첨부파일 병렬 처리

---

### 3. 이미지 표시 개선 (HeroCard → Adaptive Card)

**문제**: HeroCard 사용 시 이미지가 카드 너비에 맞춰 늘어남 (비율 깨짐)

**해결**: Adaptive Card + Image 요소 사용
```json
{
  "type": "Image",
  "url": "...",
  "size": "Medium",
  "selectAction": {
    "type": "Action.OpenUrl",
    "url": "원본 이미지 URL"
  }
}
```
- `size: "Medium"`: 적절한 크기로 제한 (비율 유지)
- `selectAction`: 클릭 시 원본 이미지 열기

**파일**: [app/core/router.py](../app/core/router.py)
- `_send_combined_message_to_teams()`
- `_send_attachments_to_teams()`

---

### 4. 한글 파일명 업로드 오류 수정

**문제**: Supabase Storage가 비-ASCII 파일명 거부

**해결**: UUID 기반 파일명으로 대체
```python
file_path = f"{uuid.uuid4().hex[:12]}{ext}"
```

**파일**: [app/database.py](../app/database.py) - `upload_to_storage()`

---

### 5. 클립보드/스크린샷 이미지 처리

**문제**: Teams에서 붙여넣기한 이미지가 Freshchat에 전송 안됨

**해결**: `text/html` 첨부파일에서 `<img src>` URL 추출
```python
img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content)
```

**파일**: [app/teams/bot.py](../app/teams/bot.py) - `_parse_attachments()`

---

## 아키텍처 요약

```
Teams User
    ↓
TeamsBot (app/teams/bot.py)
    ↓
MessageRouter (app/core/router.py)
    ↓
PlatformFactory (app/core/platform_factory.py)
    ↓
FreshchatClient / ZendeskClient (app/adapters/)
```

### 주요 캐싱

| 항목 | TTL | 위치 |
|------|-----|------|
| Platform Client | 10분 | `PlatformFactory._cache` |
| Agent 정보 | 30분 | `FreshchatClient._agent_cache` |
| Supabase Client | 영구 | `@lru_cache` |

---

## 주요 파일 설명

| 파일 | 설명 |
|------|------|
| `app/core/router.py` | 메시지 라우팅 핵심 로직 |
| `app/teams/bot.py` | Teams Bot Framework 핸들러 |
| `app/adapters/freshchat/client.py` | Freshchat API 클라이언트 |
| `app/adapters/freshchat/webhook.py` | Freshchat 웹훅 파서 |
| `app/database.py` | Supabase DB/Storage 클라이언트 |
| `app/core/platform_factory.py` | 플랫폼 클라이언트 팩토리 |
| `app/core/tenant.py` | 멀티테넌트 설정 관리 |

---

## 배포

```bash
# Fly.io 배포
fly deploy

# 로그 확인
fly logs -a teams-helpdesk-bridge
```

---

## 알려진 제한사항

1. **메모리**: 512MB - 대용량 파일 처리 시 주의
2. **Freshchat 파일 업로드**: 이미지는 `image` 타입, 기타는 `file` 타입 사용 필요
3. **Teams Adaptive Card**: 버전 1.4 사용 중

---

## 향후 개선 가능 항목

- [ ] Zendesk 어댑터 완성 (현재 Freshchat만 테스트됨)
- [ ] 대화 종료 시 Teams 알림
- [ ] 에러 재시도 로직 강화
- [ ] 모니터링/알림 시스템 추가
