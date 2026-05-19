import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, SearchHistoryRepository, FavoriteRepository
from bot.services import search_games, format_game_card
from bot.services.ai_service import detective_analyze, search_all_stores
from bot.locales import t
from bot.keyboards import back_keyboard, game_result_keyboard, main_menu_keyboard
from bot.states import SearchStates

logger = logging.getLogger(__name__)
router = Router()
MAX_ROUNDS = 5
ALL_BACK = ["← Back", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]
THINKING = {"ua": "🕵️ Аналізую підказки...", "ru": "🕵️ Анализирую...", "en": "🕵️ Analyzing clues..."}

async def get_lang(tid):
    async with async_session_maker() as s:
        u = await UserRepository(s).get_by_telegram_id(tid)
        return u.language if u else "en"

async def go_main(message, state):
    await state.clear()
    uid = message.from_user.id
    is_admin = uid in settings.admin_ids
    async with async_session_maker() as s:
        u = await UserRepository(s).get_by_telegram_id(uid)
        lang = u.language if u else "en"
        is_premium = u.premium_status if u else False
    await message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=is_premium), parse_mode="HTML")

def _store_card(game, lang):
    src = game.get("source", "")
    name = game.get("name", "")
    rating = game.get("rating", 0)
    dev = game.get("developer", "")
    genres = ", ".join(g for g in game.get("genres", []) if g)
    year = (game.get("released", "") or "")[:4]
    price = game.get("price", "")
    url = game.get("url", "")
    lines = [f"🎮 *{name}*", f"📦 {src}"]
    if rating: lines.append(f"⭐ {rating}/5")
    if dev: lines.append(f"👨‍💻 {dev}")
    if genres: lines.append(f"🎯 {genres}")
    if year: lines.append(f"📅 {year}")
    if price: lines.append(f"💰 {price}")
    if url: lines.append(f"🔗 [{'Відкрити' if lang=='ua' else 'Open'}]({url})")
    return "\n".join(lines)

@router.message(F.text.in_(["🔍 Find a Game", "🔍 Найти игру", "🔍 Знайти гру"]))
async def search_menu(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_lang(message.from_user.id)
    async with async_session_maker() as s:
        repo = UserRepository(s)
        user = await repo.get_by_telegram_id(message.from_user.id)
        can = await repo.can_search(message.from_user.id, settings.free_daily_searches)
    is_premium = user and user.premium_status
    is_admin = message.from_user.id in settings.admin_ids
    if not can and not is_premium and not is_admin:
        await message.answer(t("search_limit_reached", lang), reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=bool(is_premium)), parse_mode="HTML")
        return
    if not is_premium and not is_admin and user:
        remaining = max(0, settings.free_daily_searches - (user.daily_search_count or 0))
        await message.answer(t("searches_left", lang, count=remaining), parse_mode="HTML")
    await state.set_state(SearchStates.waiting_for_description)
    await message.answer(t("search_prompt", lang), reply_markup=back_keyboard(lang), parse_mode="HTML")

@router.message(SearchStates.waiting_for_description)
async def process_search(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    if message.text in ALL_BACK or message.text in [t("btn_back", lang), t("btn_main_menu", lang)]:
        await go_main(message, state)
        return
    query = message.text.strip()
    if len(query) < 3:
        await message.answer("✍️ Мінімум 3 символи.")
        return
    async with async_session_maker() as s:
        repo = UserRepository(s)
        user = await repo.get_by_telegram_id(message.from_user.id)
        is_premium = user and user.premium_status
        is_admin = message.from_user.id in settings.admin_ids
        can = is_premium or is_admin or await repo.can_search(message.from_user.id, settings.free_daily_searches)
        if not can:
            await message.answer(t("search_limit_reached", lang), reply_markup=main_menu_keyboard(lang, is_admin=is_admin, is_premium=bool(is_premium)), parse_mode="HTML")
            await state.clear()
            return
        if not is_premium and not is_admin:
            await repo.increment_search_count(message.from_user.id)
    thinking = await message.answer(THINKING.get(lang, THINKING["en"]))
    history = [{"role": "user", "content": query}]
    ai = await detective_analyze(history, lang)
    await thinking.delete()
    if ai.get("clarification_needed") and ai.get("detective_message"):
        history.append({"role": "assistant", "content": ai["detective_message"]})
        await state.update_data(original_query=query, conversation_history=history, clarification_round=1)
        await state.set_state(SearchStates.clarifying)
        await message.answer(f"🕵️ {ai['detective_message']}", reply_markup=back_keyboard(lang), parse_mode="HTML")
    else:
        await _do_search(message, state, ai, query, lang)

@router.message(SearchStates.clarifying)
async def process_clarification(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    if message.text in ALL_BACK or message.text in [t("btn_back", lang), t("btn_main_menu", lang)]:
        await go_main(message, state)
        return
    data = await state.get_data()
    history = data.get("conversation_history", [])
    original = data.get("original_query", message.text)
    round_n = data.get("clarification_round", 1)
    history.append({"role": "user", "content": message.text.strip()})
    thinking = await message.answer(THINKING.get(lang, THINKING["en"]))
    ai = await detective_analyze(history, lang)
    await thinking.delete()
    if ai.get("clarification_needed") and round_n < MAX_ROUNDS:
        history.append({"role": "assistant", "content": ai.get("detective_message", "")})
        await state.update_data(conversation_history=history, clarification_round=round_n + 1)
        await message.answer(f"🕵️ {ai['detective_message']}", reply_markup=back_keyboard(lang), parse_mode="HTML")
    else:
        if ai.get("detective_message") and not ai.get("clarification_needed"):
            await message.answer(f"🎯 {ai['detective_message']}", parse_mode="HTML")
        await _do_search(message, state, ai, original, lang)

async def _do_search(message, state, ai, original, lang):
    msg = await message.answer(t("search_searching", lang))
    keywords = ai.get("keywords") or [original]
    genres = ai.get("genres", [])
    game_name = ai.get("game_name", "") or (keywords[0] if keywords else original)
    platform = ai.get("platform", "")
    rawg, stores = await asyncio.gather(search_games(keywords, genres, page=1), search_all_stores(game_name, platform), return_exceptions=True)
    if isinstance(rawg, Exception): rawg = []
    if isinstance(stores, Exception): stores = []
    if not rawg and keywords: rawg = await search_games([keywords[0]], [], page=1)
    if not rawg: rawg = await search_games([original], [], page=1)
    seen = set()
    all_games = []
    for g in list(rawg) + list(stores):
        n = g.get("name", "").lower()
        if n not in seen:
            seen.add(n)
            all_games.append(g)
    await msg.delete()
    if not all_games:
        await message.answer(t("search_no_results", lang), reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in settings.admin_ids, is_premium=False), parse_mode="HTML")
        await state.clear()
        return
    await _show_games(message, state, all_games, lang, original, keywords, genres)

async def _show_games(message, state, games, lang, query, keywords, genres):
    await state.update_data(query=query, keywords=keywords, genres=genres, current_page=1)
    async with async_session_maker() as s:
        user = await UserRepository(s).get_by_telegram_id(message.from_user.id)
        await SearchHistoryRepository(s).add(user_id=user.id, search_query=query, result_game=games[0]["name"] if games else None)
    await state.set_state(SearchStates.showing_results)
    for game in games[:1]:
        source = game.get("source", "")
        if source:
            card = _store_card(game, lang)
            img = game.get("background_image", "")
            if img:
                try:
                    await message.answer_photo(photo=img, caption=card, parse_mode="Markdown")
                    continue
                except Exception:
                    pass
            await message.answer(card, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            card = format_game_card(game, lang)
            async with async_session_maker() as s:
                u = await UserRepository(s).get_by_telegram_id(message.from_user.id)
                is_fav = await FavoriteRepository(s).is_favorite(u.id, game["id"])
            safe_name = game["name"][:25].replace(":", "").strip()
            kb = game_result_keyboard(str(game["id"])[:20], safe_name, lang, is_fav, 1)
            if game.get("background_image"):
                try:
                    await message.answer_photo(photo=game["background_image"], caption=card, reply_markup=kb, parse_mode="Markdown")
                    continue
                except Exception:
                    pass
            await message.answer(card, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "search:again")
async def search_again(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await state.clear()
    await state.set_state(SearchStates.waiting_for_description)
    await callback.message.answer(t("search_prompt", lang), reply_markup=back_keyboard(lang), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("search:more:"))
async def search_more(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    page = int(callback.data.split(":")[2])
    data = await state.get_data()
    keywords = data.get("keywords", [])
    if not keywords:
        await callback.answer()
        return
    await callback.answer("Завантажую..." if lang == "ua" else "Loading...")
    games = await search_games(keywords, data.get("genres", []), page=page)
    if not games:
        await callback.message.answer(t("search_no_results", lang))
        return
    await state.update_data(current_page=page)
    for game in games[:5]:
        card = format_game_card(game, lang)
        async with async_session_maker() as s:
            u = await UserRepository(s).get_by_telegram_id(callback.from_user.id)
            is_fav = await FavoriteRepository(s).is_favorite(u.id, game["id"])
        safe_name = game["name"][:25].replace(":", "").strip()
        kb = game_result_keyboard(str(game["id"])[:20], safe_name, lang, is_fav, page)
        if game.get("background_image"):
            try:
                await callback.message.answer_photo(photo=game["background_image"], caption=card, reply_markup=kb, parse_mode="Markdown")
                continue
            except Exception:
                pass
        await callback.message.answer(card, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data.startswith("fav:") & ~F.data.startswith("fav:view:"))
async def add_fav(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    game_id, game_name = parts[1], parts[2]
    async with async_session_maker() as s:
        u = await UserRepository(s).get_by_telegram_id(callback.from_user.id)
        fav = FavoriteRepository(s)
        if not u:
            await callback.answer()
            return
        if await fav.is_favorite(u.id, game_id):
            await callback.answer(t("already_in_favorites", lang))
            return
        await fav.add(user_id=u.id, game_id=game_id, game_name=game_name, game_data={"id": game_id, "name": game_name})
    await callback.answer(t("added_to_favorites", lang))

@router.callback_query(F.data.startswith("unfav:"))
async def remove_fav(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    game_id = callback.data.split(":")[1]
    async with async_session_maker() as s:
        u = await UserRepository(s).get_by_telegram_id(callback.from_user.id)
        if u:
            await FavoriteRepository(s).remove(u.id, game_id)
    await callback.answer(t("removed_from_favorites", lang))
