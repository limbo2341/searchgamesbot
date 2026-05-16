import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository, SearchHistoryRepository, FavoriteRepository
from bot.services import analyze_game_description, search_games, format_game_card
from bot.locales import t
from bot.keyboards import back_keyboard, game_result_keyboard, main_menu_keyboard
from bot.states import SearchStates

logger = logging.getLogger(__name__)
router = Router()

ALL_BACK_TEXTS = ["← Back", "← Назад", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]


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

    searches_used = user.daily_search_count if user else 0
    remaining = max(0, settings.free_daily_searches - searches_used)

    if not (user and user.premium_status):
        info = t("searches_left", lang, count=remaining)
        await message.answer(info, parse_mode="HTML")

    await state.set_state(SearchStates.waiting_for_description)
    await message.answer(
        t("search_prompt", lang),
        reply_markup=back_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(SearchStates.waiting_for_description)
async def process_search(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    if message.text in ALL_BACK_TEXTS or message.text in [t("btn_back", lang), t("btn_main_menu", lang)]:
        await send_to_main_menu(message, state)
        return

    query = message.text.strip()
    if len(query) < 3:
        await message.answer("Please write at least 3 characters.")
        return

    searching_msg = await message.answer(t("search_searching", lang))

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        is_premium = user and user.premium_status
        can_search = is_premium or await user_repo.can_search(message.from_user.id, settings.free_daily_searches)

        if not can_search:
            await searching_msg.delete()
            await message.answer(
                t("search_limit_reached", lang),
                reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in settings.admin_ids),
                parse_mode="HTML",
            )
            await state.clear()
            return

        if not is_premium:
            await user_repo.increment_search_count(message.from_user.id)

    try:
        ai_result = await analyze_game_description(query, lang)
        keywords = ai_result.get("keywords", [query])
        genres = ai_result.get("genres", [])
        possible_game = ai_result.get("description", "")

        # Try direct game name first if AI is confident
        if ai_result.get("confidence", 0) > 0.7 and possible_game:
            keywords = [possible_game] + keywords

        games = await search_games(keywords, genres, page=1)

        # If no results, try with just the raw query
        if not games:
            games = await search_games([query], [], page=1)

        if not games:
            await searching_msg.delete()
            await message.answer(t("search_no_results", lang))
            return

        await state.update_data(
            query=query,
            keywords=keywords,
            genres=genres,
            current_page=1,
        )

        async with async_session_maker() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_telegram_id(message.from_user.id)
            history_repo = SearchHistoryRepository(session)
            await history_repo.add(
                user_id=user.id,
                search_query=query,
                result_game=games[0]["name"] if games else None,
            )

        await searching_msg.delete()
        await state.set_state(SearchStates.showing_results)

        for i, game in enumerate(games[:5], 1):
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
                except Exception:
                    await message.answer(
                        card_text,
                        reply_markup=keyboard,
                        parse_mode="Markdown",
                    )
            else:
                await message.answer(
                    card_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )

    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        try:
            await searching_msg.delete()
        except Exception:
            pass
        await message.answer(t("error_general", lang))


@router.callback_query(F.data == "search:again")
async def search_again(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(SearchStates.waiting_for_description)
    await callback.message.answer(
        t("search_prompt", lang),
        reply_markup=back_keyboard(lang),
        parse_mode="HTML",
    )
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

    await callback.answer("Loading more results...")

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

        keyboard = game_result_keyboard(
            game_id=game["id"],
            game_name=game["name"],
            language=lang,
            is_favorite=is_fav,
            page=page,
        )

        if game.get("background_image"):
            try:
                await callback.message.answer_photo(
                    photo=game["background_image"],
                    caption=card_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            except Exception:
                await callback.message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await callback.message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("fav:") & ~F.data.startswith("fav:view:"))
async def add_to_favorites(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return

    game_id = parts[1]
    game_name = parts[2]

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

        await fav_repo.add(
            user_id=user.id,
            game_id=game_id,
            game_name=game_name,
            game_data={"id": game_id, "name": game_name},
        )

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
