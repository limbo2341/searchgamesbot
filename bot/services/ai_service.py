"""
ai_service.py — «Детектив-геймер» логіка для IgroMemory бота.

Замість одного холодного запиту AI тепер веде інтерактивний діалог:
  1. Отримує початковий опис → намагається вгадати гру.
  2. Якщо впевненість < 90% → повертає clarification_needed=True + 1-2 питання.
  3. Кожна наступна відповідь користувача дописується в historу і знову подається AI.
  4. Коли впевненість ≥ 90% → clarification_needed=False, game_name містить фінальну назву.
"""

import aiohttp
import json
import logging
from bot.config import settings

logger = logging.getLogger(__name__)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ──────────────────────────────────────────────
# Системний промпт — «Детектив-геймер»
# ──────────────────────────────────────────────

DETECTIVE_SYSTEM = """You are GamesDetective — an enthusiastic gamer who has played thousands of games since the 1980s.
A user is trying to remember a game they played. Your job: identify the game through a fun detective-style conversation.

LANGUAGE RULE:
- Detect the language the user is writing in (Ukrainian, Russian, English, or a mix).
- Always reply in the SAME language the user used in their LAST message.

YOUR WORKFLOW:
1. Read ALL provided clues (description + any previous Q&A).
2. Think step by step: what game mechanics, characters, settings, year, platform fit?
3. If you are 90-100% sure — give the final answer (clarification_needed = false).
4. If you are less than 90% sure — ask 1 or 2 SHORT, fun clarifying questions to narrow it down.
   - Questions must be specific and easy to answer (yes/no, multiple choice, or short).
   - Never ask more than 2 questions at once.
   - Vary question types: genre, platform, year, visual style, multiplayer, character, mechanic.
5. Once confident, output the EXACT English game name in "game_name".

KNOWN SLANG (always recognize these):
- "шеллі / shelly", "бравл болл / brawl ball", "бравл / brawl" → Brawl Stars
- "пубг / pubg / пабг" → PUBG: Battlegrounds
- "майн / майнкрафт" → Minecraft
- "гта / gta" → Grand Theft Auto
- "кс / контра / cs" → Counter-Strike
- "дота / доту" → Dota 2
- "фортнайт / fortnite" → Fortnite
- "амонг ас / among us" → Among Us
- "вот / ворлд оф тенкс" → World of Tanks
- "лол / league" → League of Legends

RESPONSE FORMAT — always respond with ONLY valid JSON, no extra text:
{
  "clarification_needed": true or false,
  "game_name": "Exact English game name (empty string if not yet sure)",
  "confidence": 0.0 to 1.0,
  "detective_message": "Your message to the user in their language (thinking aloud + questions or final reveal)",
  "keywords": ["game name", "alternative", "genre keyword"],
  "genres": ["genre1", "genre2"]
}

When revealing the answer (clarification_needed=false), make it exciting:
e.g. "Розгадав! 🎯 Це [Game Name]! Ось чому я так думаю: ..."
"""


# ──────────────────────────────────────────────
# Основна функція — інтерактивний детектив
# ──────────────────────────────────────────────

async def detective_analyze(
    conversation_history: list[dict],
    language: str = "ua",
) -> dict:
    """
    Передає повну історію діалогу AI і отримує або уточнюючі питання,
    або фінальну назву гри.

    conversation_history — список dict: [{"role": "user"|"assistant", "content": str}, ...]
    Перший елемент повинен бути першим описом від користувача.

    Повертає dict:
    {
        "clarification_needed": bool,
        "game_name": str,
        "confidence": float,
        "detective_message": str,   ← текст для показу користувачеві
        "keywords": list[str],
        "genres": list[str],
    }
    """
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
        "X-Title": "IgroMemory Bot",
    }

    messages = [{"role": "system", "content": DETECTIVE_SYSTEM}] + conversation_history

    payload = {
        "model": settings.openrouter_model,
        "messages": messages,
        "max_tokens": 700,
        "temperature": 0.4,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"OpenRouter error {response.status}: {text}")
                    return _fallback(conversation_history[0]["content"] if conversation_history else "")

                data = await response.json()
                raw = data["choices"][0]["message"]["content"]

        # Парсимо JSON з відповіді
        clean = raw.strip()
        # Видаляємо markdown-огорожі якщо є
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        result = json.loads(clean)

        # Гарантуємо всі потрібні поля
        result.setdefault("clarification_needed", True)
        result.setdefault("game_name", "")
        result.setdefault("confidence", 0.5)
        result.setdefault("detective_message", "")
        result.setdefault("keywords", [])
        result.setdefault("genres", [])

        # Якщо AI впевнений і є назва — додаємо її першою в keywords
        if result["game_name"] and result["game_name"] not in result["keywords"]:
            result["keywords"] = [result["game_name"]] + result["keywords"]

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error in detective_analyze: {e}\nRaw: {raw[:300]}")
        return _fallback(conversation_history[0]["content"] if conversation_history else "")
    except Exception as e:
        logger.error(f"detective_analyze failed: {e}", exc_info=True)
        return _fallback(conversation_history[0]["content"] if conversation_history else "")


def _fallback(original_query: str) -> dict:
    """Запасний результат якщо AI не відповів."""
    return {
        "clarification_needed": False,
        "game_name": "",
        "confidence": 0.3,
        "detective_message": "",
        "keywords": [original_query] if original_query else [],
        "genres": [],
    }


# ──────────────────────────────────────────────
# Допоміжні функції (залишені для сумісності)
# ──────────────────────────────────────────────

async def analyze_game_description(description: str, language: str = "en") -> dict:
    """Wrapper для зворотної сумісності зі старим кодом."""
    history = [{"role": "user", "content": description}]
    result = await detective_analyze(history, language)
    return {
        "possible_game": result.get("game_name", ""),
        "keywords": result.get("keywords", [description]),
        "genres": result.get("genres", []),
        "confidence": result.get("confidence", 0.5),
        "description": result.get("detective_message", ""),
        "clarification_needed": result.get("clarification_needed", False),
        "detective_message": result.get("detective_message", ""),
    }


async def analyze_screenshot_description(description: str, language: str = "en") -> dict:
    """Аналіз скріншота — один запит, без діалогу."""
    system = (
        "You are a game recognition expert. Identify the game from the visual description. "
        "Respond ONLY in JSON: "
        '{"possible_game": "Game name", "keywords": ["kw1","kw2"], '
        '"genres": ["g1"], "confidence": 0.8, "clarification_needed": false}'
    )
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": description},
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as resp:
                data = await resp.json()
                raw = data["choices"][0]["message"]["content"]
                clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                return json.loads(clean)
    except Exception as e:
        logger.error(f"Screenshot analysis failed: {e}")
        return {"keywords": [], "confidence": 0.3, "clarification_needed": True}


async def get_refined_search(original: str, clarifications: dict, language: str = "en") -> dict:
    """Старий API — тепер делегує detective_analyze."""
    history = [{"role": "user", "content": original}]
    for q, a in clarifications.items():
        history.append({"role": "assistant", "content": q})
        history.append({"role": "user", "content": a})
    result = await detective_analyze(history, language)
    return {
        "keywords": result.get("keywords", [original]),
        "genres": result.get("genres", []),
        "confidence": result.get("confidence", 0.5),
    }
