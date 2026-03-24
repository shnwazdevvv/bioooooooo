import re
import os

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

MONGO_URI = os.environ.get("MONGO_URI", "")

_BROADCAST_CHAT_IDS = os.environ.get("BROADCAST_CHAT_IDS", "").strip()
BROADCAST_EXTRA_CHAT_IDS = []
if _BROADCAST_CHAT_IDS:
    for part in _BROADCAST_CHAT_IDS.split(","):
        part = part.strip()
        try:
            if part:
                BROADCAST_EXTRA_CHAT_IDS.append(int(part))
        except ValueError:
            pass

SPAM_WINDOW_SEC = int(os.environ.get("SPAM_WINDOW_SEC", "8"))
SPAM_MAX_MSG = int(os.environ.get("SPAM_MAX_MSG", "6"))

DEFAULT_WARNING_LIMIT = 3
DEFAULT_PUNISHMENT = "mute"
DEFAULT_CONFIG = ("warn", DEFAULT_WARNING_LIMIT, DEFAULT_PUNISHMENT)

URL_PATTERN = re.compile(
    r"""
    (?:
        (?:
            (?:(?:https?|ftps?)://|www\.)[^\s'"<>()\[\]{}]+
        )
        |
        (?:
            \b
            (?:
                (?:[A-Za-z0-9-]{1,63}\.)+(?:[A-Za-z]{2,63})
                |
                (?:\d{1,3}\.){3}\d{1,3}
                |
                \[[0-9A-Fa-f:]+\]
            )
            (?::\d{2,5})?
            (?:/[^\s'"<>()\[\]{}]*)?
        )
        |
        (?:
            \b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b
        )
        |
        (?:
            (?<!\w)@[\w_]{4,32}
        )
    )
    """,
    re.IGNORECASE | re.UNICODE | re.VERBOSE,
)
