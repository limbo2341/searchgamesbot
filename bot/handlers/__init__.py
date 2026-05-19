from aiogram import Router
from .start import router as start_router
from .search import router as search_router
from .premium import router as premium_router
from .misc import router as misc_router
from .screenshot import router as screenshot_router
from .admin import router as admin_router
from .subscription import router as subscription_router
from .profile import router as profile_router
from .bot_control import router as bot_control_router
from .ai_chat import router as ai_chat_router


def get_all_routers() -> Router:
    main_router = Router()
    main_router.include_router(start_router)
    main_router.include_router(admin_router)
    main_router.include_router(bot_control_router)
    main_router.include_router(profile_router)
    main_router.include_router(ai_chat_router)
    main_router.include_router(search_router)
    main_router.include_router(premium_router)
    main_router.include_router(screenshot_router)
    main_router.include_router(misc_router)
    main_router.include_router(subscription_router)
    return main_router
