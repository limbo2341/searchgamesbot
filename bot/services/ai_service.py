import aiohttp
import json
import logging
from bot.config import settings

logger = logging.getLogger(__name__)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def analyze_game_description(description: str, language: str = "en") -> dict:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
        "X-Title": "IgroMemory Bot",
    }

    # Step 1: Ask AI to THINK and identify the game
    think_prompt = """You are a game expert. A user describes a game from memory - your job is to figure out EXACTLY what game it is.

Think step by step:
1. What specific elements are mentioned? (characters, game modes, mechanics, setting)
2. What game has ALL these elements together?
3. Are there any character names, game modes, or unique mechanics that point to a specific game?

The user may write in Ukrainian, Russian, or English, or mix them.
Known slang: "шеллі/shelly" = Brawl Stars character, "бравл болл" = Brawl Stars mode, "редим" = game mode in Brawl Stars, "пабг/пубг" = PUBG, "майн" = Minecraft, "кс/контра" = Counter-Strike, "дота" = Dota 2, "фортнайт" = Fortnite.

After thinking, respond ONLY in this JSON format:
{
  "thinking": "My step by step reasoning about what game this is",
  "game_name": "The exact English game name I identified",
  "confidence": 0.95,
  "search_keywords": ["exact game name", "alternative name if any"],
  "genres": ["genre"]
}

If you are not sure, still give your best guess with lower confidence."""

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": think_prompt},
            {"role": "user", "content": f"Game description: {description}"},
        ],
        "max_tokens": 600,
        "temperature": 0.2,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"OpenRouter error {response.status}: {text}")
                    return {"keywords": [description], "genres": [], "confidence": 0.3, "possible_game": ""}
                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                try:
                    clean = content.strip().strip("```json").strip("```").strip()
                    result = json.loads(clean)
                    game_name = result.get("game_name", "")
                    keywords = result.get("search_keywords", [])
                    if game_name and game_name not in keywords:
                        keywords = [game_name] + keywords
                    return {
                        "possible_game": game_name,
                        "keywords": keywords,
                        "genres": result.get("genres", []),
                        "confidence": result.get("confidence", 0.5),
                        "description": result.get("thinking", ""),
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse AI response: {content}")
                    return {"keywords": [description], "genres": [], "confidence": 0.3, "possible_game": ""}
    except Exception as e:
        logger.error(f"OpenRouter request failed: {e}")
        return {"keywords": [description], "genres": [], "confidence": 0.3, "possible_game": ""}


async def analyze_screenshot_description(description: str, language: str = "en") -> dict:
    system_prompt = """You are a game recognition expert. Identify the game from the description.
Respond ONLY in JSON: {"possible_game": "Game name", "keywords": ["keyword1"], "genres": ["genre1"], "confidence": 0.7, "clarification_needed": false, "clarification_questions": []}"""
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description},
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                clean = content.strip().strip("```json").strip("```").strip()
                return json.loads(clean)
    except Exception as e:
        logger.error(f"Screenshot analysis failed: {e}")
        return {"keywords": [], "confidence": 0.3, "clarification_needed": True}


async def get_refined_search(original: str, clarifications: dict, language: str = "en") -> dict:
    system_prompt = """Based on the description and clarifications, identify the exact game name.
Respond ONLY in JSON: {"keywords": ["exact game name", "keyword2"], "genres": ["genre1"], "confidence": 0.85}"""
    clarification_text = "\n".join([f"{k}: {v}" for k, v in clarifications.items()])
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Original: {original}\nClarifications:\n{clarification_text}"},
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                clean = content.strip().strip("```json").strip("```").strip()
                return json.loads(clean)
    except Exception as e:
        logger.error(f"Refined search failed: {e}")
        return {"keywords": [original], "confidence": 0.5}
