"""
search.py — Детектив-пошук з Gemini + RAWG + Steam.
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, SearchHistoryRepository, FavoriteRepository
from bot.services import search_games, format_game_card
from bot.services.ai_service import detective_analyze, search_steam
from bot.locales import t
from bot.keyboards import back_keyboard, game_result_keyboard, main_menu_keyboard
from bot.states import SearchStates

logger = logging.getLogger(__name__)
router = Router()

MAX_CLARIFICATION_ROUNDS = 5

ALL_BACK_TEXTS = [
    "← Back", "← Назад", "← Назад",
    "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню",
]

THINKING = {
    "ua": "🕵️ Думаю... аналізую підказки...",
    "ru": "🕵️ Думаю... анализирую подсказки...",
    "en": "🕵️ Thinking... analyzing clues...",
}


async def get_user_lang(telegram_id: int) -> str:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user.language if user else "en"


async def send_to_main_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    is_admin = user_id in settings.admin_ids
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(user_id)
        lang = user.language if user else "en"
    await message.answer(
        t("main_menu", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=is_admin),
        parse_mode="HTML",
    )


# ── Вхід у пошук ──

@router.message(F.text.in_(["🔍 Find a Game", "🔍 Найти игру", "🔍 Знайти гру"]))
async def search_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        can_search = await user_repo.can_search(message.from_user.id, settings.free_daily_searches)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

    if not can_search and not (user and user.premium_status):
        await message.answer(
            t("search_limit_reached", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in settings.admin_ids),
            parse_mode="HTML",
        )
        return

    if not (user and user.premium_status):
        searches_used = user.daily_search_count if user else 0
        remaining = max(0, settings.free_daily_searches - searches_used)
        await message.answer(t("searches_left", lang, count=remaining), parse_mode="HTML")

    await state.set_state(SearchStates.waiting_for_description)
    await message.answer(
        t("search_prompt", lang),
        reply_markup=back_keyboard(lang),
        parse_mode="HTML",
    )


# ── Перший опис ──

@router.message(SearchStates.waiting_for_description)
async def process_search(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    if message.text in ALL_BACK_TEXTS or message.text in [t("btn_back", lang), t("btn_main_menu", lang)]:
        await send_to_main_menu(message, state)
        return

    query = message.text.strip()
    if len(query) < 3:
        await message.answer("✍️ Напиши хоча б 3 символи." if lang == "ua" else "✍️ Please write at least 3 characters.")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        is_premium = user and user.premium_status
        can_search = is_premium or await user_repo.can_search(message.from_user.id, settings.free_daily_searches)

        if not can_search:
            await message.answer(
                t("search_limit_reached", lang),
                reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in settings.admin_ids),
                parse_mode="HTML",
            )
            await state.clear()
            return

        if not is_premium:
            await user_repo.increment_search_count(message.from_user.id)

    thinking_msg = await message.answer(THINKING.get(lang, THINKING["en"]))
    history = [{"role": "user", "content": query}]
    ai_result = await detective_analyze(history, lang)
    await thinking_msg.delete()

    if ai_result.get("clarification_needed") and ai_result.get("detective_message"):
        history.append({"role": "assistant", "content": ai_result["detective_message"]})
        await state.update_data(
            original_query=query,
            conversation_history=history,
            clarification_round=1,
        )
        await state.set_state(SearchStates.clarifying)
        await message.answer(
            f"🕵️ {ai_result['detective_message']}",
            reply_markup=back_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        await _do_search(message, state, ai_result, query, lang)


# ── Відповідь на уточнення (цикл) ──

@router.message(SearchStates.clarifying)
async def process_clarification(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    if message.text in ALL_BACK_TEXTS or message.text in [t("btn_back", lang), t("btn_main_menu", lang)]:
        await send_to_main_menu(message, state)
        return

    data = await state.get_data()
    history: list = data.get("conversation_history", [])
    original_query: str = data.get("original_query", message.text)
    round_num: int = data.get("clarification_round", 1)

    history.append({"role": "user", "content": message.text.strip()})

    thinking_msg = await message.answer(THINKING.get(lang, THINKING["en"]))
    ai_result = await detective_analyze(history, lang)
    await thinking_msg.delete()

    if ai_result.get("clarification_needed") and round_num < MAX_CLARIFICATION_ROUNDS:
        history.append({"role": "assistant", "content": ai_result.get("detective_message", "")})
        await state.update_data(
            conversation_history=history,
            clarification_round=round_num + 1,
        )
        await message.answer(
            f"🕵️ {ai_result['detective_message']}",
            reply_markup=back_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        if ai_result.get("detective_message") and not ai_result.get("clarification_needed"):
            await message.answer(f"🎯 {ai_result['detective_message']}", parse_mode="HTML")
        await _do_search(message, state, ai_result, original_query, lang)


# ── Фінальний пошук ──

async def _do_search(message: Message, state: FSMContext, ai_result: dict, original_query: str, lang: str):
    searching_msg = await message.answer(t("search_searching", lang))

    keywords = ai_result.get("keywords", []) or [original_query]
    genres = ai_result.get("genres", [])
    game_name = ai_result.get("game_name", "")
    platform = ai_result.get("platform", "").lower()

    # RAWG пошук
    games = await search_games(keywords, genres, page=1)
    if not games and keywords:
        games = await search_games([keywords[0]], [], page=1)
    if not games:
        games = await search_games([original_query], [], page=1)

    # Steam пошук — додаємо якщо PC або невідома платформа
    steam_games = []
    if game_name and platform not in ("mobile", "android", "ios"):
        steam_games = await search_steam(game_name)

    # Об'єднуємо: RAWG першими, Steam додатково
    all_games = games + [g for g in steam_games if g["name"] not in {x["name"] for x in games}]

    await searching_msg.delete()

    if not all_games:
        await message.answer(
            t("search_no_results", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in settings.admin_ids),
            parse_mode="HTML",
        )
        await state.clear()
        return

    await _show_games(message, state, all_games, lang, original_query, keywords, genres)


async def _show_games(message: Message, state: FSMContext, games: list, lang: str, query: str, keywords: list, genres: list):
    await state.update_data(query=query, keywords=keywords, genres=genres, current_page=1)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        history_repo = SearchHistoryRepository(session)
        await history_repo.add(
            user_id=user.id,
            search_query=query,
            result_game=games[0]["name"] if games else None,
        )

    await state.set_state(SearchStates.showing_results)

    for game in games[:5]:
        # Steam ігри мають своє форматування
        source = game.get("source", "")
        if source.startswith("Steam"):
            card_text = (
                f"🎮 *{game['name']}*\n"
                f"🖥️ Платформа: PC (Steam)\n"
                f"🔗 [Відкрити в Steam]({game.get('url', '')})"
            )
            if game.get("background_image"):
                try:
                    await message.answer_photo(
                        photo=game["background_image"],
                        caption=card_text,
                        parse_mode="Markdown",
                    )
                    continue
                except Exception:
                    pass
            await message.answer(card_text, parse_mode="Markdown")
            continue

        card_text = format_game_card(game, lang)
        async with async_session_maker() as session:
            user_repo = UserRepository(session)
            fav_repo = FavoriteRepository(session)
            user = await user_repo.get_by_telegram_id(message.from_user.id)
            is_fav = await fav_repo.is_favorite(user.id, game["id"])

        keyboard = game_result_keyboard(
            game_id=game["id"],
            game_name=game["name"],
            language=lang,
            is_favorite=is_fav,
            page=1,
        )

        if game.get("background_image"):
            try:
                await message.answer_photo(
                    photo=game["background_image"],
                    caption=card_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
                continue
            except Exception:
                pass
        await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")


# ── Колбеки ──

@router.callback_query(F.data == "search:again")
async def search_again(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    await state.set_state(SearchStates.waiting_for_description)
    await callback.message.answer(t("search_prompt", lang), reply_markup=back_keyboard(lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("search:more:"))
async def search_more(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)
    page = int(callback.data.split(":")[2])
    data = await state.get_data()
    keywords = data.get("keywords", [])
    genres = data.get("genres", [])
    if not keywords:
        await callback.answer("Please search again.")
        return
    await callback.answer("Loading..." if lang == "en" else "Завантажую...")
    games = await search_games(keywords, genres, page=page)
    if not games:
        await callback.message.answer(t("search_no_results", lang))
        return
    await state.update_data(current_page=page)
    for game in games[:5]:
        card_text = format_game_card(game, lang)
        async with async_session_maker() as session:
            user_repo = UserRepository(session)
            fav_repo = FavoriteRepository(session)
            user = await user_repo.get_by_telegram_id(callback.from_user.id)
            is_fav = await fav_repo.is_favorite(user.id, game["id"])
        keyboard = game_result_keyboard(game_id=game["id"], game_name=game["name"], language=lang, is_favorite=is_fav, page=page)
        if game.get("background_image"):
            try:
                await callback.message.answer_photo(photo=game["background_image"], caption=card_text, reply_markup=keyboard, parse_mode="Markdown")
                continue
            except Exception:
                pass
        await callback.message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("fav:") & ~F.data.startswith("fav:view:"))
async def add_to_favorites(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    game_id, game_name = parts[1], parts[2]
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        fav_repo = FavoriteRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if await fav_repo.is_favorite(user.id, game_id):
            await callback.answer(t("already_in_favorites", lang), show_alert=False)
            return
        await fav_repo.add(user_id=user.id, game_id=game_id, game_name=game_name, game_data={"id": game_id, "name": game_name})
    await callback.answer(t("added_to_favorites", lang), show_alert=False)


@router.callback_query(F.data.startswith("unfav:"))
async def remove_from_favorites(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    game_id = callback.data.split(":")[1]
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        fav_repo = FavoriteRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if user:
            await fav_repo.remove(user.id, game_id)
    await callback.answer(t("removed_from_favorites", lang), show_alert=False)
