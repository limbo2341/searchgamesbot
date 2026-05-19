import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, ReferralRepository
from bot.locales import t
from bot.keyboards import language_keyboard, main_menu_keyboard, admin_main_keyboard
from bot.states import LanguageSetup

logger = logging.getLogger(__name__)
router = Router()

ALL_BACK_TEXTS = ["← Back", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]


async def send_main_menu(message: Message, lang: str, user_id: int, is_admin: bool, is_premium: bool):
    """Надсилає головне меню з правильними кнопками залежно від статусу."""
    await message.answer(
        t("main_menu", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium),
        parse_mode="HTML",
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    invited_by = None
    args = message.text.split()
    if len(args) > 1:
        try:
            ref_id = int(args[1].replace("ref_", ""))
            if ref_id != user_id:
                invited_by = ref_id
        except (ValueError, IndexError):
            pass

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user, created = await user_repo.get_or_create(
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            invited_by=invited_by,
        )

        if not created:
            await user_repo.check_and_expire_premium(user.telegram_id)
        if created and invited_by:
            ref_repo = ReferralRepository(session)
            inviter = await user_repo.get_by_telegram_id(invited_by)
            if inviter and not await ref_repo.exists(user_id):
                await ref_repo.create(inviter_id=inviter.id, invited_id=user.id)
                new_count = await user_repo.increment_referrals(invited_by)
                if new_count % settings.referral_required_count == 0:
                    await user_repo.set_premium(invited_by, days=settings.referral_reward_days)
                    try:
                        await message.bot.send_message(
                            invited_by,
                            t("referral_bonus_granted", inviter.language),
                        )
                    except Exception:
                        pass

        is_admin_user = user_id in settings.admin_ids
        is_premium = bool(user.premium_status)

        if created or not user.language:
            await state.set_state(LanguageSetup.choosing_language)
            await message.answer(t("choose_language"), reply_markup=language_keyboard())
        else:
            await user_repo.update_username(user_id, username or "", first_name or "")
            await message.answer(
                t("welcome", user.language),
                reply_markup=main_menu_keyboard(
                    user.language,
                    is_admin=is_admin_user,
                    is_premium=is_premium,
                ),
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery, state: FSMContext):
    language = callback.data.split(":")[1]
    user_id = callback.from_user.id
    is_admin_user = user_id in settings.admin_ids

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_language(user_id, language)
        user = await user_repo.get_by_telegram_id(user_id)
        is_premium = bool(user.premium_status) if user else False

    await state.clear()
    await callback.message.edit_text(t("language_set", language))
    await callback.message.answer(
        t("welcome", language),
        reply_markup=main_menu_keyboard(language, is_admin=is_admin_user, is_premium=is_premium),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    is_admin_user = user_id in settings.admin_ids
    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(user_id)
        lang = user.language if user else "en"
        is_premium = bool(user.premium_status) if user else False

    await message.answer(
        t("main_menu", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=is_admin_user, is_premium=is_premium),
        parse_mode="HTML",
    )


@router.message(F.text == "🔧 Admin Panel")
async def admin_button_handler(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    await state.clear()
    await message.answer("🔧 <b>Admin Panel</b>", reply_markup=admin_main_keyboard(), parse_mode="HTML")


@router.message(F.text.in_(ALL_BACK_TEXTS))
async def universal_back(message: Message, state: FSMContext):
    """Universal back/main menu — завжди показує правильні кнопки."""
    await state.clear()
    user_id = message.from_user.id
    is_admin_user = user_id in settings.admin_ids
    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(user_id)
        lang = user.language if user else "en"
        is_premium = bool(user.premium_status) if user else False

    await message.answer(
        t("main_menu", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=is_admin_user, is_premium=is_premium),
        parse_mode="HTML",
    )
