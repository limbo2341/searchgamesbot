"""
screenshot.py — Пошук гри по скріншоту (тільки Premium).
Використовує Groq через OpenRouter vision для аналізу зображення.
"""

import logging
import aiohttp
import json
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, FavoriteRepository
from bot.services import search_games, format_game_card
from bot.locales import t
from bot.keyboards import back_keyboard, game_result_keyboard, main_menu_keyboard
from bot.states import SearchStates

logger = logging.getLogger(__name__)
router = Router()

ALL_BACK = ["← Back", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def get_user_lang(telegram_id: int) -> str:
    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        return user.language if user else "en"


async def analyze_screenshot_with_vision(image_url: str, caption: str, lang: str) -> dict:
    """Аналізує скріншот через OpenRouter vision (безкоштовна модель)."""
    lang_names = {"en": "English", "ru": "Russian", "ua": "Ukrainian"}
    lang_name = lang_names.get(lang, "English")

    system_prompt = f"""You are a game recognition expert. Look at this game screenshot carefully.
Identify what game this is and extract search keywords.
User language: {lang_name}.
Respond ONLY in JSON:
{{"possible_game": "Game name", "keywords": ["kw1", "kw2"], "genres": ["genre"], "confidence": 0.85, "clarification_needed": false}}"""

    # Використовуємо безкоштовну vision модель через OpenRouter
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
    }
    payload = {
        "model": "google/gemini-flash-1.5",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": caption or "What game is this?"},
                ],
            },
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OPENROUTER_URL, headers=headers, json=payload,
                              timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    text = await r.text()
                    logger.error(f"Vision error {r.status}: {text[:200]}")
                    return {"keywords": [], "confidence": 0.3, "clarification_needed": True, "possible_game": ""}
                data = await r.json()
                raw = data["choices"][0]["message"]["content"]
                clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                return json.loads(clean)
    except Exception as e:
        logger.error(f"Screenshot analysis failed: {e}")
        return {"keywords": [], "confidence": 0.3, "clarification_needed": True, "possible_game": ""}


@router.message(F.text.in_(["🖼️ Пошук по фото", "🖼️ Поиск по фото", "🖼️ Search by Photo"]))
async def screenshot_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)
    is_admin = message.from_user.id in settings.admin_ids

    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(message.from_user.id)

    is_premium = user and user.premium_status

    if not is_premium and not is_admin:
        await message.answer(
            t("screenshot_premium_only", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=False),
            parse_mode="HTML",
        )
        return

    await state.set_state(SearchStates.waiting_for_screenshot)
    await message.answer(
        t("screenshot_prompt", lang),
        reply_markup=back_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(F.photo)
async def handle_screenshot(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)
    is_admin = message.from_user.id in settings.admin_ids

    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(message.from_user.id)

    is_premium = user and user.premium_status

    if not is_premium and not is_admin:
        await message.answer(
            t("screenshot_premium_only", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=False),
            parse_mode="HTML",
        )
        return

    analyzing_msg = await message.answer(t("screenshot_analyzing", lang))

    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"
        caption = message.caption or "game screenshot"

        ai_result = await analyze_screenshot_with_vision(file_url, caption, lang)

        keywords = ai_result.get("keywords", [])
        confidence = ai_result.get("confidence", 0)
        possible_game = ai_result.get("possible_game", "")

        if possible_game:
            keywords = [possible_game] + keywords

        if not keywords or confidence < 0.4:
            await analyzing_msg.delete()
            await message.answer(
                "🤔 Не вдалось розпізнати гру. Спробуй описати її текстом." if lang == "ua"
                else "🤔 Couldn't recognize the game. Try describing it in text.",
                reply_markup=back_keyboard(lang),
            )
            return

        games = await search_games(keywords)
        await analyzing_msg.delete()

        if not games:
            await message.answer(t("search_no_results", lang))
            return

        for game in games[:3]:
            card_text = format_game_card(game, lang)
            async with async_session_maker() as session:
                u = await UserRepository(session).get_by_telegram_id(message.from_user.id)
                is_fav = await FavoriteRepository(session).is_favorite(u.id, game["id"])

            safe_name = game["name"][:25].replace(":", "").strip()
            kb = game_result_keyboard(str(game["id"])[:20], safe_name, lang, is_fav, 1)

            if game.get("background_image"):
                try:
                    await message.answer_photo(
                        photo=game["background_image"], caption=card_text,
                        reply_markup=kb, parse_mode="Markdown",
                    )
                    continue
                except Exception:
                    pass
            await message.answer(card_text, reply_markup=kb, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Screenshot error: {e}", exc_info=True)
        try:
            await analyzing_msg.delete()
        except Exception:
            pass
        await message.answer(t("error_general", lang))
