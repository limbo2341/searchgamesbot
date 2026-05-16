"""
profile.py — Хендлер кнопки «Профіль».
Показує всю інформацію про користувача.
"""

from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, SearchHistoryRepository, FavoriteRepository
from bot.locales import t
from bot.keyboards import back_keyboard, upgrade_premium_keyboard

router = Router()

PROFILE_BTN = ["👤 Профіль", "👤 Профиль", "👤 Profile"]


@router.message(F.text.in_(PROFILE_BTN))
async def show_profile(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        search_repo = SearchHistoryRepository(session)
        fav_repo = FavoriteRepository(session)

        user = await user_repo.get_by_telegram_id(user_id)
        if not user:
            await message.answer("❌ Профіль не знайдено.")
            return

        lang = user.language
        is_admin = user_id in settings.admin_ids

        # Кількість пошуків за весь час
        total_searches = await search_repo.count_by_user(user.id)
        # Кількість обраного
        fav_count = await fav_repo.count_by_user(user.id)

    # Ім'я
    name = user.first_name or user.username or f"User {user_id}"
    username_str = f"@{user.username}" if user.username else "—"

    # Дата реєстрації
    reg_date = user.registration_date.strftime("%d.%m.%Y") if user.registration_date else "—"

    # Статус
    if is_admin:
        status = "👑 Адмін"
    elif user.premium_status:
        status = "⭐ Premium"
    else:
        status = "👤 Безкоштовний"

    # Premium термін
    premium_info = ""
    if user.premium_status and user.premium_until:
        now = datetime.now(timezone.utc)
        until = user.premium_until
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until > now:
            days_left = (until - now).days
            premium_info = f"\n⏳ <b>Premium діє ще:</b> {days_left} дн. (до {until.strftime('%d.%m.%Y')})"
        else:
            premium_info = "\n⚠️ <b>Premium:</b> закінчився"
    elif is_admin:
        premium_info = "\n♾️ <b>Пошук:</b> безліміт (адмін)"
    elif user.premium_status:
        premium_info = "\n♾️ <b>Premium:</b> безстроковий"

    # Ліміт пошуків сьогодні
    if is_admin or user.premium_status:
        search_limit_str = "♾️ Безліміт"
    else:
        used = user.daily_search_count or 0
        remaining = max(0, settings.free_daily_searches - used)
        search_limit_str = f"{remaining}/{settings.free_daily_searches} залишилось сьогодні"

    # Запрошені
    referrals = user.referrals_count or 0
    referral_progress = ""
    if not user.premium_status and not is_admin:
        needed = settings.referral_required_count
        current = referrals % needed if needed else 0
        referral_progress = f" ({current}/{needed} до бонусу)"

    text = (
        f"👤 <b>Профіль</b>\n\n"
        f"📛 <b>Ім'я:</b> {name}\n"
        f"🔖 <b>Username:</b> {username_str}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📅 <b>Реєстрація:</b> {reg_date}\n\n"
        f"🏅 <b>Статус:</b> {status}"
        f"{premium_info}\n\n"
        f"🔍 <b>Пошуків сьогодні:</b> {search_limit_str}\n"
        f"📚 <b>Всього пошуків:</b> {total_searches}\n"
        f"❤️ <b>Обране:</b> {fav_count} ігор\n"
        f"👥 <b>Запрошено друзів:</b> {referrals}{referral_progress}\n"
    )

    if not user.premium_status and not is_admin:
        text += (
            f"\n💡 <i>Купи Premium для безлімітного пошуку, "
            f"пошуку по скріншоту та чату з AI!</i>"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=upgrade_premium_keyboard(lang))
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=back_keyboard(lang))
