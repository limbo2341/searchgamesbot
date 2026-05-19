import logging
import json
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.config import settings
from bot.database.engine import get_redis
from bot.middlewares.subscription_middleware import (
    get_required_channels, check_user_subscribed,
    build_sub_keyboard, build_sub_text, get_user_lang, SUB_TEXTS
)

logger = logging.getLogger(__name__)
router = Router()

class ChannelStates(StatesGroup):
    waiting_channel_link = State()

async def save_channels(channels: list):
    r = await get_redis()
    if r:
        await r.set("required_channels", json.dumps(channels))

@router.callback_query(F.data == "sub:check")
async def check_subscription(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    t = SUB_TEXTS.get(lang, SUB_TEXTS["en"])
    channels = await get_required_channels()

    if not channels:
        await callback.answer(t["ok"], show_alert=False)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    not_sub = await check_user_subscribed(callback.bot, callback.from_user.id, channels)

    if not not_sub:
        await callback.answer(t["success"], show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        await callback.answer(t["not_sub"], show_alert=True)
        try:
            await callback.message.edit_text(
                build_sub_text(not_sub, lang),
                parse_mode="HTML",
                reply_markup=build_sub_keyboard(not_sub, lang)
            )
        except Exception:
            pass

@router.callback_query(F.data == "admin:channels")
async def admin_channels_menu(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌", show_alert=True)
        return
    channels = await get_required_channels()
    text = "📺 <b>Канали для обов'язкової підписки</b>\n\n"
    if channels:
        text += "Поточні канали:\n"
        for i, ch in enumerate(channels, 1):
            text += f"{i}. <b>{ch.get('title', ch['id'])}</b>\n"
    else:
        text += "⚪ Каналів немає — підписка не обов'язкова.\nКористувачі мають повний доступ."

    buttons = [[InlineKeyboardButton(text="➕ Додати канал", callback_data="admin:channel:add")]]
    if channels:
        for ch in channels:
            buttons.append([InlineKeyboardButton(
                text=f"🗑 Видалити {ch.get('title', ch['id'])}",
                callback_data=f"admin:channel:del:{ch['id'].lstrip('@')}"
            )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data == "admin:channel:add")
async def admin_channel_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌", show_alert=True)
        return
    await state.set_state(ChannelStates.waiting_channel_link)
    await callback.message.edit_text(
        "➕ <b>Додати канал</b>\n\n"
        "Надішли username або посилання на канал.\n\n"
        "Приклад:\n"
        "• <code>@mychannel</code>\n"
        "• <code>https://t.me/mychannel</code>\n\n"
        "⚠️ <b>Важливо:</b> Бот має бути адміністратором каналу!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="admin:channels")]
        ])
    )
    await callback.answer()

@router.message(ChannelStates.waiting_channel_link)
async def admin_channel_save(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    await state.clear()

    raw = message.text.strip()
    if raw.startswith("https://t.me/"):
        channel_id = "@" + raw.replace("https://t.me/", "").strip("/")
    elif not raw.startswith("@") and not raw.startswith("-"):
        channel_id = "@" + raw
    else:
        channel_id = raw

    try:
        chat = await message.bot.get_chat(channel_id)
        invite_link = chat.invite_link or f"https://t.me/{channel_id.lstrip('@')}"

        channels = await get_required_channels()
        for ch in channels:
            if ch["id"] == channel_id:
                await message.answer("⚠️ Цей канал вже додано!")
                return

        channels.append({
            "id": channel_id,
            "title": chat.title or channel_id,
            "invite_link": invite_link
        })
        await save_channels(channels)

        await message.answer(
            f"✅ Канал <b>{chat.title}</b> успішно додано!\n\n"
            f"Тепер всі користувачі повинні підписатись на нього для використання бота.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(
            f"❌ Помилка додавання каналу.\n\n"
            f"Перевір:\n"
            f"• Бот є адміністратором каналу\n"
            f"• Посилання/username правильне\n\n"
            f"Деталі: <code>{e}</code>",
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("admin:channel:del:"))
async def admin_channel_delete(callback: CallbackQuery):
    if callback.from_user.id not in settings.admin_ids:
        await callback.answer("❌", show_alert=True)
        return

    channel_username = "@" + callback.data.replace("admin:channel:del:", "")
    channels = await get_required_channels()
    channels = [ch for ch in channels if ch["id"] != channel_username]
    await save_channels(channels)

    await callback.answer("✅ Канал видалено!", show_alert=True)
    await admin_channels_menu(callback)
