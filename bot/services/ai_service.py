import aiohttp
import json
import logging
from bot.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def analyze_game_description(description: str, language: str = "en") -> dict:
    """Analyze user description and extract game search keywords."""
    lang_prompts = {
        "en": "English",
        "ru": "Russian",
        "ua": "Ukrainian",
    }
    lang = lang_prompts.get(language, "English")

    system_prompt = f"""You are an expert game identifier with knowledge of thousands of games from all eras and platforms.
The user will describe a game from memory - your job is to identify it with maximum accuracy.

IMPORTANT RULES:
1. Think step by step about what game this could be
2. Consider ALL clues: gameplay, visuals, setting, time period, platform
3. If you recognize the game, put the EXACT game name as the first keyword
4. Extract 5-8 specific search keywords in English
5. Be specific - avoid generic words like "game", "player", "level"
6. Consider games from 1980s to 2024

Respond ONLY in JSON format, no extra text:
{{
  "possible_game": "Most likely game name (if confident)",
  "keywords": ["exact_game_name", "keyword2", "keyword3", "keyword4", "keyword5"],
  "genres": ["genre1", "genre2"],
  "description": "Brief explanation of why you think this game",
  "platform_hints": ["PC", "PS4"],
  "year_hint": "approximate year or decade",
  "confidence": 0.85
}}

User writes in {lang}. Extract keywords in English for RAWG API search.
If user writes a game name directly - use it as the main keyword."""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
        "X-Title": "IgroMemory Bot",
    }

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description},
        ],
        "max_tokens": 500,
        "temperature": 0.3,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"OpenRouter error {response.status}: {text}")
                    return {"keywords": [description], "genres": [], "confidence": 0.3}

                data = await response.json()
                content = data["choices"][0]["message"]["content"]

                try:
                    clean = content.strip().strip("```json").strip("```").strip()
                    result = json.loads(clean)
                    return result
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse AI response as JSON: {content}")
                    return {"keywords": [description], "genres": [], "confidence": 0.3}

    except Exception as e:
        logger.error(f"OpenRouter request failed: {e}")
        return {"keywords": [description], "genres": [], "confidence": 0.3}


async def analyze_screenshot_description(description: str, language: str = "en") -> dict:
    """Analyze screenshot description for game search."""
    system_prompt = """You are a game recognition expert. Based on the visual description, 
identify what game this might be and extract search keywords.
Respond ONLY in JSON format:
{
  "possible_game": "Game name if recognized",
  "keywords": ["keyword1", "keyword2"],
  "genres": ["genre1"],
  "confidence": 0.7,
  "clarification_needed": false,
  "clarification_questions": []
}
If confidence < 0.6, set clarification_needed to true and add 2-3 clarification questions."""

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/SearchForGame_bot",
        "X-Title": "IgroMemory Bot",
    }

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Screenshot description: {description}"},
        ],
        "max_tokens": 500,
        "temperature": 0.3,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    return {"keywords": [], "confidence": 0.3, "clarification_needed": True}

                data = await response.json()
                content = data["choices"][0]["message"]["content"]
                clean = content.strip().strip("```json").strip("```").strip()
                return json.loads(clean)

    except Exception as e:
        logger.error(f"OpenRouter screenshot analysis failed: {e}")
        return {"keywords": [], "confidence": 0.3, "clarification_needed": True}


async def get_refined_search(original: str, clarifications: dict, language: str = "en") -> dict:
    """Refine search with additional clarifications from user."""
    system_prompt = """Based on the original description and user clarifications, 
provide refined search keywords for finding the game.
Respond ONLY in JSON:
{
  "keywords": ["keyword1", "keyword2"],
  "genres": ["genre1"],
  "confidence": 0.85
}"""

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
