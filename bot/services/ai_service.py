"""
ai_service.py — Gemini як головний мозок + детектив-діалог.

- Gemini 2.0 Flash (безкоштовний) веде діалог як детектив-геймер.
- Якщо впевненість < 90% → ставить 1-2 уточнюючих питання.
- Якщо впевненість ≥ 90% → повертає назву гри для пошуку.
- Fallback на OpenRouter якщо Gemini недоступний.
- Пошук: RAWG + Steam (безкоштовно).
"""

import aiohttp
import json
import logging
from bot.config import settings

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DETECTIVE_SYSTEM = """You are GamesDetective — an enthusiastic gamer-detective who has played thousands of games since the 1980s across ALL platforms: PC, PlayStation, Xbox, Nintendo, iOS, Android.

A user is trying to remember a game. Your job: identify it through a detective-style conversation.

LANGUAGE RULE: Detect the language of the user's LAST message. ALWAYS reply in that SAME language.

WORKFLOW:
1. Read ALL clues (description + Q&A history).
2. Think step by step: mechanics, characters, setting, platform, year, publisher.
3. confidence >= 0.90 → final answer (clarification_needed = false, fill game_name).
4. confidence < 0.90 → ask 1-2 SHORT fun questions (yes/no or multiple choice). Never more than 2.
5. Reveal answer excitedly: "Розгадав! 🎯 Це [Назва]!" or "Got it! 🎯 It's [Name]!"

MOBILE GAMES — you MUST know these:
- Supercell: Brawl Stars, Clash of Clans, Clash Royale, Hay Day, Boom Beach, Squad Busters
- "шеллі/shelly" = Brawl Stars character → game is Brawl Stars
- "бравл болл/brawl ball" = Brawl Stars mode
- "ратуша/town hall" = Clash of Clans
- "supercell/супер клітина" = Supercell publisher
- Angry Birds (Rovio), Candy Crush (King), Subway Surfers, Temple Run
- Among Us (InnerSloth), Genshin Impact (miHoYo), Pokémon GO (Niantic)

PC/Console slang:
- "пубг/pubg" = PUBG, "майн/майнкрафт" = Minecraft, "гта/gta" = GTA
- "кс/контра" = Counter-Strike, "дота" = Dota 2, "фортнайт" = Fortnite
- "вот" = World of Tanks, "лол" = League of Legends

RESPOND ONLY with valid JSON (no markdown, no extra text):
{
  "clarification_needed": true,
  "game_name": "",
  "platform": "",
  "confidence": 0.6,
  "detective_message": "Message to user in their language",
  "keywords": ["keyword1", "keyword2"],
  "genres": ["genre1"]
}"""


async def _call_gemini(conversation_history: list) -> str | None:
    if not settings.gemini_api_key:
        return None

    contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "system_instruction": {"parts": [{"text": DETECTIVE_SYSTEM}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 700,
            "responseMimeType": "application/json",
        },
    }

    url = f"{GEMINI_URL}?key={settings.gemini_api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Gemini error {resp.status}: {text[:300]}")
                    return None
                data = await resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return None


async def _call_openrouter(conversation_history: list) -> str | None:
    if not settings.openrouter_api_key:
        return None

    messages = [{"role": "system", "content": DETECTIVE_SYSTEM}] + conversation_history
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
        "X-Title": "IgroMemory Bot",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": messages,
        "max_tokens": 700,
        "temperature": 0.4,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter call failed: {e}")
        return None


def _parse_response(raw: str) -> dict:
    clean = raw.strip()
    if "```" in clean:
        for part in clean.split("```"):
            part = part.strip().lstrip("json").strip()
            try:
                return json.loads(part)
            except Exception:
                continue
    try:
        return json.loads(clean)
    except Exception:
        start, end = clean.find("{"), clean.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(clean[start:end])
            except Exception:
                pass
    logger.warning(f"Could not parse AI response: {clean[:200]}")
    return {}


async def detective_analyze(conversation_history: list, language: str = "ua") -> dict:
    """
    Головна функція детективного пошуку.
    Приймає повну історію діалогу, повертає dict з полями:
      clarification_needed, game_name, platform, confidence,
      detective_message, keywords, genres
    """
    raw = await _call_gemini(conversation_history)
    if raw is None:
        logger.info("Gemini unavailable, trying OpenRouter")
        raw = await _call_openrouter(conversation_history)
    if raw is None:
        return _fallback(conversation_history[0]["content"] if conversation_history else "")

    result = _parse_response(raw)
    if not result:
        return _fallback(conversation_history[0]["content"] if conversation_history else "")

    result.setdefault("clarification_needed", True)
    result.setdefault("game_name", "")
    result.setdefault("platform", "")
    result.setdefault("confidence", 0.5)
    result.setdefault("detective_message", "")
    result.setdefault("keywords", [])
    result.setdefault("genres", [])

    game_name = result.get("game_name", "")
    if game_name and game_name not in result["keywords"]:
        result["keywords"] = [game_name] + result["keywords"]

    return result


def _fallback(original_query: str) -> dict:
    return {
        "clarification_needed": False,
        "game_name": "",
        "platform": "",
        "confidence": 0.3,
        "detective_message": "",
        "keywords": [original_query] if original_query else [],
        "genres": [],
    }


async def search_steam(game_name: str) -> list:
    """Шукає гру в Steam через безкоштовний Steam Store API."""
    try:
        from urllib.parse import quote
        url = f"https://store.steampowered.com/api/storesearch/?term={quote(game_name)}&l=english&cc=US"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = []
                for item in data.get("items", [])[:3]:
                    results.append({
                        "id": f"steam_{item.get('id')}",
                        "name": item.get("name", ""),
                        "background_image": item.get("large_capsule_image") or item.get("small_capsule_image"),
                        "platforms": {"pc": True},
                        "genres": [],
                        "rating": 0,
                        "released": "",
                        "source": "Steam 🖥️",
                        "url": f"https://store.steampowered.com/app/{item.get('id')}/",
                    })
                return results
    except Exception as e:
        logger.error(f"Steam search failed: {e}")
        return []


# ── Зворотна сумісність ──

async def analyze_game_description(description: str, language: str = "en") -> dict:
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
    history = [{"role": "user", "content": f"Screenshot of a game. Identify it. What I see: {description}"}]
    result = await detective_analyze(history, language)
    return {
        "possible_game": result.get("game_name", ""),
        "keywords": result.get("keywords", []),
        "genres": result.get("genres", []),
        "confidence": result.get("confidence", 0.5),
        "clarification_needed": result.get("clarification_needed", True),
    }


async def get_refined_search(original: str, clarifications: dict, language: str = "en") -> dict:
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
