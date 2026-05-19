import logging
import json
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.engine import get_redis

logger = logging.getLogger(__name__)

SKIP_CALLBACKS = ["sub:check", "sub:"]
SKIP_COMMANDS = ["/start"]

SUB_TEXTS = {
    "ua": {
        "title": "📢 <b>Для використання бота підпишись на канали:</b>",
        "after": "Після підписки натисни кнопку нижче ✅",
        "btn": "✅ Я підписався!",
        "not_sub": "❌ Ти ще не підписався на всі канали!",
        "success": "✅ Дякуємо! Доступ відкрито!",
        "ok": "✅ Все добре!",
    },
    "ru": {
        "title": "📢 <b>Для использования бота подпишись на каналы:</b>",
        "after": "После подписки нажми кнопку ниже ✅",
        "btn": "✅ Я подписался!",
        "not_sub": "❌ Ты ещё не подписался на все каналы!",
        "success": "✅ Спасибо! Доступ открыт!",
        "ok": "✅ Всё хорошо!",
    },
    "en": {
        "title": "📢 <b>To use the bot, subscribe to the channels:</b>",
        "after": "After subscribing, press the button below ✅",
        "btn": "✅ I subscribed!",
        "not_sub": "❌ You haven't subscribed to all channels yet!",
        "success": "✅ Thank you! Access granted!",
        "ok": "✅ All good!",
    },
}

async def get_required_channels() -> list:
    try:
        r = await get_redis()
        if not r:
            return []
        data = await r.get("required_channels")
        if not data:
            return []
        return json.loads(data)
    except Exception:
        return []

async def get_user_lang(user_id: int) -> str:
    try:
        from bot.database import async_session_maker
        from bot.repositories import UserRepository
        async with async_session_maker() as session:
            user = await UserRepository(session).get_by_telegram_id(user_id)
            return user.language if user else "en"
    except Exception:
        return "en"

async def check_user_subscribed(bot, user_id: int, channels: list) -> list:
    not_subscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["id"], user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subscribed.append(ch)
        except Exception as e:
            logger.error(f"Sub check error {ch}: {e}")
    return not_subscribed

def build_sub_keyboard(channels: list, lang: str = "en") -> InlineKeyboardMarkup:
    t = SUB_TEXTS.get(lang, SUB_TEXTS["en"])
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(
            text=f"📢 {ch.get('title', ch['id'])}",
            url=ch.get("invite_link", f"https://t.me/{ch['id'].lstrip('@')}")
        )])
    buttons.append([InlineKeyboardButton(
        text=t["btn"],
        callback_data="sub:check"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_sub_text(channels: list, lang: str = "en") -> str:
    t = SUB_TEXTS.get(lang, SUB_TEXTS["en"])
    ch_list = "\n".join(f"• <b>{ch.get('title', ch['id'])}</b>" for ch in channels)
    return f"{t['title']}\n\n{ch_list}\n\n{t['after']}"

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        channels = await get_required_channels()
        if not channels:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if event.data and any(event.data.startswith(s) for s in SKIP_CALLBACKS):
                return await handler(event, data)
            user_id = event.from_user.id
            bot = event.bot
            lang = await get_user_lang(user_id)
            async def send_sub(text, kb):
                try:
                    await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
                except Exception:
                    await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
                await event.answer()

        elif isinstance(event, Message):
            if event.text and any(event.text.startswith(c) for c in SKIP_COMMANDS):
                return await handler(event, data)
            user_id = event.from_user.id
            bot = event.bot
            lang = await get_user_lang(user_id)
            async def send_sub(text, kb):
                await event.answer(text, parse_mode="HTML", reply_markup=kb)
        else:
            return await handler(event, data)

        not_sub = await check_user_subscribed(bot, user_id, channels)
        if not not_sub:
            return await handler(event, data)

        await send_sub(build_sub_text(not_sub, lang), build_sub_keyboard(not_sub, lang))
