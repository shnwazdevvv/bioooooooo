from typing import Dict, Tuple, Set, List, Optional
import time
import re
import unicodedata

from pyrogram import Client, enums
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from config import (
    MONGO_URI,
    DEFAULT_CONFIG,
    DEFAULT_PUNISHMENT,
    DEFAULT_WARNING_LIMIT,
    BROADCAST_EXTRA_CHAT_IDS,
    SPAM_WINDOW_SEC,
    SPAM_MAX_MSG,
    URL_PATTERN,
)

if not MONGO_URI or "mongodb" not in MONGO_URI:
    raise ValueError(
        "MONGO_URI is not configured. Please set a valid MongoDB URI in environment variables."
    )

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["telegram_bot_db"]
warnings_collection = db["warnings"]
punishments_collection = db["punishments"]
whitelists_collection = db["whitelists"]
chats_collection = db["chats"]

_ADMIN_CACHE: Dict[Tuple[int, int], Tuple[bool, float]] = {}
_CONFIG_CACHE: Dict[int, Tuple[Tuple[str, int, str], float]] = {}
_WHITELIST_CACHE: Dict[int, Tuple[Set[int], float]] = {}
_CHATS_CACHE: Tuple[Set[int], float] = (set(), 0.0)
_BIO_CACHE: Dict[int, Tuple[Tuple[str, str, Optional[str]], float]] = {}

_SPAM_TRACKER: Dict[Tuple[int, int], Tuple[float, int]] = {}

ADMIN_TTL = 300.0
CONFIG_TTL = 600.0
WHITELIST_TTL = 300.0
CHATS_TTL = 600.0
BIO_TTL = 600.0


def _now() -> float:
    return time.monotonic()


async def is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    cached = _ADMIN_CACHE.get(key)
    if cached and cached[1] > _now():
        return cached[0]

    try:
        member = await client.get_chat_member(chat_id, user_id)
        status = getattr(member, "status", None)
        is_adm = status in {enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR}
    except Exception:
        is_adm = False

    _ADMIN_CACHE[key] = (is_adm, _now() + ADMIN_TTL)
    return is_adm


async def get_config(chat_id: int):
    cached = _CONFIG_CACHE.get(chat_id)
    if cached and cached[1] > _now():
        return cached[0]

    doc = await punishments_collection.find_one({"chat_id": chat_id})
    if doc:
        cfg = (
            doc.get("mode", "warn"),
            int(doc.get("limit", DEFAULT_WARNING_LIMIT)),
            doc.get("penalty", DEFAULT_PUNISHMENT),
        )
    else:
        cfg = DEFAULT_CONFIG

    _CONFIG_CACHE[chat_id] = (cfg, _now() + CONFIG_TTL)
    return cfg


async def update_config(chat_id: int, mode=None, limit=None, penalty=None):
    update = {}
    if mode is not None:
        update["mode"] = mode
    if limit is not None:
        update["limit"] = int(limit)
    if penalty is not None:
        update["penalty"] = penalty

    if update:
        await punishments_collection.update_one(
            {"chat_id": chat_id},
            {"$set": update},
            upsert=True,
        )
        current = await get_config(chat_id)
        new_cfg = (
            update.get("mode", current[0]),
            int(update.get("limit", current[1])),
            update.get("penalty", current[2]),
        )
        _CONFIG_CACHE[chat_id] = (new_cfg, _now() + CONFIG_TTL)


async def increment_warning(chat_id: int, user_id: int) -> int:
    doc = await warnings_collection.find_one_and_update(
        {"chat_id": chat_id, "user_id": user_id},
        {"$inc": {"count": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc.get("count", 1))


async def reset_warnings(chat_id: int, user_id: int):
    await warnings_collection.delete_one({"chat_id": chat_id, "user_id": user_id})


async def _load_whitelist(chat_id: int) -> Set[int]:
    cursor = whitelists_collection.find({"chat_id": chat_id})
    docs = await cursor.to_list(length=None)
    return {int(doc["user_id"]) for doc in docs}


async def is_whitelisted(chat_id: int, user_id: int) -> bool:
    cached = _WHITELIST_CACHE.get(chat_id)
    if cached and cached[1] > _now():
        return user_id in cached[0]

    wl = await _load_whitelist(chat_id)
    _WHITELIST_CACHE[chat_id] = (wl, _now() + WHITELIST_TTL)
    return user_id in wl


async def add_whitelist(chat_id: int, user_id: int):
    await whitelists_collection.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"user_id": user_id}},
        upsert=True,
    )
    cached = _WHITELIST_CACHE.get(chat_id)
    if cached and cached[1] > _now():
        cached[0].add(user_id)


async def remove_whitelist(chat_id: int, user_id: int):
    await whitelists_collection.delete_one({"chat_id": chat_id, "user_id": user_id})
    cached = _WHITELIST_CACHE.get(chat_id)
    if cached and cached[1] > _now():
        cached[0].discard(user_id)


async def get_whitelist(chat_id: int) -> list:
    cached = _WHITELIST_CACHE.get(chat_id)
    if cached and cached[1] > _now():
        return list(sorted(cached[0]))

    wl = await _load_whitelist(chat_id)
    _WHITELIST_CACHE[chat_id] = (wl, _now() + WHITELIST_TTL)
    return list(sorted(wl))


async def add_chat(chat_id: int):
    await chats_collection.update_one(
        {"chat_id": chat_id}, {"$set": {"chat_id": chat_id}}, upsert=True
    )
    chat_ids, exp = _CHATS_CACHE
    if exp > _now():
        chat_ids.add(chat_id)


async def get_all_chats() -> List[int]:
    global _CHATS_CACHE
    chat_ids, exp = _CHATS_CACHE
    if exp > _now() and chat_ids:
        return list(sorted(set(chat_ids).union(set(BROADCAST_EXTRA_CHAT_IDS))))

    cursor = chats_collection.find({})
    docs = await cursor.to_list(length=None)
    chat_ids = {int(doc.get("chat_id")) for doc in docs}
    chat_ids.update(BROADCAST_EXTRA_CHAT_IDS)
    _CHATS_CACHE = (chat_ids, _now() + CHATS_TTL)
    return list(sorted(chat_ids))


async def count_warnings(chat_id: int) -> int:
    pipeline = [
        {"$match": {"chat_id": chat_id}},
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$count", 0]}}}},
    ]
    cursor = warnings_collection.aggregate(pipeline)
    docs = await cursor.to_list(length=1)
    if docs:
        return int(docs[0].get("total", 0))
    return 0


async def count_warning_records(chat_id: int) -> int:
    return await warnings_collection.count_documents({"chat_id": chat_id})


async def count_whitelist(chat_id: int) -> int:
    return await whitelists_collection.count_documents({"chat_id": chat_id})


async def total_chats() -> int:
    chat_ids, exp = _CHATS_CACHE
    if exp > _now() and chat_ids:
        return len(chat_ids)
    return await chats_collection.count_documents({})


# ----- Link normalization and detection -----

_ZERO_WIDTH_RE = re.compile(r"[\u200B\u200C\u200D\u2060\uFEFF]")
_DOT_WORD_RE = re.compile(r"(?i)\b(?:d[\W_]*o[\W_]*t|\(\s*dot\s*\)|\[\s*dot\s*\]|\{\s*dot\s*\})\b")
_DOT_BRACKET_RE = re.compile(r"(?i)\[\s*\.\s*\]|\(\s*\.\s*\)|\{\s*\.\s*\}")
_AT_WORD_RE = re.compile(r"(?i)\b(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+)\b")
_HTTPS_SPACED_RE = re.compile(r"(?i)h\s*t\s*t\s*p\s*s")
_HTTP_SPACED_RE = re.compile(r"(?i)h\s*t\s*t\s*p")
_COLON_SLASHES_RE = re.compile(r":\s*/\s*/")
_WWW_SPACED_RE = re.compile(r"(?i)w\s*w\s*w\s*\.")
_DOT_SPACES_RE = re.compile(r"(?i)([a-z0-9-])\s*\.\s*([a-z0-9-])")
_SLASH_SPACES_RE = re.compile(r"/\s*/")
_TME_SPACED_RE = re.compile(r"(?i)t\s*\.\s*me\b")
_TELEGRAM_HOSTS_RE = re.compile(r"(?i)telegram\s*\.\s*(?:me|dog|org)\b|telegra\s*\.\s*ph\b")


def normalize_for_links(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _ZERO_WIDTH_RE.sub("", s)
    s = _DOT_BRACKET_RE.sub(".", s)
    s = _DOT_WORD_RE.sub(".", s)
    s = _AT_WORD_RE.sub("@", s)
    s = _COLON_SLASHES_RE.sub("://", s)
    s = _WWW_SPACED_RE.sub("www.", s)
    s = _TME_SPACED_RE.sub("t.me", s)
    s = _TELEGRAM_HOSTS_RE.sub(lambda m: m.group(0).replace(" ", ""), s)
    s = _HTTPS_SPACED_RE.sub("https", s)
    s = _HTTP_SPACED_RE.sub("http", s)
    s = _DOT_SPACES_RE.sub(r"\1.\2", s)
    s = _SLASH_SPACES_RE.sub("/", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s


def contains_link(text: str) -> bool:
    s = normalize_for_links(text)
    if not s:
        return False
    if URL_PATTERN.search(s):
        return True
    if re.search(r"(?i)(?<!\w)@\s*[\w_]{4,32}", s):
        return True
    if re.search(r"(?i)\b(?:[a-z0-9-]{1,63}\.)+[a-z]{2,63}\b", s):
        return True
    return False


async def get_user_profile_cached(
    client: Client, user_id: int
) -> Tuple[str, str, Optional[str]]:
    cached = _BIO_CACHE.get(user_id)
    if cached and cached[1] > _now():
        bio, first_name, last_name = cached[0]
        return bio or "", first_name or "", last_name

    try:
        chat = await client.get_chat(user_id)
        bio = getattr(chat, "bio", "") or ""
        first_name = getattr(chat, "first_name", "") or ""
        last_name = getattr(chat, "last_name", None)
    except Exception:
        usr = await client.get_users(user_id)
        bio = getattr(usr, "bio", "") or ""
        first_name = getattr(usr, "first_name", "") or ""
        last_name = getattr(usr, "last_name", None)

    _BIO_CACHE[user_id] = ((bio, first_name, last_name), _now() + BIO_TTL)
    return bio, first_name, last_name


def register_message_event(chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    now = _now()
    window_start, count = _SPAM_TRACKER.get(key, (now, 0))
    if now - window_start > SPAM_WINDOW_SEC:
        window_start, count = now, 1
    else:
        count += 1
    _SPAM_TRACKER[key] = (window_start, count)
    return count >= SPAM_MAX_MSG
