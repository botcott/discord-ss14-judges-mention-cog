import asyncio
import datetime
import json
import logging
import os
import re

import discord
from discord.ext import commands

with open(f"{os.path.dirname(__file__)}/config/config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

APPEAL_CHANNEL_ID = int(cfg["appeal_channel_id"])
GUILD_ID = int(cfg["guild_id"])
ENABLE_MENTION = bool(cfg["enable_mention"])
MENTION_ON_VACATION = bool(cfg["mention_on_vacation"])
JUDGE_ROLE_ID = int(cfg["judge_role_id"])
VACATION_ROLE_ID = int(cfg["vacation_role_id"])

IGNORE_WORDS = ["перма дк", "пдк"]


async def get_members_without_vacation(members_with_judge):
    return [member for member in members_with_judge
            if not any(role.id == VACATION_ROLE_ID for role in member.roles)]


async def get_member_ids_without_vacation(members_with_judge):
    return [member.id for member in await get_members_without_vacation(members_with_judge)]


class JudgesMentionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.message_wait_timeout = 15

    async def is_appeal_forum_thread(self, thread):
        return (isinstance(thread.parent, discord.ForumChannel)
                and thread.parent.id == APPEAL_CHANNEL_ID)

    def contains_ignore_words(self, content):
        content_lower = content.lower()
        return any(re.search(keyword, content_lower) for keyword in IGNORE_WORDS)

    async def get_judge_members(self, guild):
        judge_role = guild.get_role(JUDGE_ROLE_ID)
        if not judge_role:
            self.logger.error(f"Роль судьи с ID {JUDGE_ROLE_ID} не найдена")
            return None

        members = judge_role.members
        if not members:
            self.logger.warning("Пользователей с ролью судья не обнаружено")
            return None

        return members

    def create_mentions_string(self, member_ids):
        mentions = " ".join(f"<@{member_id}>" for member_id in member_ids)
        return f"Пинг судей: {mentions}" if mentions else ""

    def log_mention_info(self, thread_url, members):
        judges_info = " ".join(f"{member.name}:{member.id}" for member in members)

        self.logger.info(
            f"Создание нового обжалования\n"
            f"Время: {datetime.datetime.now()}, Ссылка: {thread_url}\n"
            f"Упомянуто судей: {len(members)}\n"
            f"Список: {judges_info}"
        )

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if not ENABLE_MENTION or not await self.is_appeal_forum_thread(thread):
            return

        try:
            def check(message):
                return message.channel.id == thread.id and not message.author.bot

            first_message = await self.bot.wait_for(
                'message',
                check=check,
                timeout=self.message_wait_timeout
            )

        except asyncio.TimeoutError:
            self.logger.warning(f"Таймаут ожидания сообщения в треде {thread.id}")
            return
        except Exception as e:
            self.logger.error(f"Ошибка при ожидании сообщения в треде {thread.id}: {e}")
            return

        if self.contains_ignore_words(first_message.content):
            self.logger.info("Создано обжалование с ПДК, пропуск")
            return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            self.logger.error(f"Гильдия с ID {GUILD_ID} не найдена")
            return

        judge_members = await self.get_judge_members(guild)
        if not judge_members:
            return

        if MENTION_ON_VACATION:
            members_to_mention = judge_members
            member_ids_to_mention = [member.id for member in judge_members]
        else:
            members_to_mention = await get_members_without_vacation(judge_members)
            member_ids_to_mention = [member.id for member in members_to_mention]

        if not member_ids_to_mention:
            self.logger.info("Нет судей для упоминания")
            return

        mentions_string = self.create_mentions_string(member_ids_to_mention)
        if mentions_string:
            await thread.send(mentions_string)

        self.log_mention_info(thread.jump_url, members_to_mention)
