import logging
import base64
import aiohttp
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.database import async_session_maker
from bot.repositories import UserRepository
from bot.services import search_games, format_game_card
from bot.locales import t
from bot.keyboards import back_keyboard, game_result_keyboard, main_menu_keyboard
from bot.states import SearchStates

logger = logging.getLogger(__name__)
router = Router()

ALL_BACK_TEXTS = ["← Back", "← Назад", "← Назад", "🏠 Main Menu", "🏠 Головне меню", "🏠 Главное меню"]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def get_user_lang(telegram_id: int) -> str:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user.language if user else "en"


async def analyze_game_screenshot(image_url: str, caption: str, lang: str) -> dict:
    """Send actual screenshot image to AI for game recognition."""
    lang_names = {"en": "English", "ru": "Russian", "ua": "Ukrainian"}
    lang_name = lang_names.get(lang, "English")

    system_prompt = f"""You are a game recognition expert. Look at this game screenshot carefully.
Identify what game this is and extract search keywords for finding it.
The user may write in {lang_name}.
Respond ONLY in JSON format:
{{
  "possible_game": "Game name if recognized with high confidence",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "genres": ["genre1", "genre2"],
  "confidence": 0.85,
  "clarification_needed": false,
  "clarification_questions": []
}}
If you cannot recognize the game, set confidence below 0.5 and clarification_needed to true."""

    user_caption = caption if caption != "game screenshot" else "What game is this screenshot from?"

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
        "X-Title": "IgroMemory Bot",
    }

    payload = {
        "model": "google/gemini-flash-1.5",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                    {"type": "text", "text": user_caption},
                ],
            },
        ],
        "max_tokens": 500,
        "temperature": 0.3,
    }

    try:
        import json
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"OpenRouter vision error {response.status}: {text}")
                    return {"keywords": [], "confidence": 0.3, "clarification_needed": True, "possible_game": ""}
                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                clean = content.strip().strip("```json").strip("```").strip()
                return json.loads(clean)
    except Exception as e:
        logger.error(f"Screenshot AI analysis failed: {e}")
        return {"keywords": [], "confidence": 0.3, "clarification_needed": True, "possible_game": ""}


@router.message(F.photo)
async def handle_screenshot(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

    if not user or not user.premium_status:
        await message.answer(
            t("screenshot_premium_only", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in settings.admin_ids),
            parse_mode="HTML",
        )
        return

    analyzing_msg = await message.answer(t("screenshot_analyzing", lang))

    try:
        # Get the largest photo
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"

        caption = message.caption or "game screenshot"
        ai_result = await analyze_game_screenshot(file_url, caption, lang)

        keywords = ai_result.get("keywords", [])
        confidence = ai_result.get("confidence", 0)
        clarification_needed = ai_result.get("clarification_needed", False)
        possible_game = ai_result.get("possible_game", "")

        if clarification_needed or confidence < 0.5:
            questions = ai_result.get("clarification_questions", [])
            if questions:
                await analyzing_msg.delete()
                await state.set_state(SearchStates.clarifying)
                await state.update_data(
                    screenshot_keywords=keywords,
                    clarification_answers={},
                    remaining_questions=questions[1:],
                )
                await message.answer(
                    t("screenshot_clarify", lang, question=questions[0]),
                    reply_markup=back_keyboard(lang),
                    parse_mode="HTML",
                )
                return
            elif not keywords:
                await analyzing_msg.delete()
                await message.answer(
                    "🤔 I couldn't recognize the game from this screenshot. Try to describe it in text instead.",
                    reply_markup=back_keyboard(lang),
                )
                return

        if possible_game:
            keywords = [possible_game] + keywords

        games = await search_games(keywords)

        await analyzing_msg.delete()

        if not games:
            await message.answer(t("search_no_results", lang))
            return

        for game in games[:3]:
            card_text = format_game_card(game, lang)
            from bot.repositories import FavoriteRepository
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
                    await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")
            else:
                await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Screenshot search error: {e}", exc_info=True)
        try:
            await analyzing_msg.delete()
        except Exception:
            pass
        await message.answer(t("error_general", lang))


@router.message(SearchStates.clarifying)
async def handle_clarification(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    if message.text in ALL_BACK_TEXTS or message.text in [t("btn_back", lang), t("btn_main_menu", lang)]:
        await state.clear()
        is_admin = message.from_user.id in settings.admin_ids
        await message.answer(
            t("main_menu", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=is_admin),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    keywords = data.get("screenshot_keywords", [])
    answers = data.get("clarification_answers", {})
    remaining = data.get("remaining_questions", [])

    answers[f"answer_{len(answers)}"] = message.text
    keywords.append(message.text)

    if remaining:
        next_question = remaining[0]
        await state.update_data(
            clarification_answers=answers,
            remaining_questions=remaining[1:],
            screenshot_keywords=keywords,
        )
        await message.answer(
            t("screenshot_clarify", lang, question=next_question),
            parse_mode="HTML",
        )
        return

    await state.clear()
    searching_msg = await message.answer(t("search_searching", lang))

    games = await search_games(keywords)

    await searching_msg.delete()

    if not games:
        is_admin = message.from_user.id in settings.admin_ids
        await message.answer(
            t("search_no_results", lang),
            reply_markup=main_menu_keyboard(lang, is_admin=is_admin),
        )
        return

    for game in games[:3]:
        card_text = format_game_card(game, lang)
        from bot.repositories import FavoriteRepository
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
                await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")


async def get_user_lang(telegram_id: int) -> str:
    async with async_session_maker() as session:
        repo = UserRepository(session)
        user = await repo.get_by_telegram_id(telegram_id)
        return user.language if user else "en"


@router.message(F.photo)
async def handle_screenshot(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

    if not user or not user.premium_status:
        await message.answer(
            t("screenshot_premium_only", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML",
        )
        return

    analyzing_msg = await message.answer(t("screenshot_analyzing", lang))

    try:
        caption = message.caption or "game screenshot"
        ai_result = await analyze_screenshot_description(caption, lang)

        keywords = ai_result.get("keywords", [])
        confidence = ai_result.get("confidence", 0)
        clarification_needed = ai_result.get("clarification_needed", False)
        possible_game = ai_result.get("possible_game", "")

        if clarification_needed or confidence < 0.6:
            questions = ai_result.get("clarification_questions", [])
            if questions:
                await analyzing_msg.delete()
                await state.set_state(SearchStates.clarifying)
                await state.update_data(
                    screenshot_keywords=keywords,
                    clarification_answers={},
                    remaining_questions=questions[1:],
                )
                await message.answer(
                    t("screenshot_clarify", lang, question=questions[0]),
                    reply_markup=back_keyboard(lang),
                    parse_mode="HTML",
                )
                return

        if possible_game:
            keywords = [possible_game] + keywords

        games = await search_games(keywords)

        await analyzing_msg.delete()

        if not games:
            await message.answer(t("search_no_results", lang))
            return

        for game in games[:3]:
            card_text = format_game_card(game, lang)
            from bot.repositories import FavoriteRepository
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
                    await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")
            else:
                await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Screenshot search error: {e}", exc_info=True)
        try:
            await analyzing_msg.delete()
        except Exception:
            pass
        await message.answer(t("error_general", lang))


@router.message(SearchStates.clarifying)
async def handle_clarification(message: Message, state: FSMContext):
    lang = await get_user_lang(message.from_user.id)

    if message.text in [t("btn_back", lang), t("btn_main_menu", lang), "← Back", "← Назад"]:
        await state.clear()
        await message.answer(
            t("main_menu", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    keywords = data.get("screenshot_keywords", [])
    answers = data.get("clarification_answers", {})
    remaining = data.get("remaining_questions", [])

    answers[f"answer_{len(answers)}"] = message.text
    keywords.append(message.text)

    if remaining:
        next_question = remaining[0]
        await state.update_data(
            clarification_answers=answers,
            remaining_questions=remaining[1:],
            screenshot_keywords=keywords,
        )
        await message.answer(
            t("screenshot_clarify", lang, question=next_question),
            parse_mode="HTML",
        )
        return

    await state.clear()
    searching_msg = await message.answer(t("search_searching", lang))

    games = await search_games(keywords)

    await searching_msg.delete()

    if not games:
        await message.answer(
            t("search_no_results", lang),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    for game in games[:3]:
        card_text = format_game_card(game, lang)
        from bot.repositories import FavoriteRepository
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
                await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message.answer(card_text, reply_markup=keyboard, parse_mode="Markdown")
