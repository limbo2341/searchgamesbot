import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, PaymentRepository
from bot.locales import t
from bot.keyboards import (
    premium_keyboard, payment_method_keyboard,
    stars_payment_keyboard, main_menu_keyboard, admin_payment_keyboard
)
from bot.states import PaymentStates

logger = logging.getLogger(__name__)
router = Router()

TARIFF_DAYS = {
    "7": 7,
    "30": 30,
    "90": 90,
    "forever": None,
}

TARIFF_UAH = {
    "7": settings.premium_7_days_uah,
    "30": settings.premium_30_days_uah,
    "90": settings.premium_90_days_uah,
    "forever": settings.premium_forever_uah,
}

TARIFF_STARS = {
    "7": settings.premium_7_days_stars,
    "30": settings.premium_30_days_stars,
    "90": settings.premium_90_days_stars,
    "forever": settings.premium_forever_stars,
}

TARIFF_NAMES = {
    "7": "7 days",
    "30": "30 days",
    "90": "90 days",
    "forever": "Forever",
}


async def get_user_lang(telegram_id: int) -> str:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user.language if user else "en"


@router.message(F.text.in_(["⭐ Premium", "⭐ Premium"]))
async def premium_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

    text = t("premium_menu", lang)

    if user and user.premium_status:
        if user.premium_until:
            date_str = user.premium_until.strftime("%d.%m.%Y")
            text = t("premium_active", lang, date=date_str) + "\n\n" + text
        else:
            text = t("premium_active_forever", lang) + "\n\n" + text

    await message.answer(
        text,
        reply_markup=premium_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("premium:"))
async def choose_tariff(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)
    tariff = callback.data.split(":")[1]

    await state.update_data(tariff=tariff)
    await state.set_state(PaymentStates.choosing_method)

    await callback.message.answer(
        t("choose_payment", lang),
        reply_markup=payment_method_keyboard(tariff, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay:card:"))
async def pay_by_card(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)
    tariff = callback.data.split(":")[2]
    amount = TARIFF_UAH.get(tariff, 0)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        pay_repo = PaymentRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)

        payment = await pay_repo.create(
            user_id=user.id,
            tariff=TARIFF_NAMES.get(tariff, tariff),
            amount=amount,
            payment_method="privatbank",
        )

    await state.update_data(payment_id=payment.id, tariff=tariff)
    await state.set_state(PaymentStates.waiting_for_screenshot)

    await callback.message.answer(
        t("payment_card_info", lang, amount=amount, card=settings.privat_card),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PaymentStates.waiting_for_screenshot, F.photo)
async def receive_screenshot(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    payment_id = data.get("payment_id")
    tariff = data.get("tariff", "unknown")

    if not payment_id:
        await message.answer(t("error_general", lang))
        return

    file_id = message.photo[-1].file_id

    async with async_session_maker() as session:
        pay_repo = PaymentRepository(session)
        user_repo = UserRepository(session)
        await pay_repo.update_screenshot(payment_id, file_id)
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        payment = await pay_repo.get_by_id(payment_id)

    user_display = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"
    amount = TARIFF_UAH.get(tariff, 0)

    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_photo(
                admin_id,
                photo=file_id,
                caption=t(
                    "new_payment_admin",
                    "en",
                    user=user_display,
                    tariff=TARIFF_NAMES.get(tariff, tariff),
                    amount=amount,
                    payment_id=payment_id,
                ),
                reply_markup=admin_payment_keyboard(payment_id),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    await state.clear()
    await message.answer(
        t("payment_screenshot_received", lang),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_by_stars(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)
    tariff = callback.data.split(":")[2]
    stars = TARIFF_STARS.get(tariff, 0)
    amount_uah = TARIFF_UAH.get(tariff, 0)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        pay_repo = PaymentRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        payment = await pay_repo.create(
            user_id=user.id,
            tariff=TARIFF_NAMES.get(tariff, tariff),
            amount=stars,
            payment_method="stars",
        )

    await state.update_data(payment_id=payment.id, tariff=tariff)

    await callback.message.answer_invoice(
        title=f"IgroMemory Premium — {TARIFF_NAMES.get(tariff, tariff)}",
        description=f"Premium subscription for {TARIFF_NAMES.get(tariff, tariff)}",
        payload=f"premium:{tariff}:{payment.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Premium", amount=stars)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    payload = message.successful_payment.invoice_payload
    parts = payload.split(":")
    tariff = parts[1] if len(parts) > 1 else "30"
    payment_id = int(parts[2]) if len(parts) > 2 else 0

    days = TARIFF_DAYS.get(tariff)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        pay_repo = PaymentRepository(session)
        await user_repo.set_premium(message.from_user.id, days=days)
        if payment_id:
            await pay_repo.approve(payment_id, 0)

    if days:
        date_str = (datetime.utcnow() + timedelta(days=days)).strftime("%d.%m.%Y")
    else:
        date_str = "Forever"

    await state.clear()
    await message.answer(
        t("payment_approved", lang, date=date_str),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML",
    )
