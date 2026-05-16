import aiohttp
import logging
from typing import List, Optional
from bot.config import settings

logger = logging.getLogger(__name__)

RAWG_BASE_URL = "https://api.rawg.io/api"


async def search_games(keywords: List[str], genres: Optional[List[str]] = None, page: int = 1) -> List[dict]:
    """Search games on RAWG API."""
    query = " ".join(keywords[:5])

    params = {
        "key": settings.rawg_api_key,
        "search": query,
        "page_size": 5,
        "page": page,
        "ordering": "-rating",
    }

    if genres:
        genre_map = {
            "action": "action",
            "adventure": "adventure",
            "rpg": "role-playing-games-rpg",
            "shooter": "shooter",
            "strategy": "strategy",
            "puzzle": "puzzle",
            "racing": "racing",
            "sports": "sports",
            "fighting": "fighting",
            "simulation": "simulation",
        }
        matched = []
        for g in genres:
            g_lower = g.lower()
            for key, val in genre_map.items():
                if key in g_lower:
                    matched.append(val)
                    break
        if matched:
            params["genres"] = ",".join(matched[:2])

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{RAWG_BASE_URL}/games", params=params) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"RAWG API error {response.status}: {text}")
                    return []

                data = await response.json()
                results = data.get("results", [])
                return [format_game(game) for game in results]

    except Exception as e:
        logger.error(f"RAWG search failed: {e}")
        return []


async def get_game_details(game_id: int) -> Optional[dict]:
    """Get detailed info about specific game."""
    params = {"key": settings.rawg_api_key}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{RAWG_BASE_URL}/games/{game_id}", params=params) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                return format_game_detail(data)
    except Exception as e:
        logger.error(f"RAWG get details failed: {e}")
        return None


def format_game(game: dict) -> dict:
    """Format raw RAWG game data."""
    platforms = []
    if game.get("platforms"):
        platforms = [p["platform"]["name"] for p in game["platforms"][:5]]

    genres = []
    if game.get("genres"):
        genres = [g["name"] for g in game["genres"][:4]]

    return {
        "id": str(game.get("id", "")),
        "name": game.get("name", "Unknown"),
        "description": game.get("short_screenshots", [{}])[0].get("image", "") if game.get("short_screenshots") else "",
        "background_image": game.get("background_image", ""),
        "rating": game.get("rating", 0),
        "ratings_count": game.get("ratings_count", 0),
        "released": game.get("released", "Unknown"),
        "platforms": platforms,
        "genres": genres,
        "metacritic": game.get("metacritic"),
    }


def format_game_detail(game: dict) -> dict:
    """Format detailed game data."""
    platforms = []
    if game.get("platforms"):
        platforms = [p["platform"]["name"] for p in game["platforms"][:6]]

    genres = []
    if game.get("genres"):
        genres = [g["name"] for g in game["genres"][:5]]

    description = game.get("description_raw", "")
    if len(description) > 500:
        description = description[:500] + "..."

    return {
        "id": str(game.get("id", "")),
        "name": game.get("name", "Unknown"),
        "description": description,
        "background_image": game.get("background_image", ""),
        "rating": game.get("rating", 0),
        "ratings_count": game.get("ratings_count", 0),
        "released": game.get("released", "Unknown"),
        "platforms": platforms,
        "genres": genres,
        "metacritic": game.get("metacritic"),
        "website": game.get("website", ""),
        "developers": [d["name"] for d in game.get("developers", [])[:2]],
        "publishers": [p["name"] for p in game.get("publishers", [])[:2]],
    }


def format_game_card(game: dict, language: str = "en") -> str:
    """Format game as beautiful text card."""
    stars = "⭐" * min(int(game.get("rating", 0)), 5)
    rating = game.get("rating", 0)
    platforms = ", ".join(game.get("platforms", [])[:3]) or "Unknown"
    genres = ", ".join(game.get("genres", [])[:3]) or "Unknown"
    released = game.get("released", "Unknown")
    metacritic = game.get("metacritic")
    mc_text = f"🎮 Metacritic: **{metacritic}**\n" if metacritic else ""

    texts = {
        "en": f"""🎮 **{game['name']}**

{stars} Rating: **{rating:.1f}**
{mc_text}📅 Released: **{released}**
🎯 Genres: **{genres}**
💻 Platforms: **{platforms}**""",
        "ru": f"""🎮 **{game['name']}**

{stars} Рейтинг: **{rating:.1f}**
{mc_text}📅 Вышла: **{released}**
🎯 Жанры: **{genres}**
💻 Платформы: **{platforms}**""",
        "ua": f"""🎮 **{game['name']}**

{stars} Рейтинг: **{rating:.1f}**
{mc_text}📅 Вийшла: **{released}**
🎯 Жанри: **{genres}**
💻 Платформи: **{platforms}**""",
    }

    return texts.get(language, texts["en"])
