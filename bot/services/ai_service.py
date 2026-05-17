import aiohttp
import asyncio
import json
import logging
from urllib.parse import quote
from bot.config import settings

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DETECTIVE_SYSTEM = """You are GamesDetective — an expert gamer who knows ALL games across all platforms.
A user tries to remember a game. Identify it through detective-style conversation.
LANGUAGE RULE: Always reply in the same language as the user's LAST message.
WORKFLOW: 1) Read all clues. 2) Think step by step. 3) confidence>=0.90 → final answer (clarification_needed=false). 4) confidence<0.90 → ask 1-2 SHORT questions.
MOBILE: Brawl Stars(шеллі/shelly/бравл болл), Clash of Clans(ратуша/town hall), Clash Royale, Supercell publisher, Angry Birds, Candy Crush, Subway Surfers, Among Us, Genshin Impact, PUBG Mobile, Free Fire.
PC: пубг=PUBG, майн=Minecraft, гта=GTA, кс=CS, дота=Dota2, фортнайт=Fortnite, вот=WoT, лол=LoL.
RESPOND ONLY valid JSON: {"clarification_needed":true,"game_name":"","platform":"","confidence":0.6,"detective_message":"msg","keywords":["kw"],"genres":["g"]}"""

CHAT_SYSTEM = """You are a friendly gaming assistant. Help users discuss games, recommend new ones, answer questions.
LANGUAGE RULE: Always reply in the same language the user uses. Be concise and friendly."""


async def _call_gemini(history: list, system: str = None) -> str | None:
    if not settings.gemini_api_key:
        return None
    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    payload = {
        "system_instruction": {"parts": [{"text": system or DETECTIVE_SYSTEM}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 700},
    }
    url = f"{GEMINI_URL}?key={settings.gemini_api_key}"
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 429:
                        wait = 15 * (attempt + 1)
                        logger.warning(f"Gemini 429, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    if r.status != 200:
                        logger.error(f"Gemini {r.status}: {await r.text()}")
                        return None
                    data = await r.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            logger.error(f"Gemini attempt {attempt+1}: {e}")
            if attempt < 2:
                await asyncio.sleep(5)
    return None


async def _call_openrouter(history: list, system: str = None) -> str | None:
    if not settings.openrouter_api_key:
        return None
    messages = [{"role": "system", "content": system or DETECTIVE_SYSTEM}] + history
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"}
    payload = {"model": settings.openrouter_model, "messages": messages, "max_tokens": 700, "temperature": 0.4}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OPENROUTER_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None


async def _call_ai(history: list, system: str = None) -> str | None:
    raw = await _call_gemini(history, system)
    if raw is None:
        raw = await _call_openrouter(history, system)
    return raw


def _parse_json(raw: str) -> dict:
    clean = raw.strip()
    if "```" in clean:
        for p in clean.split("```"):
            p = p.strip().lstrip("json").strip()
            try:
                return json.loads(p)
            except Exception:
                continue
    try:
        return json.loads(clean)
    except Exception:
        s, e = clean.find("{"), clean.rfind("}") + 1
        if s >= 0 and e > s:
            try:
                return json.loads(clean[s:e])
            except Exception:
                pass
    return {}


async def detective_analyze(history: list, language: str = "ua") -> dict:
    raw = await _call_ai(history, DETECTIVE_SYSTEM)
    if not raw:
        return _fallback(history[0]["content"] if history else "")
    result = _parse_json(raw)
    if not result:
        return _fallback(history[0]["content"] if history else "")
    result.setdefault("clarification_needed", True)
    result.setdefault("game_name", "")
    result.setdefault("platform", "")
    result.setdefault("confidence", 0.5)
    result.setdefault("detective_message", "")
    result.setdefault("keywords", [])
    result.setdefault("genres", [])
    gn = result.get("game_name", "")
    if gn and gn not in result["keywords"]:
        result["keywords"] = [gn] + result["keywords"]
    return result


async def chat_with_gemini(history: list) -> str | None:
    return await _call_ai(history, CHAT_SYSTEM)


def _fallback(q: str) -> dict:
    return {"clarification_needed": False, "game_name": "", "platform": "", "confidence": 0.3, "detective_message": "", "keywords": [q] if q else [], "genres": []}


async def search_steam(name: str) -> list:
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={quote(name)}&l=english&cc=US"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return []
                data = await r.json()
                res = []
                for item in data.get("items", [])[:3]:
                    aid = item.get("id", "")
                    res.append({"id": f"st{aid}", "name": item.get("name", ""), "background_image": item.get("large_capsule_image", ""), "platforms": {"pc": True}, "genres": [], "rating": 0, "released": "", "source": "Steam 🖥️", "url": f"https://store.steampowered.com/app/{aid}/"})
                return res
    except Exception as e:
        logger.error(f"Steam: {e}")
        return []


async def search_google_play(name: str) -> list:
    try:
        loop = asyncio.get_event_loop()
        def _sync():
            try:
                from google_play_scraper import search as gps
                results = gps(name, n_hits=3, lang="en", country="us")
                games = []
                for r in results:
                    aid = r.get("appId", "")
                    games.append({"id": f"gp{hash(aid) % 10**8}", "name": r.get("title", ""), "background_image": r.get("icon", ""), "platforms": {"mobile": True}, "genres": [r.get("genre", "")], "rating": round(r.get("score", 0) or 0, 1), "released": str(r.get("released", ""))[:10], "source": "Google Play 📱", "url": f"https://play.google.com/store/apps/details?id={aid}", "developer": r.get("developer", "")})
                return games
            except Exception as e:
                logger.error(f"gps: {e}")
                return []
        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        logger.error(f"GP: {e}")
        return []


async def search_app_store(name: str) -> list:
    try:
        url = f"https://itunes.apple.com/search?term={quote(name)}&entity=software&limit=3&country=us"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return []
                data = await r.json(content_type=None)
                res = []
                for item in data.get("results", []):
                    genre = item.get("primaryGenreName", "").lower()
                    if "game" not in genre and genre not in ("entertainment","action","adventure","puzzle","racing","role playing","simulation","sports","strategy"):
                        continue
                    tid = item.get("trackId", "")
                    res.append({"id": f"as{tid}", "name": item.get("trackName", ""), "background_image": item.get("artworkUrl512") or item.get("artworkUrl100", ""), "platforms": {"mobile": True}, "genres": [item.get("primaryGenreName", "")], "rating": round(item.get("averageUserRating", 0) or 0, 1), "released": (item.get("releaseDate", "") or "")[:10], "source": "App Store 🍎", "url": item.get("trackViewUrl", ""), "developer": item.get("artistName", ""), "price": "Free" if item.get("price", 0) == 0 else f"${item.get('price')}"})
                return res
    except Exception as e:
        logger.error(f"AppStore: {e}")
        return []


async def search_all_stores(name: str, platform: str = "") -> list:
    pl = platform.lower()
    tasks = []
    if pl not in ("mobile", "android", "ios"):
        tasks.append(search_steam(name))
    if pl not in ("pc", "console"):
        tasks.append(search_google_play(name))
        tasks.append(search_app_store(name))
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out


async def analyze_game_description(description: str, language: str = "en") -> dict:
    result = await detective_analyze([{"role": "user", "content": description}], language)
    return {"possible_game": result.get("game_name", ""), "keywords": result.get("keywords", [description]), "genres": result.get("genres", []), "confidence": result.get("confidence", 0.5), "clarification_needed": result.get("clarification_needed", False), "detective_message": result.get("detective_message", "")}


async def analyze_screenshot_description(description: str, language: str = "en") -> dict:
    result = await detective_analyze([{"role": "user", "content": f"Screenshot of a game: {description}"}], language)
    return {"possible_game": result.get("game_name", ""), "keywords": result.get("keywords", []), "genres": result.get("genres", []), "confidence": result.get("confidence", 0.5), "clarification_needed": result.get("clarification_needed", True)}


async def get_refined_search(original: str, clarifications: dict, language: str = "en") -> dict:
    history = [{"role": "user", "content": original}]
    for q, a in clarifications.items():
        history.append({"role": "assistant", "content": q})
        history.append({"role": "user", "content": a})
    result = await detective_analyze(history, language)
    return {"keywords": result.get("keywords", [original]), "genres": result.get("genres", []), "confidence": result.get("confidence", 0.5)}
