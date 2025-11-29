"""Teams Bot 라우트"""
from fastapi import APIRouter, Request, Response

from botbuilder.schema import Activity

from app.teams.bot import get_teams_bot, TeamsMessage
from app.core.router import get_message_router
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/callback")
async def bot_callback(request: Request) -> Response:
    """Teams Bot 콜백 엔드포인트

    Bot Framework에서 들어오는 Activity 처리
    """
    try:
        # 요청 본문 파싱
        body = await request.json()
        activity = Activity().from_dict(body)

        # Auth 헤더 추출
        auth_header = request.headers.get("Authorization", "")

        # Bot 설정
        bot = get_teams_bot()
        message_router = get_message_router()

        # 메시지 핸들러 설정 (라우터와 연결)
        async def message_handler(context, message: TeamsMessage):
            await message_router.handle_teams_message(context, message)

        bot.set_message_handler(message_handler)

        # Activity 처리
        await bot.process_activity(activity, auth_header)

        return Response(status_code=200)

    except Exception as e:
        logger.error("Bot callback error", error=str(e))
        return Response(status_code=500)


@router.post("/messages")
async def bot_messages(request: Request) -> Response:
    """Teams Bot 메시지 엔드포인트 (별칭)

    Azure Bot Service는 /api/messages를 기본으로 사용
    """
    return await bot_callback(request)
