import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import (
    UserRepository, SearchHistoryRepository,
    FavoriteRepository, SupportRepository
)
from bot.locales import t
from bot.keyboards import (
    main_menu_keyboard, back_keyboard, settings_keyboard,
    language_keyboard, referral_keyboard, favorites_keyboard
)
from bot.states import SupportStates

logger = logging.getLogger(__name__)
router = Router()

ALL_BACK_TEXTS = ["← Back", "← Назад", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def get_user_lang(telegram_id: int) -> str:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user.language if user else "en"


# ===== HISTORY =====
@router.message(F.text.in_(["🕓 History", "🕓 История", "🕓 Історія"]))
async def history_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        history_repo = SearchHistoryRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer(t("error_general", lang))
            return

        limit = 20 if user.premium_status else 10
        history = await history_repo.get_user_history(user.id, limit=limit)

    if not history:
        await message.answer(t("history_empty", lang), reply_markup=main_menu_keyboard(lang, is_admin=_is_admin(message.from_user.id)))
        return

    text = t("history_title", lang)
    for i, item in enumerate(history, 1):
        date_str = item.created_at.strftime("%d.%m %H:%M")
        result = f" → {item.result_game}" if item.result_game else ""
        text += f"{i}. <b>{item.search_query}</b>{result} <i>({date_str})</i>\n"

    await message.answer(text, reply_markup=main_menu_keyboard(lang, is_admin=_is_admin(message.from_user.id)), parse_mode="HTML")


# ===== FAVORITES =====
@router.message(F.text.in_(["❤️ Favorites", "❤️ Избранное", "❤️ Обране"]))
async def favorites_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        fav_repo = FavoriteRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer(t("error_general", lang))
            return

        favorites = await fav_repo.get_user_favorites(user.id)

    if not favorites:
        await message.answer(t("favorites_empty", lang), reply_markup=main_menu_keyboard(lang, is_admin=_is_admin(message.from_user.id)))
        return

    text = t("favorites_title", lang)
    for i, fav in enumerate(favorites[:10], 1):
        text += f"{i}. 🎮 <b>{fav.game_name}</b>\n"

    await message.answer(
        text,
        reply_markup=favorites_keyboard(favorites, lang),
        parse_mode="HTML",
    )


# ===== SETTINGS =====
@router.message(F.text.in_(["⚙️ Settings", "⚙️ Настройки", "⚙️ Налаштування"]))
async def settings_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    await message.answer(
        t("settings_menu", lang) + "\n\n" + t("current_language", lang),
        reply_markup=settings_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:language")
async def change_language(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        t("choose_language"),
        reply_markup=language_keyboard(),
    )
    await callback.answer()


# ===== SUPPORT =====
@router.message(F.text.in_(["🆘 Support", "🆘 Поддержка", "🆘 Підтримка"]))
async def support_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(SupportStates.waiting_for_message)
    await message.answer(
        t("support_prompt", lang),
        reply_markup=back_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(SupportStates.waiting_for_message)
async def receive_support_message(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    if message.text in [t("btn_back", lang), t("btn_main_menu", lang), "← Back", "← Назад"]:
        await state.clear()
        await message.answer(
            t("main_menu", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=_is_admin(message.from_user.id)),
            parse_mode="HTML",
        )
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        support_repo = SupportRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer(t("error_general", lang))
            return

        ticket = await support_repo.create(user_id=user.id, message=message.text)

    user_display = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"

    from bot.keyboards import admin_support_ticket_keyboard
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                t(
                    "new_support_admin",
                    "en",
                    ticket_id=ticket.id,
                    user=user_display,
                    message=message.text,
                ),
                reply_markup=admin_support_ticket_keyboard(ticket.id, message.from_user.id),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    await state.clear()
    await message.answer(
        t("support_sent", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=_is_admin(message.from_user.id)),
        parse_mode="HTML",
    )


# ===== ABOUT =====
@router.message(F.text.in_(["ℹ️ About Bot", "ℹ️ О боте", "ℹ️ Про бота"]))
async def about_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        t("about_text", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=_is_admin(message.from_user.id)),
        parse_mode="HTML",
    )


# ===== REFERRAL =====
@router.message(F.text.in_(["👥 Invite Friends", "👥 Пригласить друга", "👥 Запросити друга"]))
async def referral_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

    ref_link = f"https://t.me/SearchForGame_bot?start=ref_{message.from_user.id}"
    count = user.referrals_count if user else 0

    await message.answer(
        t("referral_info", lang, link=ref_link, count=count),
        reply_markup=referral_keyboard(ref_link, lang),
        parse_mode="HTML",
    )
