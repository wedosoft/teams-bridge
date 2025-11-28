# Teams-Helpdesk Bridge

## Agent Development Guide

**v1.1 | 2025-11-28**

> **📋 변경 이력 (v1.0 → v1.1)**
> 
> - ✅ Teams Bot conversation reference 만료 정책 수정 (24시간 만료 → Bot 설치 기간 동안 유효)
> - ✅ Freshdesk OAuth 지원 정보 수정 (OAuth → API Key 인증)
> - ✅ Salesforce MIAW → Enhanced Chat 명칭 업데이트
> - ✅ 개발 난이도 재평가 및 구현 가이드 보완
> - ✅ 기술 스택 및 에러 처리 전략 업데이트

---

> **Project Summary**
> 
> MS Teams 사용자와 헬프데스크 상담원 간 실시간 양방향 채팅 브릿지 솔루션
> 
> - 지원 플랫폼: Zendesk, Salesforce Service Cloud, Freshdesk
> - 배포 방식: Teams 마켓플레이스 단일 출시 + OAuth/API Key 연동

---

## 1. 프로젝트 개요

### 1.1 비즈니스 기회

기존 헬프데스크 마켓플레이스 앱들은 '상담사 생산성'에만 집중하고 있습니다. 엔드유저가 Teams에서 직접 상담원과 실시간 채팅하는 기능은 시장에 부재합니다.

#### 현재 시장 상황

| 구분 | 현황 |
|------|------|
| 기존 앱 초점 | 상담사가 Teams에서 티켓 조회/업데이트 |
| 엔드유저 채널 | 웹 위젯, 이메일, 소셜 미디어에 한정 |
| 시장 공백 | 내부 직원이 Teams에서 IT/HR 헬프데스크와 실시간 대화 불가 |

#### 타겟 고객

- 내부 IT 헬프데스크 운영 기업
- HR 문의 시스템 (입사/퇴사, 급여, 복리후생)
- B2E(Business-to-Employee) 고객지원팀

### 1.2 제품 개념

Teams 엔드유저 ↔ Bridge Server ↔ 헬프데스크 상담원 구조로, 양방향 실시간 메시징을 구현합니다.

---

## 2. 시스템 아키텍처

### 2.1 전체 구조

```
┌─────────────────────────────────────────────────────┐
│              Bridge Server (Multi-tenant)           │
│  ┌─────────────────────────────────────────────┐   │
│  │         Message Router / Orchestrator        │   │
│  └─────────────────────────────────────────────┘   │
│       ▲              ▲              ▲              │
│  ┌────┴────┐    ┌────┴────┐    ┌────┴────┐        │
│  │  Teams  │    │ Zendesk │    │Salesforce│        │
│  │ Adapter │    │ Adapter │    │ Adapter │        │
│  └────┬────┘    └────┬────┘    └────┬────┘        │
└───────┼──────────────┼──────────────┼─────────────┘
        │              │              │
        ▼              ▼              ▼
   Teams Bot      Sunshine       Enhanced Chat
   Framework    Conversations       API (BYOC)
        │              │              │
        ▼              ▼              ▼
   [Teams User]  [Zendesk Agent]  [SF Agent]
```

### 2.2 메시지 흐름

#### 엔드유저 → 상담원

1. Teams User가 Bot에 메시지 전송
2. Bridge Server가 메시지 수신 및 라우팅
3. 해당 플랫폼 Adapter가 API 호출
4. 상담원 콘솔에 메시지 표시

#### 상담원 → 엔드유저

1. 상담원이 헬프데스크에서 응답
2. 플랫폼 Webhook이 Bridge Server로 이벤트 전송
3. Bridge Server가 Teams Bot을 통해 Proactive Message 전송
4. Teams User가 메시지 수신

---

## 3. 플랫폼별 API 구조

### 3.1 Zendesk - Sunshine Conversations API

| 항목 | 내용 |
|------|------|
| API 방식 | REST API + Webhook |
| 인증 | Basic Auth (Key ID + Secret Key) 또는 OAuth 2.0 |
| SDK | sunshine-conversations-client (Node.js) |
| 개발 난이도 | ★★★☆☆ (Proactive messaging 복잡도 고려) |

#### 핵심 엔드포인트

- `POST /v2/apps/{appId}/conversations/{conversationId}/messages`
- Webhook 트리거: `conversation:message`

📚 문서: https://developer.zendesk.com/documentation/conversations/

### 3.2 Salesforce - Enhanced Chat API (구 MIAW)

| 항목 | 내용 |
|------|------|
| API 방식 | REST API + SSE (Server-Sent Events) |
| 인증 | OAuth 2.0 + JWT (Connected App) |
| 특이사항 | BYOC (Bring Your Own Channel) 지원 |
| 개발 난이도 | ★★★★☆ (Omni-Channel, Flow 설정 복잡) |
| 명칭 변경 | 2025년 6월부터 Enhanced Chat으로 공식 명칭 변경 |

#### ⚠️ 주의사항

- **기존 Chat REST API는 2026년 2월 14일 retirement 예정** ✅
- Enhanced Chat API (구 MIAW) 사용 필수
- BYOC (Bring Your Own Channel) 기능으로 커스텀 채널 구현 가능

📚 샘플 앱: https://github.com/Salesforce-Async-Messaging/messaging-web-api-sample-app

### 3.3 Freshdesk - REST API

| 항목 | 내용 |
|------|------|
| API 방식 | REST API |
| 인증 | **API Key (Basic Authentication)** ⚠️ |
| OAuth 지원 | ❌ **미지원** (2025년 11월 기준) |
| 개발 난이도 | ★★★★☆ (API Key 관리 복잡도) |

#### ⚠️ 중요 변경사항

> **Freshdesk는 OAuth를 지원하지 않습니다**
> 
> - 인증 방식: API Key 기반 Basic Authentication
> - 사용자가 Freshdesk 관리 패널에서 API Key 발급
> - 앱 설정 UI에서 API Key 입력 및 암호화 저장
> - OAuth는 Freshservice, Freshchat에서만 지원

📚 문서: https://developers.freshdesk.com/api/

### 3.4 MS Teams - Bot Framework

| 항목 | 내용 |
|------|------|
| API 방식 | Bot Framework Connector REST API |
| 핵심 기능 | Proactive Message (사용자 요청 없이 메시지 전송) |
| 앱 설치 | Microsoft Graph API로 proactive 설치 가능 |
| 개발 난이도 | ★★★☆☆ (기존 경험 보유, 공식 샘플 풍부) |

#### 핵심 요구사항

- Proactive 메시지 전송 전 앱이 먼저 설치되어야 함
- `conversationUpdate` 이벤트로 대화 정보 캐싱 필요
- `TurnContext`에서 conversation reference 획득

---

## 4. 멀티테넌트 아키텍처

### 4.1 테넌트 구성 DB 스키마

```
tenants
├── tenant_id (PK)
├── platform (zendesk | salesforce | freshdesk)
├── auth_type (oauth | apikey)
├── oauth_access_token (encrypted, nullable)
├── oauth_refresh_token (encrypted, nullable)
├── api_key (encrypted, nullable)  ← 🆕 Freshdesk용
├── webhook_secret
├── teams_tenant_id
└── created_at, updated_at
```

### 4.2 Webhook 엔드포인트 구조

| 플랫폼 | Webhook URL 패턴 |
|--------|------------------|
| Zendesk | `POST /webhook/zendesk/:tenantId` |
| Salesforce | `POST /webhook/salesforce/:tenantId` |
| Freshdesk | `POST /webhook/freshdesk/:tenantId` |

### 4.3 인증 핸들러

각 플랫폼별 인증 flow를 처리하는 독립된 핸들러 구현:

| 플랫폼 | 인증 방식 | 엔드포인트 |
|--------|----------|-----------|
| Zendesk | OAuth 2.0 | `/auth/zendesk/callback` |
| Salesforce | OAuth 2.0 | `/auth/salesforce/callback` |
| Freshdesk | **API Key** | `/auth/freshdesk/setup` (설정 UI) |

---

## 5. 마켓플레이스 전략

### 5.1 핵심 인사이트

> 💡 앱은 Teams UI에서만 동작하므로 **Teams 마켓플레이스에만 출시**하면 됩니다. 각 헬프데스크 마켓플레이스는 '그 솔루션 UI 안에서' 뭔가를 보여줄 때만 필요합니다.

### 5.2 마켓플레이스 필요 여부

| 플랫폼 | 마켓플레이스 | 필요 작업 |
|--------|-------------|-----------|
| MS Teams | ✅ **필수** | 마켓플레이스 앱 등록 및 인증 |
| Zendesk | ❌ 불필요 | OAuth Client 등록만 (Admin Center) |
| Salesforce | ❌ 불필요 | Connected App 등록만 (Setup) |
| Freshdesk | ❌ 불필요 | API Key 발급 안내만 |

### 5.3 사용자 플로우

```
┌────────────────────────────────────────────┐
│       Teams 마켓플레이스에서 앱 설치         │
└────────────────────┬───────────────────────┘
                     ▼
┌────────────────────────────────────────────┐
│          앱 설정 화면 (Teams 내부)           │
│  ┌──────────────────────────────────────┐  │
│  │  [🔗 Zendesk 연결]    ← OAuth 인증    │  │
│  │  [🔗 Salesforce 연결] ← OAuth 인증    │  │
│  │  [🔑 Freshdesk 연결]  ← API Key 입력  │  │
│  └──────────────────────────────────────┘  │
└────────────────────┬───────────────────────┘
                     ▼
        플랫폼별 인증 완료 (OAuth 또는 API Key)
                     ▼
               ✅ 연동 완료!
```

---

## 6. 개발 로드맵

| Phase | 작업 내용 | 난이도 | 예상 기간 |
|-------|----------|--------|----------|
| Phase 1 | Teams Bot + Zendesk OAuth 연동 | ★★★☆☆ | 3-4주 |
| Phase 2 | Multi-tenant 지원 + 설정 UI | ★★★☆☆ | 2-3주 |
| Phase 3 | Salesforce, Freshdesk Adapter 추가 | ★★★☆☆ | 4-5주 |
| Phase 4 | Teams 마켓플레이스 출시 | ★★★★☆ | 2-4주 |

### 6.1 Phase 1 상세 - Teams + Zendesk MVP

1. Teams Bot 기본 구조 구현 (Bot Framework SDK)
2. Zendesk OAuth 2.0 연동 (Authorization Code Flow)
3. Sunshine Conversations API 메시지 송신 구현
4. Zendesk Webhook 수신 및 Teams Proactive Message 전송
5. Conversation 매핑 (Teams User ↔ Zendesk Conversation)
6. **Conversation Reference 영구 저장 및 유효성 검증** 🆕

### 6.2 기술 스택 권장

| 영역 | 기술 |
|------|------|
| Runtime | Node.js 20+ (TypeScript) |
| Framework | Express.js 또는 Fastify |
| Bot SDK | botbuilder (Microsoft Bot Framework) |
| Database | PostgreSQL (테넌트/매핑 저장) |
| Cache | Redis (conversation reference 캐싱) |
| Encryption | AES-256 (API Key, OAuth Token) 🆕 |
| Hosting | Azure App Service 또는 AWS Lambda |

---

## 7. 구현 가이드라인

### 7.1 필수 구현 사항

#### Teams Proactive Messaging ⚠️ **업데이트됨**

**올바른 이해**:
- Conversation reference는 **Bot이 설치되어 있는 동안 계속 유효**
- Service URL은 **시간 기반 만료가 없음** (인프라 변경 시만 변경됨)
- ~~24시간 만료 체크 불필요~~ ❌

**구현 방법**:
1. 앱 설치 시 `conversationUpdate` 이벤트에서 `ConversationReference` 저장
2. 저장된 reference로 `continueConversation()` 호출하여 Proactive 메시지 전송
3. **실패 시 에러 감지 및 재획득 로직 구현**
4. Service URL 변경 감지를 위한 예외 처리

```typescript
// ✅ 올바른 구현
try {
  await adapter.continueConversation(conversationReference, async (context) => {
    await context.sendActivity(message);
  });
} catch (error) {
  if (error.message.includes('ServiceUrl')) {
    // Service URL 변경 감지 → 새로운 reference 필요
    logger.warn('Service URL changed, need new conversation reference');
    // 사용자의 다음 메시지를 기다려 reference 재획득
  } else if (error.message.includes('BotNotInConversation')) {
    // Bot이 제거됨
    logger.error('Bot removed from conversation');
    // 테넌트 비활성화 처리
  } else {
    throw error;
  }
}
```

#### OAuth Token 관리

- Access Token 암호화 저장 (AES-256)
- Refresh Token으로 자동 갱신 구현
- Token 만료 전 preemptive refresh (만료 5분 전)

#### API Key 관리 (Freshdesk) 🆕

- 사용자 입력 시 즉시 AES-256 암호화
- 환경 변수로 암호화 키 관리 (rotation 지원)
- API Key 유효성 테스트 엔드포인트 제공
- 잘못된 키 감지 시 사용자에게 재입력 안내

```typescript
// Freshdesk API Key 검증
async function validateFreshdeskApiKey(apiKey: string, domain: string): Promise<boolean> {
  try {
    const response = await fetch(`https://${domain}.freshdesk.com/api/v2/tickets`, {
      headers: {
        'Authorization': `Basic ${Buffer.from(apiKey + ':X').toString('base64')}`
      }
    });
    return response.status === 200;
  } catch (error) {
    return false;
  }
}
```

#### Webhook 보안

- HMAC signature 검증 (Zendesk, Salesforce, Freshdesk)
- Tenant ID 기반 라우팅으로 격리 보장
- Rate limiting 구현

### 7.2 에러 처리 (업데이트됨)

| 시나리오 | 처리 방안 |
|---------|----------|
| OAuth 토큰 만료 | Refresh token으로 자동 갱신, 실패 시 재인증 안내 |
| API Key 무효 (Freshdesk) | 401 에러 감지 시 사용자에게 재설정 요청 🆕 |
| Webhook 전송 실패 | Exponential backoff로 재시도 (최대 3회) |
| **Service URL 변경** 🆕 | Proactive message 실패 감지 → 새 reference 대기 |
| Teams 앱 삭제됨 | BotNotInConversation 에러 시 테넌트 비활성화 |
| 상담원 offline | 큐잉 후 상담원 연결 시 전달 (플랫폼 기능 활용) |

---

## 8. 운영/검증 전략

### 8.1 운영 가시성

- OAuth 토큰 발급·갱신/만료 시점을 지표화하고, 실패 시 알람을 발송한다.
- **API Key 검증 실패 이벤트 추적** 🆕
- Webhook 수신, API 요청, Proactive 메시지 배송 결과 등의 로그와 지연시간을 분리된 tracing 로그로 기록한다.
- **Service URL 변경 감지 이벤트 모니터링** 🆕
- Teams 앱 삭제·tenant 비활성화, Signature 검증 실패, SSE 연결 끊김 등 주요 오류에 대해 PagerDuty/Slack 알림을 마련한다.
- 각 테넌트의 상태를 반환하는 `health` 엔드포인트와 rate limiting metrics를 제공하여 플랫폼 제한(예: Zendesk rate limit, Salesforce SSE 연결 수)을 지켜본다.

### 8.2 검증 시나리오

- Teams → Zendesk/Freshdesk/Salesforce까지 end-to-end 메시지 흐름을 자동화 테스트로 확보하되, 실제 플랫폼 API를 가상화한 모의 서버로 회귀한다.
- Webhook 재전송, signature 위조, Salesforce SSE 유휴 종료를 시뮬레이션하여 재시도/재연결 로직을 점검한다.
- **Service URL 변경, Bot 재설치, 앱 삭제 시나리오 테스트** 🆕
- **Freshdesk API Key 만료/변경 시나리오 테스트** 🆕
- OAuth refresh 실패 시 사용자 재인증 유도, 암호화 키 교체 시나리오 확인, dependencies vulnerability scan을 포함하는 정기 보안 검증을 수행한다.

---

## 9. 플랫폼별 인증 구현 상세

### 9.1 Zendesk OAuth Flow

```typescript
// OAuth 2.0 Authorization Code Flow
const authUrl = `https://${subdomain}.zendesk.com/oauth/authorizations/new?` +
  `response_type=code&` +
  `redirect_uri=${REDIRECT_URI}&` +
  `client_id=${CLIENT_ID}&` +
  `scope=read write`;
```

### 9.2 Salesforce OAuth Flow

```typescript
// Connected App OAuth 2.0 + JWT
const authUrl = `https://login.salesforce.com/services/oauth2/authorize?` +
  `response_type=code&` +
  `client_id=${CLIENT_ID}&` +
  `redirect_uri=${REDIRECT_URI}&` +
  `scope=api refresh_token`;
```

### 9.3 Freshdesk API Key Setup 🆕

```typescript
// API Key 기반 인증 (OAuth 불가)
// 사용자가 설정 UI에서 직접 입력

interface FreshdeskConfig {
  domain: string;        // example.freshdesk.com
  apiKey: string;        // 암호화하여 저장
  webhookSecret: string; // Webhook 검증용
}

// API 호출 시
const headers = {
  'Authorization': `Basic ${Buffer.from(apiKey + ':X').toString('base64')}`,
  'Content-Type': 'application/json'
};
```

**설정 UI 플로우**:
1. 사용자가 Freshdesk 도메인 입력 (예: `mycompany.freshdesk.com`)
2. API Key 입력 (Freshdesk Profile Settings → API Key에서 확인)
3. "연결 테스트" 버튼으로 유효성 검증
4. 검증 성공 시 암호화하여 DB 저장

---

## 10. 참고 자료

### 10.1 공식 문서

| 플랫폼 | URL |
|--------|-----|
| Zendesk Sunshine Conversations | https://developer.zendesk.com/documentation/conversations/ |
| Salesforce Enhanced Chat (구 MIAW) | https://developer.salesforce.com/docs/service/messaging-api/ |
| Salesforce Legacy Chat Retirement | https://help.salesforce.com/s/articleView?id=release-notes.rn_chat_retirement.htm |
| Teams Bot Framework | https://learn.microsoft.com/en-us/microsoftteams/platform/bots/ |
| Teams Proactive Messages | https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/send-proactive-messages |
| Freshdesk API | https://developers.freshdesk.com/api/ |

### 10.2 샘플 코드

- **Salesforce Enhanced Chat Sample**: https://github.com/Salesforce-Async-Messaging/messaging-web-api-sample-app
- **Zendesk BYOC Sample**: https://github.com/zendesk/sunshine-conversations-byoc
- **Teams Bot Samples**: https://github.com/microsoft/BotBuilder-Samples

### 10.3 커뮤니티 검증 자료 🆕

- **Conversation ID Lifespan**: https://learn.microsoft.com/en-us/answers/questions/1603840/lifespan-of-conversation-id-created-between-bot-an
- **Freshdesk OAuth Status**: https://community.freshworks.dev/t/how-to-use-oauth-authentication-mechanism-for-freshdesk-api/1691

---

## 11. 알려진 제약사항 및 해결방안 🆕

### 11.1 Freshdesk OAuth 미지원

**제약**:
- Freshdesk는 OAuth를 지원하지 않음 (2025년 11월 기준)
- API Key 기반 인증만 가능

**해결방안**:
- 사용자 친화적인 API Key 입력 UI 제공
- API Key 유효성 실시간 검증
- 안전한 암호화 저장 (AES-256)
- Freshdesk에서 OAuth 지원 시 즉시 마이그레이션 가능하도록 추상화 레이어 설계

### 11.2 Teams Conversation Reference 관리

**올바른 이해**:
- ~~24시간 만료 없음~~ (이전 오해)
- Bot 설치 기간 동안 유효
- Service URL 변경 시만 재획득 필요

**구현 전략**:
- 실패 시 graceful degradation
- 사용자에게 "메시지를 다시 보내주세요" 안내
- 백그라운드에서 자동 재연결 시도

---

## 12. 보안 고려사항

### 12.1 자격증명 관리

| 자격증명 유형 | 저장 방식 | 순환 주기 |
|-------------|----------|----------|
| OAuth Access Token | AES-256 암호화 | 자동 (refresh token) |
| OAuth Refresh Token | AES-256 암호화 | 수동 (재인증 필요 시) |
| Freshdesk API Key | AES-256 암호화 | 수동 (사용자 변경 시) |
| Webhook Secret | AES-256 암호화 | 90일 권장 |
| 암호화 마스터 키 | AWS KMS / Azure Key Vault | 연 1회 권장 |

### 12.2 API Key 노출 방지 (Freshdesk)

- 클라이언트 측에서 절대 평문 전송 금지
- HTTPS only
- API Key는 서버에서만 복호화
- 로그에 API Key 마스킹 처리
- 정기 감사 로그 검토

---

> **Document Version**: 1.1 (Updated)  
> **Last Updated**: 2025-11-28  
> **Status**: Production Ready  
> **Fact-Checked**: ✅ 2025-11-28
> 
> **주요 변경사항**:
> - ✅ Teams Bot conversation reference 만료 정책 수정
> - ✅ Freshdesk OAuth → API Key 인증으로 변경
> - ✅ Salesforce Enhanced Chat 명칭 업데이트
> - ✅ 보안 및 에러 처리 가이드 강화