# Teams-Helpdesk Bridge AI Instructions

## 🏗 Architecture Overview
This project is a multi-tenant bridge between **Microsoft Teams** and various **Helpdesk Platforms** (Freshchat, Zendesk, Freshdesk).

- **Message Router (`app/core/router.py`)**: The central orchestrator that routes messages between Teams and Helpdesks.
- **Platform Factory (`app/core/platform_factory.py`)**: Dynamically creates helpdesk clients based on tenant configuration.
- **Teams Bot (`app/teams/bot.py`)**: Wraps Bot Framework SDK to handle Teams activities and proactive messaging.
- **Tenant Service (`app/core/tenant.py`)**: Manages multi-tenant configurations, including encrypted platform credentials.
- **Database (`app/database.py`)**: Uses Supabase for storing `tenants`, `conversations` (mapping Teams to Helpdesk IDs), and `user_profiles`.

## 🛠 Development Workflows
- **Local Execution**: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **Admin Setup**: Use `POST /api/admin/config` with `X-Tenant-ID` header to configure a tenant.
- **Debugging**: Use `GET /api/admin/validate` to check if tenant configuration is correctly decrypted and valid.
- **PoC Testing**: For Freshdesk PoC, use `X-Tenant-ID` and `X-Requester-Email` headers to bypass full Teams SSO.

## 📋 Coding Conventions & Patterns
- **Adapter Pattern**: All helpdesk clients must implement the `HelpdeskClient` protocol in `app/core/platform_factory.py`.
- **Security**: NEVER store raw API keys in the database. Use `app/utils/crypto.py` to encrypt/decrypt `platform_config` before saving to/reading from Supabase.
- **Multi-tenancy**: Always scope operations by `teams_tenant_id`.
- **Teams UI**: Use **Adaptive Cards** for complex interactions (e.g., intake forms). See `app/teams/bot.py` for examples.
- **Proactive Messages**: When a helpdesk agent responds, the bridge uses `TeamsBot.send_proactive_message` to notify the user.
- **File Structure**:
  - `app/adapters/{platform}/client.py`: API client for the platform.
  - `app/adapters/{platform}/webhook.py`: Logic for parsing platform webhooks.
  - `app/adapters/{platform}/routes.py`: FastAPI routes for platform-specific endpoints.

## 🔑 Critical Environment Variables
- `ENCRYPTION_KEY`: Required for decrypting tenant credentials.
- `PUBLIC_URL`: The base URL of the bridge server (used for webhooks).
- `BOT_APP_ID`, `BOT_APP_PASSWORD`: Azure Bot credentials.
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`: Supabase connection details.

## 🚀 Deployment
- **Platform**: Fly.io (configured via `fly.toml`).
- **Database**: Supabase (migrations in `supabase/migrations/`).
