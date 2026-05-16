import logging
from datetime import datetime, timedelta
from aiogram import Router, F
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

TARIFF_DAYS = {
    "7 days": 7,
    "30 days": 30,
    "90 days": 90,
    "Forever": None,
}


def is_admin(telegram_id: int) -> bool:
    return telegram_id in settings.admin_ids


@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🔧 <b>Admin Panel</b>\n\nWelcome, Admin!",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )


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

    text = (
        "📊 <b>Statistics</b>\n\n"
        f"👥 Total users: <b>{total_users}</b>\n"
        f"⭐ Premium users: <b>{premium_users}</b>\n"
        f"🔍 Total searches: <b>{total_searches}</b>\n"
    )

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:payments")
async def admin_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        pending = await pay_repo.get_pending()

    if not pending:
        await callback.message.answer("✅ No pending payments.")
        await callback.answer()
        return

    for payment in pending:
        text = (
            f"💳 <b>Payment #{payment.id}</b>\n"
            f"User ID: {payment.user_id}\n"
            f"Tariff: {payment.tariff}\n"
            f"Amount: {payment.amount}\n"
            f"Method: {payment.payment_method}\n"
            f"Date: {payment.created_at.strftime('%d.%m.%Y %H:%M')}"
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
async def approve_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        user_repo = UserRepository(session)

        payment = await pay_repo.approve(payment_id, callback.from_user.id)
        if not payment:
            await callback.answer("Payment not found.", show_alert=True)
            return

        user = await user_repo.get_by_id(payment.user_id)
        if not user:
            await callback.answer("User not found.", show_alert=True)
            return

        days = TARIFF_DAYS.get(payment.tariff)
        await user_repo.set_premium(user.telegram_id, days=days)

    if days:
        date_str = (datetime.utcnow() + timedelta(days=days)).strftime("%d.%m.%Y")
    else:
        date_str = "Forever"

    try:
        await callback.bot.send_message(
            user.telegram_id,
            f"🎉 Your payment was approved! Premium is now active until {date_str}!",
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    await callback.message.edit_caption(
        caption=f"✅ Payment #{payment_id} APPROVED by admin",
        parse_mode="HTML",
    )
    await callback.answer("✅ Approved!", show_alert=True)


@router.callback_query(F.data.startswith("admin:pay:reject:"))
async def reject_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    payment_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        user_repo = UserRepository(session)
        payment = await pay_repo.reject(payment_id, callback.from_user.id)
        if not payment:
            await callback.answer("Payment not found.", show_alert=True)
            return
        user = await user_repo.get_by_id(payment.user_id)

    if user:
        try:
            await callback.bot.send_message(
                user.telegram_id,
                "❌ Your payment was rejected. Please contact support.",
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")

    await callback.message.edit_caption(
        caption=f"❌ Payment #{payment_id} REJECTED by admin",
    )
    await callback.answer("❌ Rejected!", show_alert=True)


@router.callback_query(F.data == "admin:support")
async def admin_support(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    async with async_session_maker() as session:
        support_repo = SupportRepository(session)
        tickets = await support_repo.get_open()

    if not tickets:
        await callback.message.answer("✅ No open support tickets.")
        await callback.answer()
        return

    for ticket in tickets:
        text = (
            f"📨 <b>Ticket #{ticket.id}</b>\n"
            f"User ID: {ticket.user_id}\n"
            f"Date: {ticket.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Message:\n{ticket.message}"
        )
        async with async_session_maker() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(ticket.user_id)
        tg_id = user.telegram_id if user else 0

        await callback.message.answer(
            text,
            reply_markup=admin_support_ticket_keyboard(ticket.id, tg_id),
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
    user_telegram_id = int(parts[4])

    await state.set_state(AdminStates.waiting_for_support_reply)
    await state.update_data(ticket_id=ticket_id, user_telegram_id=user_telegram_id)
    await callback.message.answer(f"✍️ Write your reply for ticket #{ticket_id}:")
    await callback.answer()


@router.message(AdminStates.waiting_for_support_reply)
async def admin_support_reply_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    user_telegram_id = data.get("user_telegram_id")

    async with async_session_maker() as session:
        support_repo = SupportRepository(session)
        await support_repo.close(ticket_id, message.text)

    try:
        await message.bot.send_message(
            user_telegram_id,
            f"📩 <b>Support reply:</b>\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer(f"✅ Reply sent for ticket #{ticket_id}!")
    except Exception as e:
        logger.error(f"Failed to send support reply: {e}")
        await message.answer("❌ Failed to send reply.")

    await state.clear()


@router.callback_query(F.data.startswith("admin:support:close:"))
async def admin_support_close(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[3])

    async with async_session_maker() as session:
        support_repo = SupportRepository(session)
        await support_repo.close(ticket_id, "Closed by admin.")

    await callback.message.edit_text(f"✅ Ticket #{ticket_id} closed.")
    await callback.answer("Closed!", show_alert=False)


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer("📢 Write your broadcast message:")
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer("📢 Sending broadcast...")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        users = await user_repo.get_all_users()

    sent = 0
    failed = 0
    for user in users:
        if user.is_banned:
            continue
        try:
            await message.bot.send_message(
                user.telegram_id,
                f"📢 <b>Announcement</b>\n\n{message.text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1

    await message.answer(f"✅ Broadcast done!\nSent: {sent}\nFailed: {failed}")


@router.callback_query(F.data == "admin:give_premium")
async def admin_give_premium_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="give_premium")
    await callback.message.answer("👤 Enter user Telegram ID:")
    await callback.answer()


@router.callback_query(F.data == "admin:ban")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="ban")
    await callback.message.answer("👤 Enter user Telegram ID to ban:")
    await callback.answer()


@router.callback_query(F.data == "admin:unban")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="unban")
    await callback.message.answer("👤 Enter user Telegram ID to unban:")
    await callback.answer()


@router.message(AdminStates.waiting_for_user_id)
async def admin_user_id_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid ID. Enter a number.")
        return

    data = await state.get_data()
    action = data.get("action")

    if action == "give_premium":
        await state.update_data(target_id=target_id)
        await state.set_state(AdminStates.waiting_for_premium_days)
        await message.answer("📅 Enter days (or 0 for forever):")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(target_id)

        if not user:
            await message.answer("❌ User not found.")
            await state.clear()
            return

        if action == "ban":
            await user_repo.ban_user(target_id)
            await message.answer(f"🚫 User {target_id} banned.")
        elif action == "unban":
            await user_repo.unban_user(target_id)
            await message.answer(f"✅ User {target_id} unbanned.")

    await state.clear()


@router.message(AdminStates.waiting_for_premium_days)
async def admin_premium_days_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Invalid number.")
        return

    data = await state.get_data()
    target_id = data.get("target_id")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.set_premium(target_id, days=days if days > 0 else None)

    days_text = f"{days} days" if days > 0 else "Forever"
    await message.answer(f"⭐ Premium given to {target_id} for {days_text}!")

    try:
        await message.bot.send_message(
            target_id,
            f"🎉 You received Premium for {days_text} from admin!",
        )
    except Exception:
        pass

    await state.clear()
