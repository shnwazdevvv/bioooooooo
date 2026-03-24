from pyrogram import Client, filters, errors
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
import asyncio
import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from helper.utils import (
    is_admin,
    get_config, update_config,
    increment_warning, reset_warnings,
    is_whitelisted, add_whitelist, remove_whitelist, get_whitelist,
    add_chat, get_all_chats,
    get_user_profile_cached,
    register_message_event,
    count_warnings, count_whitelist, total_chats, count_warning_records,
    contains_link,
)

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    URL_PATTERN,
    OWNER_ID,
)

app = Client(
    "biolink_protector_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


@app.on_message(filters.command("start"))
async def start_handler(client: Client, message):
    chat_id = message.chat.id
    await add_chat(chat_id)
    bot = await client.get_me()
    add_url = f"https://t.me/{bot.username}?startgroup=true"
    text = (
        "**✨ Welcome to BioLink Protector Bot! ✨**\n\n"
        "🛡️ I help protect your groups from users with links in their bio.\n\n"
        "**🔹 Key Features:**\n"
        "   • Automatic URL detection in user bios\n"
        "   • Customizable warning limit\n"
        "   • Auto-mute or ban when limit is reached\n"
        "   • Whitelist management for trusted users\n\n"
        "**Use /help to see all available commands.**"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Me to Your Group", url=add_url)],
        [
            InlineKeyboardButton("⚙️ Configure", callback_data="back"),
            InlineKeyboardButton("🛠️ Support", url="https://t.me/iwantandroid"),
        ],
        [
            InlineKeyboardButton("📦 Source", url="https://github.com/strad-dev131/BioLink-Protector"),
            InlineKeyboardButton("🗑️ Close", callback_data="close"),
        ],
    ])
    await client.send_message(chat_id, text, reply_markup=kb)


@app.on_message(filters.command("help"))
async def help_handler(client: Client, message):
    chat_id = message.chat.id
    help_text = (
        "**🛠️ Bot Commands & Usage**\n\n"
        "`/config` – set warn-limit & punishment mode (admins)\n"
        "`/free` – whitelist a user (reply or user/id) (admins)\n"
        "`/unfree` – remove from whitelist (admins)\n"
        "`/freelist` – list all whitelisted users (admins)\n"
        "`/stats` – show chat protection stats (admins)\n"
        "`/id` – show your ID and chat/replied user ID\n"
        "`/ping` – check bot latency\n"
        "`/about` – about and helpful links\n\n"
        "**When someone with a URL in their bio posts, I'll:**\n"
        " 1. ⚠️ Warn them\n"
        " 2. 🔇 Mute when they exceed the limit (if set)\n"
        " 3. 🔨 Ban when configured to ban\n\n"
        "**Use the inline buttons on warnings to cancel or whitelist**"
    )
    bot = await client.get_me()
    add_url = f"https://t.me/{bot.username}?startgroup=true"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add to Group", url=add_url)],
        [InlineKeyboardButton("🗑️ Close", callback_data="close")]
    ])
    await client.send_message(chat_id, help_text, reply_markup=kb)


@app.on_message(filters.command("ping"))
async def ping_handler(client: Client, message):
    start = time.perf_counter()
    m = await message.reply_text("Pinging...")
    dt = (time.perf_counter() - start) * 1000
    await m.edit_text(f"Pong! {dt:.0f} ms")


@app.on_message(filters.command("id"))
async def id_handler(client: Client, message):
    uid = message.from_user.id if message.from_user else 0
    cid = message.chat.id
    text = [f"👤 Your ID: `{uid}`", f"💬 Chat ID: `{cid}`"]
    if message.reply_to_message and message.reply_to_message.from_user:
        text.append(f"↪️ Replied user ID: `{message.reply_to_message.from_user.id}`")
    await message.reply_text("\n".join(text))


@app.on_message(filters.command("about"))
async def about_handler(client: Client, message):
    bot = await client.get_me()
    add_url = f"https://t.me/{bot.username}?startgroup=true"
    text = (
        "**BioLink Protector**\n"
        "Protect your groups by detecting links in user bios and applying warnings, mutes, or bans.\n\n"
        "• Fast and reliable (cached admin checks, reduced API/DB calls)\n"
        "• Flexible configuration per chat\n"
        "• Owner broadcast support\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add to Group", url=add_url)],
        [
            InlineKeyboardButton("📦 Source", url="https://github.com/strad-dev131/BioLink-Protector"),
            InlineKeyboardButton("🛠️ Support", url="https://t.me/TeamsXchat"),
        ],
        [InlineKeyboardButton("🗑️ Close", callback_data="close")],
    ])
    await message.reply_text(text, reply_markup=kb)


@app.on_message(filters.group & filters.command("config"))
async def configure(client: Client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await is_admin(client, chat_id, user_id):
        return

    mode, limit, penalty = await get_config(chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Warn", callback_data="warn")],
        [
            InlineKeyboardButton("Mute ✅" if penalty == "mute" else "Mute", callback_data="mute"),
            InlineKeyboardButton("Ban ✅" if penalty == "ban" else "Ban", callback_data="ban")
        ],
        [InlineKeyboardButton("Close", callback_data="close")]
    ])
    await client.send_message(
        chat_id,
        "**Choose penalty for users with links in bio:**",
        reply_markup=keyboard
    )
    await message.delete()


@app.on_message(filters.group & filters.command("free"))
async def command_free(client: Client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await is_admin(client, chat_id, user_id):
        return

    if message.reply_to_message:
        target = message.reply_to_message.from_user
    elif len(message.command) > 1:
        arg = message.command[1]
        target = await client.get_users(int(arg) if arg.isdigit() else arg)
    else:
        return await client.send_message(chat_id, "**Reply or use /free user or id to whitelist someone.**")

    await add_whitelist(chat_id, target.id)
    await reset_warnings(chat_id, target.id)

    text = f"**✅ {target.mention} has been added to the whitelist**"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚫 Unwhitelist", callback_data=f"unwhitelist_{target.id}"),
            InlineKeyboardButton("🗑️ Close", callback_data="close")
        ]
    ])
    await client.send_message(chat_id, text, reply_markup=keyboard)


@app.on_message(filters.group & filters.command("unfree"))
async def command_unfree(client: Client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await is_admin(client, chat_id, user_id):
        return

    if message.reply_to_message:
        target = message.reply_to_message.from_user
    elif len(message.command) > 1:
        arg = message.command[1]
        target = await client.get_users(int(arg) if arg.isdigit() else arg)
    else:
        return await client.send_message(chat_id, "**Reply or use /unfree user or id to unwhitelist someone.**")

    if await is_whitelisted(chat_id, target.id):
        await remove_whitelist(chat_id, target.id)
        text = f"**🚫 {target.mention} has been removed from the whitelist**"
    else:
        text = f"**ℹ️ {target.mention} is not whitelisted.**"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Whitelist", callback_data=f"whitelist_{target.id}"),
            InlineKeyboardButton("🗑️ Close", callback_data="close")
        ]
    ])
    await client.send_message(chat_id, text, reply_markup=keyboard)


@app.on_message(filters.group & filters.command("freelist"))
async def command_freelist(client: Client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await is_admin(client, chat_id, user_id):
        return

    ids = await get_whitelist(chat_id)
    if not ids:
        await client.send_message(chat_id, "**⚠️ No users are whitelisted in this group.**")
        return

    text = "**📋 Whitelisted Users:**\n\n"
    for i, uid in enumerate(ids, start=1):
        try:
            user = await client.get_users(uid)
            name = f"{user.first_name}{(' ' + user.last_name) if user.last_name else ''}"
            text += f"{i}: {name} [`{uid}`]\n"
        except Exception:
            text += f"{i}: [User not found] [`{uid}`]\n"

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Close", callback_data="close")]])
    await client.send_message(chat_id, text, reply_markup=keyboard)


@app.on_message(filters.group & filters.command("stats"))
async def stats_handler(client: Client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await is_admin(client, chat_id, user_id):
        return

    mode, limit, penalty = await get_config(chat_id)
    wl_count = await count_whitelist(chat_id)
    warn_records = await count_warning_records(chat_id)
    warn_total = await count_warnings(chat_id)

    text = (
        "**📊 Chat Protection Stats**\n\n"
        f"• Mode: `{mode}` | Penalty: `{penalty}` | Limit: `{limit}`\n"
        f"• Whitelisted users: `{wl_count}`\n"
        f"• Users with warnings: `{warn_records}`\n"
        f"• Total warning count: `{warn_total}`\n"
    )
    await message.reply_text(text)


@app.on_message(filters.private & filters.command("broadcast"))
async def broadcast_handler(client: Client, message):
    if OWNER_ID <= 0 or message.from_user.id != OWNER_ID:
        return

    if len(message.command) > 1:
        text = message.text.split(maxsplit=1)[1]
    elif message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""
    else:
        return await message.reply_text("Send /broadcast <text> or reply to a message.")

    chat_ids = await get_all_chats()
    if not chat_ids:
        return await message.reply_text("No chats registered.")

    await message.reply_text(f"Broadcasting to {len(chat_ids)} chats...")

    async def _send(cid: int):
        try:
            await client.send_message(cid, text)
        except errors.ChatWriteForbidden:
            pass
        except Exception:
            pass

    sem = asyncio.Semaphore(10)

    async def _worker(cid: int):
        async with sem:
            await _send(cid)
            await asyncio.sleep(0.1)

    await asyncio.gather(*(_worker(cid) for cid in chat_ids))
    await message.reply_text("Broadcast finished.")


@app.on_callback_query()
async def callback_handler(client: Client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    if not await is_admin(client, chat_id, user_id):
        return await callback_query.answer("❌ You are not administrator", show_alert=True)

    if data == "close":
        return await callback_query.message.delete()

    if data == "back":
        mode, limit, penalty = await get_config(chat_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Warn", callback_data="warn")],
            [
                InlineKeyboardButton("Mute ✅" if penalty == "mute" else "Mute", callback_data="mute"),
                InlineKeyboardButton("Ban ✅" if penalty == "ban" else "Ban", callback_data="ban")
            ],
            [InlineKeyboardButton("Close", callback_data="close")]
        ])
        await callback_query.message.edit_text("**Choose penalty for users with links in bio:**", reply_markup=kb)
        return await callback_query.answer()

    if data == "warn":
        _, selected_limit, _ = await get_config(chat_id)
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("5 ✅" if selected_limit == 5 else "5", callback_data="warn_5"),
                InlineKeyboardButton("10 ✅" if selected_limit == 10 else "10", callback_data="warn_10"),
                InlineKeyboardButton("15 ✅" if selected_limit == 15 else "15", callback_data="warn_15"),
            ],
            [InlineKeyboardButton("Back", callback_data="back"), InlineKeyboardButton("Close", callback_data="close")]
        ])
        return await callback_query.message.edit_text("**Select number of warns before penalty:**", reply_markup=kb)

    if data in ["mute", "ban"]:
        await update_config(chat_id, penalty=data)
        mode, limit, penalty = await get_config(chat_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Warn", callback_data="warn")],
            [
                InlineKeyboardButton("Mute ✅" if penalty == "mute" else "Mute", callback_data="mute"),
                InlineKeyboardButton("Ban ✅" if penalty == "ban" else "Ban", callback_data="ban")
            ],
            [InlineKeyboardButton("Close", callback_data="close")]
        ])
        await callback_query.message.edit_text("**Punishment selected:**", reply_markup=kb)
        return await callback_query.answer()

    if data.startswith("warn_"):
        count = int(data.split("_")[1])
        await update_config(chat_id, limit=count)
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("5 ✅" if count == 5 else "5", callback_data="warn_5"),
                InlineKeyboardButton("10 ✅" if count == 10 else "10", callback_data="warn_10"),
                InlineKeyboardButton("15 ✅" if count == 15 else "15", callback_data="warn_15"),
            ],
            [InlineKeyboardButton("Back", callback_data="back"), InlineKeyboardButton("Close", callback_data="close")]
        ])
        await callback_query.message.edit_text(f"**Warning limit set to {count}**", reply_markup=kb)
        return await callback_query.answer()

    if data.startswith(("unmute_", "unban_")):
        action, uid = data.split("_")
        target_id = int(uid)
        user = await client.get_users(target_id)
        name = f"{user.first_name}{(' ' + user.last_name) if user.last_name else ''}"
        try:
            if action == "unmute":
                await client.restrict_chat_member(chat_id, target_id, ChatPermissions(can_send_messages=True))
            else:
                await client.unban_chat_member(chat_id, target_id)
            await reset_warnings(chat_id, target_id)
            msg = f"**{name} (`{target_id}`) has been {'unmuted' if action == 'unmute' else 'unbanned'}**."
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Whitelist ✅", callback_data=f"whitelist_{target_id}"),
                    InlineKeyboardButton("🗑️ Close", callback_data="close")
                ]
            ])
            await callback_query.message.edit_text(msg, reply_markup=kb)
        except errors.ChatAdminRequired:
            await callback_query.message.edit_text(f"I don't have permission to {action} users.")
        return await callback_query.answer()

    if data.startswith("cancel_warn_"):
        target_id = int(data.split("_")[-1])
        await reset_warnings(chat_id, target_id)
        user = await client.get_users(target_id)
        full_name = f"{user.first_name}{(' ' + user.last_name) if user.last_name else ''}"
        mention = f"[{full_name}](tg://user?id={target_id})"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Whitelist✅", callback_data=f"whitelist_{target_id}"),
                InlineKeyboardButton("🗑️ Close", callback_data="close")
            ]
        ])
        await callback_query.message.edit_text(
            f"**✅ {mention} [`{target_id}`] has no more warnings!**", reply_markup=kb
        )
        return await callback_query.answer()

    if data.startswith("whitelist_"):
        target_id = int(data.split("_")[1])
        await add_whitelist(chat_id, target_id)
        await reset_warnings(chat_id, target_id)
        user = await client.get_users(target_id)
        full_name = f"{user.first_name}{(' ' + user.last_name) if user.last_name else ''}"
        mention = f"[{full_name}](tg://user?id={target_id})"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚫 Unwhitelist", callback_data=f"unwhitelist_{target_id}"),
                InlineKeyboardButton("🗑️ Close", callback_data="close")
            ]
        ])
        await callback_query.message.edit_text(
            f"**✅ {mention} [`{target_id}`] has been whitelisted!**", reply_markup=kb
        )
        return await callback_query.answer()

    if data.startswith("unwhitelist_"):
        target_id = int(data.split("_")[1])
        await remove_whitelist(chat_id, target_id)
        user = await client.get_users(target_id)
        full_name = f"{user.first_name}{(' ' + user.last_name) if user.last_name else ''}"
        mention = f"[{full_name}](tg://user?id={target_id})"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Whitelist✅", callback_data=f"whitelist_{target_id}"),
                InlineKeyboardButton("🗑️ Close", callback_data="close")
            ]
        ])
        await callback_query.message.edit_text(
            f"**❌ {mention} [`{target_id}`] has been removed from whitelist.**", reply_markup=kb
        )
        return await callback_query.answer()


@app.on_message(filters.group)
async def check_bio(client: Client, message):
    chat_id = message.chat.id
    await add_chat(chat_id)

    if not message.from_user or message.from_user.is_bot:
        return

    user_id = message.from_user.id
    if await is_admin(client, chat_id, user_id) or await is_whitelisted(chat_id, user_id):
        return

    bio, first_name, last_name = await get_user_profile_cached(client, user_id)

    full_name = f"{first_name}{(' ' + last_name) if last_name else ''}"
    mention = f"[{full_name}](tg://user?id={user_id})"

    is_spammer = register_message_event(chat_id, user_id)

    text_content = message.text or message.caption or ""
    bio_has_link = contains_link(bio)
    msg_has_link = contains_link(text_content) if text_content else False

    if bio_has_link or msg_has_link:
        if msg_has_link:
            try:
                await message.delete()
            except errors.MessageDeleteForbidden:
                await message.reply_text("Please grant me delete permission.")

        if is_spammer:
            try:
                _, _, penalty = await get_config(chat_id)
                if penalty == "mute":
                    await client.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False))
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unmute ✅", callback_data=f"unmute_{user_id}")]])
                    await message.reply_text(f"**{mention} has been 🔇 muted for mass spamming with link.**", reply_markup=kb)
                else:
                    await client.ban_chat_member(chat_id, user_id)
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unban ✅", callback_data=f"unban_{user_id}")]])
                    await message.reply_text(f"**{mention} has been 🔨 banned for mass spamming with link.**", reply_markup=kb)
            except errors.ChatAdminRequired:
                await message.reply_text("I don't have permission to restrict/ban users.")
            return

        mode, limit, penalty = await get_config(chat_id)
        reason_src = "message" if msg_has_link else "bio"
        if mode == "warn":
            count = await increment_warning(chat_id, user_id)
            warning_text = (
                "**🚨 Warning Issued** 🚨\n\n"
                f"👤 **User:** {mention} `[{user_id}]`\n"
                f"❌ **Reason:** URL found in {reason_src}\n"
                f"⚠️ **Warning:** {count}/{limit}\n\n"
                "**Notice: Please remove any links from your bio or messages.**"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("❌ Cancel Warning", callback_data=f"cancel_warn_{user_id}"),
                    InlineKeyboardButton("✅ Whitelist", callback_data=f"whitelist_{user_id}"),
                ],
                [InlineKeyboardButton("🗑️ Close", callback_data="close")]
            ])
            sent = await message.reply_text(warning_text, reply_markup=keyboard)
            if count >= limit:
                try:
                    if penalty == "mute":
                        await client.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False))
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unmute ✅", callback_data=f"unmute_{user_id}")]])
                        await sent.edit_text(f"**{mention} has been 🔇 muted for [Link In {reason_src.capitalize()}].**", reply_markup=kb)
                    else:
                        await client.ban_chat_member(chat_id, user_id)
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unban ✅", callback_data=f"unban_{user_id}")]])
                        await sent.edit_text(f"**{mention} has been 🔨 banned for [Link In {reason_src.capitalize()}].**", reply_markup=kb)
                except errors.ChatAdminRequired:
                    await sent.edit_text(f"**I don't have permission to {penalty} users.**")
        else:
            try:
                if mode == "mute":
                    await client.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False))
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unmute", callback_data=f"unmute_{user_id}")]])
                    await message.reply_text(f"{mention} has been 🔇 muted for [Link In {reason_src.capitalize()}].", reply_markup=kb)
                else:
                    await client.ban_chat_member(chat_id, user_id)
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Unban", callback_data=f"unban_{user_id}")]])
                    await message.reply_text(f"{mention} has been 🔨 banned for [Link In {reason_src.capitalize()}].", reply_markup=kb)
            except errors.ChatAdminRequired:
                return await message.reply_text(f"I don't have permission to {mode} users.")
    else:
        await reset_warnings(chat_id, user_id)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    app.run()
