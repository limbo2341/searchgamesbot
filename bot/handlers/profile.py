from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, SearchHistoryRepository, FavoriteRepository
from bot.keyboards import back_keyboard

router = Router()
PROFILE_BTN = ["👤 Профіль", "👤 Профиль", "👤 Profile"]

@router.message(F.text.in_(PROFILE_BTN))
async def show_profile(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    is_admin = uid in settings.admin_ids
    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(uid)
        if not user:
            await message.answer("❌ Профіль не знайдено. Надішли /start")
            return
        lang = user.language
        history = await SearchHistoryRepository(session).get_user_history(user.id, limit=1000)
        total_searches = len(history)
        fav_count = await FavoriteRepository(session).count_user_favorites(user.id)
    name = user.first_name or user.username or f"User {uid}"
    username_str = f"@{user.username}" if user.username else "—"
    reg_date = user.registration_date.strftime("%d.%m.%Y") if user.registration_date else "—"
    if is_admin: status = "👑 Адмін"
    elif user.premium_status: status = "⭐ Premium"
    else: status = "👤 Безкоштовний"
    premium_info = ""
    if user.premium_status and user.premium_until:
        now = datetime.now(timezone.utc)
        until = user.premium_until.replace(tzinfo=timezone.utc) if user.premium_until.tzinfo is None else user.premium_until
        if until > now:
            premium_info = f"\n⏳ <b>Premium ще:</b> {(until-now).days} дн. (до {until.strftime('%d.%m.%Y')})"
        else:
            premium_info = "\n⚠️ <b>Premium:</b> закінчився"
    elif is_admin: premium_info = "\n♾️ Безліміт (адмін)"
    elif user.premium_status: premium_info = "\n♾️ Premium безстроковий"
    if is_admin or user.premium_status: search_str = "♾️ Безліміт"
    else:
        used = user.daily_search_count or 0
        search_str = f"{max(0, settings.free_daily_searches - used)}/{settings.free_daily_searches} залишилось"
    refs = user.referrals_count or 0
    ref_str = f"{refs} ({refs % settings.referral_required_count}/{settings.referral_required_count} до бонусу)" if not (user.premium_status or is_admin) else str(refs)
    text = (f"👤 <b>Профіль</b>\n\n📛 <b>Ім'я:</b> {name}\n🔖 <b>Username:</b> {username_str}\n🆔 <b>ID:</b> <code>{uid}</code>\n📅 <b>Реєстрація:</b> {reg_date}\n\n🏅 <b>Статус:</b> {status}{premium_info}\n\n🔍 <b>Пошуків сьогодні:</b> {search_str}\n📚 <b>Всього пошуків:</b> {total_searches}\n❤️ <b>Обране:</b> {fav_count} ігор\n👥 <b>Запрошено:</b> {ref_str}\n")
    if not user.premium_status and not is_admin:
        text += "\n💡 <i>Купи Premium для безліміту, пошуку по фото та AI чату!</i>"
    await message.answer(text, parse_mode="HTML", reply_markup=back_keyboard(lang))
