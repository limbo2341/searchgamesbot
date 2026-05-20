import logging
import asyncio
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, PaymentRepository, SupportRepository, SearchHistoryRepository, FavoriteRepository
from bot.keyboards import admin_main_keyboard, admin_payment_keyboard, admin_support_ticket_keyboard
from bot.states import AdminStates

logger = logging.getLogger(__name__)
router = Router()

# Головний адмін — тільки він може банити адмінів і керувати адмін-правами
MAIN_ADMIN_ID = 7245932902


def is_admin(tid: int) -> bool:
    return tid in settings.admin_ids


def is_main_admin(tid: int) -> bool:
    return tid == MAIN_ADMIN_ID


async def _get_bot_status() -> tuple[bool, str]:
    try:
        from bot.database.engine import get_redis
        redis = await get_redis()
        if not redis:
            return False, ""
        disabled = await redis.get("bot:disabled")
        if disabled:
            reason_raw = await redis.get("bot:disable_reason")
            reason = reason_raw.decode() if isinstance(reason_raw, bytes) else str(reason_raw or "")
            return True, reason
        return False, ""
    except Exception:
        return False, ""


def _confirm_keyboard(action: str, target_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Підтвердити", callback_data=f"mainadmin:confirm:{action}:{target_id}")
    builder.button(text="❌ Відхилити", callback_data=f"mainadmin:reject:{action}:{target_id}")
    builder.adjust(2)
    return builder.as_markup()


@router.message(Command("admin"))
@router.message(F.text == "🔧 Admin Panel")
async def admin_panel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🔧 <b>Admin Panel</b>",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )


# ── Статистика ──

@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        from bot.repositories import SearchHistoryRepository
        history_repo = SearchHistoryRepository(session)
        total_users = await user_repo.get_total_count()
        premium_users = await user_repo.get_premium_count()
        total_searches = await history_repo.get_total_count()

    is_disabled, reason = await _get_bot_status()
    bot_status = f"🔴 Вимкнений\nПричина: {reason}" if is_disabled else "🟢 Працює"

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"🤖 <b>Статус:</b> {bot_status}\n\n"
        f"👥 <b>Всього користувачів:</b> {total_users}\n"
        f"⭐ <b>Premium:</b> {premium_users}\n"
        f"🔍 <b>Всього пошуків:</b> {total_searches}\n"
    )

    await callback.message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())
    await callback.answer()


# ── Користувачі ──

@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery):
    await _show_users_page(callback, 0)

@router.callback_query(F.data.startswith("admin:stats:p:"))
async def admin_stats_paged(callback: CallbackQuery):
    page = int(callback.data.split(":")[-1])
    await _show_stats_page(callback, page)

@router.callback_query(F.data.startswith("admin:users:p:"))
async def admin_users_paged(callback: CallbackQuery):
    await _show_users_page(callback, int(callback.data.split(":")[3]))

async def _show_users_page(callback: CallbackQuery, page: int):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    from sqlalchemy import select, func
    from bot.models import SearchHistory
    per = 15
    async with async_session_maker() as session:
        users = await UserRepository(session).get_all_users()
        counts = {}
        for u in users:
            res = await session.execute(
                select(func.count(SearchHistory.id)).where(SearchHistory.user_id == u.id)
            )
            counts[u.id] = res.scalar_one()
    if not users:
        await callback.answer("Немає користувачів", show_alert=True)
        return
    users_sorted = sorted(users, key=lambda u: counts.get(u.id, 0), reverse=True)
    total = len(users_sorted)
    pages = (total + per - 1) // per
    page = max(0, min(page, pages - 1))
    chunk = users_sorted[page*per:(page+1)*per]
    text = f"👥 <b>Користувачі ({total})</b> — {page+1}/{pages}\n<i>↓ Найактивніші першими</i>\n\n"
    for u in chunk:
        p = "⭐" if u.premium_status else "👤"
        b = " 🚫" if u.is_banned else ""
        a = " 🔧" if u.telegram_id in settings.admin_ids else ""
        sc = counts.get(u.id, 0)
        text += f"{p} <b>{u.first_name or 'User'}</b> | <code>{u.telegram_id}</code>{b}{a}\n   🔍 {sc} пошуків\n"
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:users:p:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"admin:users:p:{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Оновити", callback_data=f"admin:users:p:{page}")])
    rows.append([InlineKeyboardButton(text="◀️ Меню", callback_data="admin:back")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

async def admin_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    async with async_session_maker() as session:
        pending = await PaymentRepository(session).get_pending()

    if not pending:
        await callback.message.answer("✅ Немає платежів на перевірку.")
        await callback.answer()
        return

    for payment in pending:
        # Отримуємо telegram_id користувача
        async with async_session_maker() as session:
            user = await UserRepository(session).get_by_id(payment.user_id)
        user_tid = user.telegram_id if user else payment.user_id

        text = (
            f"💳 <b>Платіж #{payment.id}</b>\n"
            f"User TG ID: <code>{user_tid}</code>\n"
            f"Тариф: {payment.tariff}\n"
            f"Сума: {payment.amount}\n"
            f"Метод: {payment.payment_method}\n"
            f"Дата: {payment.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        kb = admin_payment_keyboard(payment.id)
        if payment.screenshot_file_id:
            try:
                await callback.message.bot.send_photo(
                    callback.from_user.id,
                    photo=payment.screenshot_file_id,
                    caption=text,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
                continue
            except Exception:
                pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:pay:approve:"))
async def admin_approve_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        user_repo = UserRepository(session)

        payment = await pay_repo.get_by_id(payment_id)
        if not payment:
            await callback.answer("❌ Платіж не знайдено", show_alert=True)
            return

        if payment.status != "pending":
            await callback.answer(f"⚠️ Вже оброблено: {payment.status}", show_alert=True)
            return

        # Даємо Premium
        days_map = {"7": 7, "30": 30, "90": 90, "forever": None}
        days = days_map.get(str(payment.tariff), 30)

        user = await user_repo.get_by_id(payment.user_id)
        if user:
            await user_repo.set_premium(user.telegram_id, days=days)

        await pay_repo.approve(payment_id, callback.from_user.id)

    days_text = f"{days} днів" if days else "Назавжди"

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(f"✅ Платіж #{payment_id} підтверджено! Premium {days_text} → {user.telegram_id if user else '?'}")

    if user:
        try:
            await callback.bot.send_message(
                user.telegram_id,
                f"🎉 <b>Платіж підтверджено!</b>\n\nTвій Premium активовано на {days_text}! ⭐",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer("✅ Approved!")


@router.callback_query(F.data.startswith("admin:pay:reject:"))
async def admin_reject_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        payment = await pay_repo.get_by_id(payment_id)
        if not payment:
            await callback.answer("❌ Не знайдено", show_alert=True)
            return

        user = await UserRepository(session).get_by_id(payment.user_id)
        await pay_repo.reject(payment_id, callback.from_user.id)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(f"❌ Платіж #{payment_id} відхилено.")

    if user:
        try:
            await callback.bot.send_message(
                user.telegram_id,
                "❌ На жаль, твій платіж відхилено. Зверніться до підтримки.",
            )
        except Exception:
            pass

    await callback.answer("❌ Rejected!")


# ── Broadcast ──

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer("📢 Напиши повідомлення для розсилки:")
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    sending_msg = await message.answer("📢 Надсилаю...")

    async with async_session_maker() as session:
        users = await UserRepository(session).get_all_users()

    sent = failed = 0
    for user in users:
        if user.is_banned:
            continue
        try:
            await message.bot.send_message(
                user.telegram_id,
                f"📢 <b>Оголошення</b>\n\n{message.text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1

    try:
        await sending_msg.delete()
    except Exception:
        pass

    await message.answer(
        f"✅ <b>Розсилка завершена!</b>\n\n📨 Надіслано: {sent}\n❌ Помилок: {failed}\n👥 Всього: {sent+failed}",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


# ── Give Premium ──

@router.callback_query(F.data == "admin:give_premium")
async def admin_give_premium_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="give_premium")
    await callback.message.answer("👤 Введи Telegram ID користувача:")
    await callback.answer()


# ── Remove Premium ──

@router.callback_query(F.data == "admin:remove_premium")
async def admin_remove_premium_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="remove_premium")
    await callback.message.answer("👤 Введи Telegram ID для видалення Premium:")
    await callback.answer()


# ── Ban ──

@router.callback_query(F.data == "admin:ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="ban")
    await callback.message.answer("👤 Введи Telegram ID для бану:\n\n<i>Формат: ID причина_бану кількість_днів (0=назавжди)</i>\n<i>Приклад: 123456789 спам 7</i>", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="unban")
    await callback.message.answer("👤 Введи Telegram ID для розбану:")
    await callback.answer()


# ── Support ──

@router.callback_query(F.data == "admin:support")
async def admin_support(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    async with async_session_maker() as session:
        tickets = await SupportRepository(session).get_open()

    if not tickets:
        await callback.message.answer("✅ Немає відкритих тікетів.")
        await callback.answer()
        return

    for ticket in tickets[:10]:
        text = f"📨 <b>Тікет #{ticket.id}</b>\nВід: {ticket.user_id}\n\n{ticket.message}"
        await callback.message.answer(
            text,
            reply_markup=admin_support_ticket_keyboard(ticket.id, ticket.user_id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:support:reply:"))
async def admin_support_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    parts = callback.data.split(":")
    ticket_id = int(parts[3])
    user_tid = int(parts[4])
    await state.set_state(AdminStates.waiting_for_support_reply)
    await state.update_data(ticket_id=ticket_id, user_telegram_id=user_tid)
    await callback.message.answer(f"📝 Відповідь на тікет #{ticket_id}:")
    await callback.answer()


@router.message(AdminStates.waiting_for_support_reply)
async def admin_support_reply_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    user_tid = data.get("user_telegram_id")
    try:
        await message.bot.send_message(user_tid, f"📩 <b>Відповідь підтримки:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer(f"✅ Відповідь надіслано на тікет #{ticket_id}!", reply_markup=admin_main_keyboard())
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
    await state.clear()


@router.callback_query(F.data.startswith("admin:support:close:"))
async def admin_support_close(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    ticket_id = int(callback.data.split(":")[3])
    async with async_session_maker() as session:
        await SupportRepository(session).close(ticket_id, "Closed by admin")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(f"✅ Тікет #{ticket_id} закрито.")
    await callback.answer()


# ── Обробка user ID від простого адміна (з підтвердженням головного) ──

@router.message(AdminStates.waiting_for_user_id)
async def admin_user_id_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    action = data.get("action")

    # Парсимо введення
    parts = message.text.strip().split()
    try:
        target_id = int(parts[0])
    except (ValueError, IndexError):
        await message.answer("❌ Невірний формат.")
        return

    ban_reason = parts[1] if len(parts) > 1 else "Порушення правил"
    ban_days = int(parts[2]) if len(parts) > 2 else 0

    if action == "give_premium":
        await state.update_data(target_id=target_id)
        await state.set_state(AdminStates.waiting_for_premium_days)
        await message.answer("📅 Введи кількість днів (0 = назавжди):")
        return

    # Перевіряємо чи target є адміном
    target_is_admin = target_id in settings.admin_ids

    # Якщо звичайний адмін хоче зробити дію — надсилаємо запит головному
    if not is_main_admin(message.from_user.id):
        # Перевіряємо імунітет адміна
        if target_is_admin and action in ("ban", "remove_premium"):
            await message.answer("🚫 Ти не можеш виконати цю дію над іншим адміном. Тільки головний адмін може.")
            await state.clear()
            return

        # Надсилаємо запит головному адміну
        action_names = {
            "ban": f"🚫 Забанити на {ban_days} дн. (причина: {ban_reason})",
            "unban": "✅ Розбанити",
            "remove_premium": "❌ Забрати Premium",
        }
        action_text = action_names.get(action, action)

        # Зберігаємо дані для підтвердження
        await state.update_data(
            target_id=target_id,
            ban_reason=ban_reason,
            ban_days=ban_days,
            pending_action=action,
        )
        safe_reason = ban_reason.replace('_','-').replace(':','-')[:20]
        try:
            await message.bot.send_message(
                MAIN_ADMIN_ID,
                f"⚠️ <b>Запит від адміна</b>\n\n"
                f"👮 Адмін: @{message.from_user.username or message.from_user.id}\n"
                f"🎯 Дія: {action_text}\n"
                f"👤 Ціль: <code>{target_id}</code>\n\n"
                f"Підтвердити?",
                reply_markup=_confirm_keyboard(f"{action}_{target_id}_{ban_days}_{safe_reason}", message.from_user.id),
                parse_mode="HTML",
            )
            await message.answer(
                "⏳ <b>Запит надіслано головному адміну.</b>\nЗачекайте на підтвердження.",
                parse_mode="HTML",
                reply_markup=admin_main_keyboard(),
            )
        except Exception as e:
            await message.answer(f"❌ Не вдалось надіслати запит: {e}")

        await state.clear()
        return

    # Головний адмін — виконує без підтвердження
    await _execute_admin_action(
        message, action, target_id,
        ban_reason=ban_reason, ban_days=ban_days,
    )
    await state.clear()


# ── Підтвердження від головного адміна ──

@router.callback_query(F.data.startswith("mainadmin:confirm:"))
async def main_admin_confirm(callback: CallbackQuery):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌ Тільки головний адмін", show_alert=True)
        return

    # mainadmin:confirm:action_targetid_days_reason:requester_id
    parts = callback.data.split(":", 3)
    action_data = parts[2]
    requester_id = int(parts[3])

    action_parts = action_data.split("_")
    action = action_parts[0]
    target_id = int(action_parts[1])
    ban_days = int(action_parts[2]) if len(action_parts) > 2 else 0
    ban_reason = " ".join(action_parts[3:]).replace("_", " ") if len(action_parts) > 3 else "Порушення"

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _execute_admin_action_bot(
        callback.bot, callback.message, action, target_id,
        ban_reason=ban_reason, ban_days=ban_days,
    )

    # Повідомляємо адміна що зробив запит
    try:
        await callback.bot.send_message(requester_id, f"✅ Головний адмін підтвердив твій запит щодо <code>{target_id}</code>.", parse_mode="HTML")
    except Exception:
        pass

    await callback.answer("✅ Виконано!")


@router.callback_query(F.data.startswith("mainadmin:reject:"))
async def main_admin_reject(callback: CallbackQuery):
    if not is_main_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    parts = callback.data.split(":", 3)
    requester_id = int(parts[3])

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer("❌ Запит відхилено.")

    try:
        await callback.bot.send_message(requester_id, "❌ Головний адмін відхилив твій запит.")
    except Exception:
        pass

    await callback.answer("❌ Відхилено!")


async def _execute_admin_action(message: Message, action: str, target_id: int, ban_reason: str = "", ban_days: int = 0):
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(target_id)

        if not user:
            await message.answer("❌ Користувача не знайдено.")
            return

        if action == "ban":
            await user_repo.ban_user(target_id)
            ban_text = f"назавжди" if ban_days == 0 else f"на {ban_days} днів"
            await message.answer(f"🚫 Користувача <code>{target_id}</code> заблоковано {ban_text}.\nПричина: {ban_reason}", parse_mode="HTML", reply_markup=admin_main_keyboard())
            try:
                await message.bot.send_message(
                    target_id,
                    f"🚫 <b>Тебе заблоковано</b>\n\nПричина: {ban_reason}\nТермін: {ban_text}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        elif action == "unban":
            await user_repo.unban_user(target_id)
            await message.answer(f"✅ Користувача <code>{target_id}</code> розблоковано.", parse_mode="HTML", reply_markup=admin_main_keyboard())
            try:
                await message.bot.send_message(target_id, "✅ Тебе розблоковано! Можеш користуватись ботом.")
            except Exception:
                pass

        elif action == "remove_premium":
            await user_repo.remove_premium(target_id)
            await message.answer(f"❌ Premium видалено у <code>{target_id}</code>.", parse_mode="HTML", reply_markup=admin_main_keyboard())
            try:
                await message.bot.send_message(target_id, "ℹ️ Твій Premium статус видалено адміністратором.")
            except Exception:
                pass


async def _execute_admin_action_bot(bot, message: Message, action: str, target_id: int, ban_reason: str = "", ban_days: int = 0):
    """Версія без message.bot для використання з callback."""
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(target_id)

        if not user:
            await message.answer("❌ Користувача не знайдено.")
            return

        if action == "ban":
            await user_repo.ban_user(target_id)
            ban_text = "назавжди" if ban_days == 0 else f"на {ban_days} днів"
            await message.answer(f"🚫 <code>{target_id}</code> заблоковано {ban_text}. Причина: {ban_reason}", parse_mode="HTML")
            try:
                await bot.send_message(target_id, f"🚫 <b>Тебе заблоковано</b>\n\nПричина: {ban_reason}\nТермін: {ban_text}", parse_mode="HTML")
            except Exception:
                pass

        elif action == "unban":
            await user_repo.unban_user(target_id)
            await message.answer(f"✅ <code>{target_id}</code> розблоковано.", parse_mode="HTML")
            try:
                await bot.send_message(target_id, "✅ Тебе розблоковано!")
            except Exception:
                pass

        elif action == "remove_premium":
            await user_repo.remove_premium(target_id)
            await message.answer(f"❌ Premium видалено у <code>{target_id}</code>.", parse_mode="HTML")
            try:
                await bot.send_message(target_id, "ℹ️ Твій Premium статус видалено.")
            except Exception:
                pass


@router.message(AdminStates.waiting_for_premium_days)
async def admin_premium_days_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Невірне число.")
        return

    data = await state.get_data()
    target_id = data.get("target_id")

    # Якщо не головний адмін — надсилаємо запит
    if not is_main_admin(message.from_user.id):
        days_text = f"{days} днів" if days > 0 else "Назавжди"
        try:
            await message.bot.send_message(
                MAIN_ADMIN_ID,
                f"⚠️ <b>Запит від адміна</b>\n\n"
                f"👮 Адмін: @{message.from_user.username or message.from_user.id}\n"
                f"🎯 Дія: ⭐ Видати Premium на {days_text}\n"
                f"👤 Ціль: <code>{target_id}</code>",
                reply_markup=_confirm_keyboard(f"give_premium_{target_id}_{days}_none", message.from_user.id),
                parse_mode="HTML",
            )
            await message.answer("⏳ Запит надіслано головному адміну.", reply_markup=admin_main_keyboard())
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}")
        await state.clear()
        return

    # Головний адмін — одразу
    async with async_session_maker() as session:
        await UserRepository(session).set_premium(target_id, days=days if days > 0 else None)

    days_text = f"{days} днів" if days > 0 else "Назавжди"
    await message.answer(f"⭐ Premium видано <code>{target_id}</code> на {days_text}!", parse_mode="HTML", reply_markup=admin_main_keyboard())

    try:
        await message.bot.send_message(target_id, f"🎉 Тобі видано Premium на {days_text}! ⭐")
    except Exception:
        pass

    await state.clear()

@router.callback_query(F.data == "admin:user_stats")
async def show_user_stats(callback: CallbackQuery):
    await _show_stats_page(callback, 0)

@router.callback_query(F.data.startswith("admin:stats:p:"))
async def show_user_stats_paged(callback: CallbackQuery):
    await _show_stats_page(callback, int(callback.data.split(":")[3]))

async def _show_stats_page(callback: CallbackQuery, page: int):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    from sqlalchemy import select, func
    from bot.models import SearchHistory
    per = 15
    async with async_session_maker() as session:
        users = await UserRepository(session).get_all_users()
        user_data = []
        for u in users:
            res = await session.execute(
                select(func.count(SearchHistory.id)).where(SearchHistory.user_id == u.id)
            )
            cnt = res.scalar_one()
            user_data.append((u, cnt))
        user_data.sort(key=lambda x: x[1], reverse=True)
        total = len(user_data)
        pages = (total + per - 1) // per
        page = max(0, min(page, pages - 1))
        chunk = user_data[page*per:(page+1)*per]
        text = f"📊 <b>Статистика користувачів ({total})</b> — {page+1}/{pages}\n<i>↓ Найактивніші</i>\n\n"
        for u, sc in chunk:
            p = "⭐" if u.premium_status else "👤"
            b = " 🚫" if u.is_banned else ""
            text += f"{p} <b>{u.first_name or 'User'}</b> | <code>{u.telegram_id}</code>{b} — 🔍 {sc}\n"
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:stats:p:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="Далі ▶️", callback_data=f"admin:stats:p:{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Оновити", callback_data=f"admin:stats:p:{page}")])
    rows.append([InlineKeyboardButton(text="◀️ Меню", callback_data="admin:back")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

async def broadcast_tag_start(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in settings.admin_ids:
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_broadcast_tag)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Всім", callback_data="btag:all")],
        [InlineKeyboardButton(text="⭐ Тільки Premium", callback_data="btag:premium")],
        [InlineKeyboardButton(text="👤 Тільки безкоштовним", callback_data="btag:free")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])
    await callback.message.edit_text(
        "📢 <b>Розсилка з тегами</b>\n\nОбери кому відправити:",
        parse_mode="HTML", reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("btag:"))
async def broadcast_tag_select(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":")[1]
    await state.update_data(broadcast_target=target)
    await state.set_state(AdminStates.waiting_broadcast_message)
    target_names = {"all": "всіх", "premium": "Premium юзерів", "free": "безкоштовних"}
    await callback.message.edit_text(
        f"✍️ Напиши текст оголошення для <b>{target_names.get(target, 'всіх')}</b>.\n\n"
        f"Можна використовувати HTML: <b>жирний</b>, <i>курсив</i>, <u>підкреслений</u>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AdminStates.waiting_broadcast_message)
async def broadcast_tag_send(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    data = await state.get_data()
    target = data.get("broadcast_target", "all")
    await state.clear()

    async with async_session_maker() as session:
        all_users = await UserRepository(session).get_all_active()

    if target == "premium":
        users = [u for u in all_users if u.premium_status]
    elif target == "free":
        users = [u for u in all_users if not u.premium_status]
    else:
        users = all_users

    progress_msg = await message.answer(f"📤 Відправляю... 0/{len(users)}")

    sent = 0
    failed = 0
    batch_size = 10

    for i, user in enumerate(users):
        try:
            tag = f'<a href="tg://user?id={user.telegram_id}">{user.first_name or "Користувач"}</a>'
            text = (
                f"📢 <b>Оголошення від адміністрації</b>\n\n"
                f"👋 {tag}, є новини!\n\n"
                f"{message.text or message.caption or ''}\n\n"
                f"🤖 @{(await message.bot.get_me()).username}"
            )
            await message.bot.send_message(
                user.telegram_id, text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            sent += 1
        except Exception:
            failed += 1

        if (i + 1) % batch_size == 0:
            try:
                await progress_msg.edit_text(f"📤 Відправляю... {i+1}/{len(users)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await progress_msg.edit_text(
        f"✅ <b>Розсилка завершена!</b>\n\n"
        f"📨 Відправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>\n"
        f"👥 Всього: <b>{len(users)}</b>",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin:send_features")
async def send_features(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌", show_alert=True)
        return

    async with async_session_maker() as session:
        all_users = await UserRepository(session).get_all_active()

    free_text = (
        "🎮 <b>Що нового в боті!</b>\n\n"
        "👤 <b>Безкоштовно:</b>\n"
        "🔍 Пошук ігор по опису\n"
        "🕵️ Детектив-режим (бот ставить питання)\n"
        "❤️ Обране — зберігай ігри\n"
        "🕐 Історія пошуків\n"
        "👥 Запроси друга — отримай більше пошуків\n\n"
        "⭐ <b>Premium можливості:</b>\n"
        "🖼️ Пошук по скріншоту\n"
        "🤖 AI Чат — безліміт\n"
        "♾️ Необмежений пошук\n"
        "🥇 Пріоритетна підтримка\n\n"
        "💎 Купи Premium: натисни ⭐ Premium в меню!"
    )

    premium_text = (
        "⭐ <b>Дякуємо що ти Premium!</b>\n\n"
        "🎁 Твої ексклюзивні можливості:\n"
        "🖼️ Пошук по скріншоту гри\n"
        "🤖 AI Чат без обмежень\n"
        "♾️ Необмежений пошук ігор\n"
        "🥇 Пріоритетна підтримка\n\n"
        "🆕 <b>Скоро нові функції тільки для Premium!</b>"
    )

    sent = 0
    for user in all_users:
        try:
            text = premium_text if user.premium_status else free_text
            await callback.bot.send_message(
                user.telegram_id, text, parse_mode="HTML"
            )
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)

    await callback.answer(f"✅ Відправлено {sent} юзерам!", show_alert=True)


@router.callback_query(F.data == "admin:banlist")
async def admin_banlist(callback: CallbackQuery):
    await _show_banlist_page(callback, 0)

@router.callback_query(F.data.startswith("admin:banlist:p:"))
async def admin_banlist_paged(callback: CallbackQuery):
    await _show_banlist_page(callback, int(callback.data.split(":")[3]))

async def _show_banlist_page(callback: CallbackQuery, page: int):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return
    from sqlalchemy import select
    from bot.models import User
    per = 15
    async with async_session_maker() as session:
        res = await session.execute(select(User).where(User.is_banned == True))
        banned = list(res.scalars().all())
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Меню", callback_data="admin:back")]])
    if not banned:
        try:
            await callback.message.edit_text("✅ <b>Банлист порожній</b>", parse_mode="HTML", reply_markup=back_kb)
        except Exception:
            await callback.message.answer("✅ Банлист порожній.", reply_markup=back_kb)
        await callback.answer()
        return
    total = len(banned)
    pages = (total + per - 1) // per
    page = max(0, min(page, pages - 1))
    chunk = banned[page*per:(page+1)*per]
    text = f"🚫 <b>Банлист ({total})</b> — {page+1}/{pages}\n\n"
    for u in chunk:
        nm = u.first_name or u.username or "User"
        text += f"🚫 <b>{nm}</b> | <code>{u.telegram_id}</code>\n"
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin:banlist:p:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin:banlist:p:{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Меню", callback_data="admin:back")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()
