import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, PaymentRepository, SupportRepository
from bot.keyboards import admin_main_keyboard, admin_payment_keyboard, admin_support_ticket_keyboard
from bot.states import AdminStates

logger = logging.getLogger(__name__)
router = Router()


def is_admin(telegram_id: int) -> bool:
    return telegram_id in settings.admin_ids


async def _get_bot_status() -> tuple[bool, str]:
    """Повертає (is_disabled, reason)."""
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


@router.message(Command("admin"))
@router.message(F.text == "🔧 Admin Panel")
async def admin_panel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🔧 <b>Admin Panel</b>\n\nWelcome, Admin!",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )


# ── Статистика ──

@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
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
        f"⭐ <b>Premium користувачів:</b> {premium_users}\n"
        f"🔍 <b>Всього пошуків:</b> {total_searches}\n"
    )

    await callback.message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())
    await callback.answer()


# ── Платежі ──

@router.callback_query(F.data == "admin:payments")
async def admin_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        pending = await pay_repo.get_pending()

    if not pending:
        await callback.message.answer("✅ Немає платежів на перевірку.")
        await callback.answer()
        return

    for payment in pending:
        text = (
            f"💳 <b>Платіж #{payment.id}</b>\n"
            f"User ID: {payment.user_id}\n"
            f"Тариф: {payment.tariff}\n"
            f"Сума: {payment.amount}\n"
            f"Метод: {payment.payment_method}\n"
            f"Дата: {payment.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        if payment.screenshot_file_id:
            await callback.message.bot.send_photo(
                callback.from_user.id,
                photo=payment.screenshot_file_id,
                caption=text,
                reply_markup=admin_payment_keyboard(payment.id),
                parse_mode="HTML",
            )
        else:
            await callback.message.answer(
                text,
                reply_markup=admin_payment_keyboard(payment.id),
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:pay:approve:"))
async def admin_approve_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        user_repo = UserRepository(session)
        payment = await pay_repo.get_by_id(payment_id)

        if not payment:
            await callback.answer("Payment not found.", show_alert=True)
            return

        days_map = {"7": 7, "30": 30, "90": 90, "forever": None}
        days = days_map.get(str(payment.tariff), 30)

        user = await user_repo.get_by_id(payment.user_telegram_id)
        if user:
            await user_repo.set_premium(user.telegram_id, days=days)

        await pay_repo.update_status(payment_id, "approved")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Платіж #{payment_id} підтверджено!")
    await callback.answer("✅ Approved!")


@router.callback_query(F.data.startswith("admin:pay:reject:"))
async def admin_reject_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        await pay_repo.update_status(payment_id, "rejected")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Платіж #{payment_id} відхилено.")
    await callback.answer("❌ Rejected!")


# ── Broadcast ──

@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer("📢 Напиши повідомлення для розсилки:")
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    sending_msg = await message.answer("📢 Надсилаю розсилку...")

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

    await sending_msg.delete()
    await message.answer(
        f"✅ <b>Розсилка завершена!</b>\n\n"
        f"📨 Надіслано: {sent}\n"
        f"❌ Помилок: {failed}\n"
        f"👥 Всього: {sent + failed}",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


# ── Give Premium ──

@router.callback_query(F.data == "admin:give_premium")
async def admin_give_premium_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="give_premium")
    await callback.message.answer("👤 Введи Telegram ID користувача:")
    await callback.answer()


# ── Remove Premium ──

@router.callback_query(F.data == "admin:remove_premium")
async def admin_remove_premium_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="remove_premium")
    await callback.message.answer("👤 Введи Telegram ID користувача для видалення Premium:")
    await callback.answer()


# ── Ban/Unban ──

@router.callback_query(F.data == "admin:ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="ban")
    await callback.message.answer("👤 Введи Telegram ID для бану:")
    await callback.answer()


@router.callback_query(F.data == "admin:unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="unban")
    await callback.message.answer("👤 Введи Telegram ID для розбану:")
    await callback.answer()


# ── Support ──

@router.callback_query(F.data == "admin:support")
async def admin_support(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    async with async_session_maker() as session:
        support_repo = SupportRepository(session)
        tickets = await support_repo.get_open_tickets()

    if not tickets:
        await callback.message.answer("✅ Немає відкритих тікетів.")
        await callback.answer()
        return

    for ticket in tickets[:10]:
        text = (
            f"📨 <b>Тікет #{ticket.id}</b>\n"
            f"Від: {ticket.user_id}\n\n"
            f"{ticket.message}"
        )
        await callback.message.answer(
            text,
            reply_markup=admin_support_ticket_keyboard(ticket.id, ticket.user_id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:support:reply:"))
async def admin_support_reply_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    parts = callback.data.split(":")
    ticket_id = int(parts[3])
    user_tid = int(parts[4])

    await state.set_state(AdminStates.waiting_for_support_reply)
    await state.update_data(ticket_id=ticket_id, user_telegram_id=user_tid)
    await callback.message.answer(f"📝 Напиши відповідь на тікет #{ticket_id}:")
    await callback.answer()


@router.message(AdminStates.waiting_for_support_reply)
async def admin_support_reply_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    user_tid = data.get("user_telegram_id")

    try:
        await message.bot.send_message(
            user_tid,
            f"📩 <b>Відповідь підтримки:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer(f"✅ Відповідь надіслано на тікет #{ticket_id}!")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

    await state.clear()


@router.callback_query(F.data.startswith("admin:support:close:"))
async def admin_support_close(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[3])
    async with async_session_maker() as session:
        await SupportRepository(session).close_ticket(ticket_id)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Тікет #{ticket_id} закрито.")
    await callback.answer()


# ── Users list ──

@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    async with async_session_maker() as session:
        users = await UserRepository(session).get_all_users()

    text = f"👥 <b>Користувачі ({len(users)})</b>\n\n"
    for user in users[:20]:
        premium = "⭐" if user.premium_status else "👤"
        banned = " 🚫" if user.is_banned else ""
        text += f"{premium} {user.first_name or 'User'} | ID: <code>{user.telegram_id}</code>{banned}\n"

    if len(users) > 20:
        text += f"\n<i>...та ще {len(users) - 20} користувачів</i>"

    await callback.message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())
    await callback.answer()


# ── Обробка ID ──

@router.message(AdminStates.waiting_for_user_id)
async def admin_user_id_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Невірний ID. Введи число.")
        return

    data = await state.get_data()
    action = data.get("action")

    if action == "give_premium":
        await state.update_data(target_id=target_id)
        await state.set_state(AdminStates.waiting_for_premium_days)
        await message.answer("📅 Введи кількість днів (0 = назавжди):")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(target_id)

        if not user:
            await message.answer("❌ Користувача не знайдено.")
            await state.clear()
            return

        if action == "ban":
            await user_repo.ban_user(target_id)
            await message.answer(f"🚫 Користувача {target_id} заблоковано.")
            try:
                await message.bot.send_message(target_id, "🚫 Тебе заблоковано в боті.")
            except Exception:
                pass

        elif action == "unban":
            await user_repo.unban_user(target_id)
            await message.answer(f"✅ Користувача {target_id} розблоковано.")
            try:
                await message.bot.send_message(target_id, "✅ Тебе розблоковано! Можеш користуватись ботом.")
            except Exception:
                pass

        elif action == "remove_premium":
            await user_repo.remove_premium(target_id)
            await message.answer(f"❌ Premium видалено у користувача {target_id}.")
            # Надсилаємо сповіщення юзеру
            try:
                await message.bot.send_message(
                    target_id,
                    "ℹ️ Твій Premium статус було видалено адміністратором.",
                )
            except Exception:
                pass

    await state.clear()
    await message.answer("✅ Готово!", reply_markup=admin_main_keyboard())


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

    async with async_session_maker() as session:
        await UserRepository(session).set_premium(target_id, days=days if days > 0 else None)

    days_text = f"{days} днів" if days > 0 else "Назавжди"
    await message.answer(
        f"⭐ Premium видано користувачу {target_id} на {days_text}!",
        reply_markup=admin_main_keyboard(),
    )

    try:
        await message.bot.send_message(
            target_id,
            f"🎉 Тобі видано Premium на {days_text} від адміна!\n\n"
            f"✨ Тепер доступні всі функції бота.",
        )
    except Exception:
        pass

    await state.clear()
