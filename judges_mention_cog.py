import os
import re
import json
import datetime
import logging
import asyncio

import discord
from discord.ext import commands

with open(f"{os.path.dirname(__file__)}/config/config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

appeal_channel_id = int(cfg["appeal_channel_id"])
guild_id = int(cfg["guild_id"])

enable_mention = bool(cfg["enable_mention"])
mention_on_vacation = bool(cfg["mention_on_vacation"])

judge_role_id = int(cfg["judge_role_id"])
vacation_role_id = int(cfg["vacation_role_id"])

async def get_nicknames_without_vacation(members_with_judge: list, vacation_role_id: int) -> list:
    """ 
        Returns nicknames list without vacation
    """
    nicknames_without_vacation = []

    if not members_with_judge:
        return nicknames_without_vacation

    for member in members_with_judge:
        role_ids = {role.id for role in member.roles}
        if vacation_role_id not in role_ids:
            nicknames_without_vacation.append(member.id)

    return nicknames_without_vacation

async def get_members_without_vacation(members_with_judge: list, vacation_role_id: int) -> list:
    """ 
        Returns members list without vacation
    """
    members_without_vacation = []

    if not members_with_judge:
        return members_without_vacation

    for member in members_with_judge:
        role_ids = {role.id for role in member.roles}
        if vacation_role_id not in role_ids:
            members_without_vacation.append(member)

    return members_without_vacation

class JudgesMentionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        self.max_wait_time = 15

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        """
            This event is triggered when someone creates a post in the forum.
        """

        check = ["перма дк", "пдк"]
        message = await self.wait_for_message(thread)
        if (not enable_mention): return
        if (not isinstance(thread.parent, discord.ForumChannel)): return
        if (thread.parent.id != appeal_channel_id): return
        
        for word in check:
            if (re.search(word, message.content.lower())):
                self.logger.info("Создано обжалование с ПДК, пропуск")
                return

        guild = self.bot.get_guild(guild_id)
        judge_role = guild.get_role(judge_role_id)

        if (not judge_role.members): 
            self.logger.warning("Пользователей с ролью судья не обнаружено")
            return

        mentions = "Пинг судей: "
        members_list = []

        if (mention_on_vacation):
            for member in judge_role.members:
                mentions += f"<@{member.id}> "
                members_list.append(member)
        else:
            without_vacation = await get_nicknames_without_vacation(judge_role.members, vacation_role_id)
            members_list = await get_members_without_vacation(judge_role.members, vacation_role_id)
            
            if (not without_vacation): return
            for id in without_vacation:
                mentions += f"<@{id}> "

        await thread.send(mentions)

        thread_url = thread.jump_url
        judges_mention_names = ""

        for member in members_list:
            judges_mention_names += f"{member.name}:{member.id} "

        self.logger.info(f"Создание нового обжалования")
        self.logger.info(f"время: {datetime.datetime.now()}, ссылка на публикацию: {thread_url}")
        self.logger.info(f"было упомянуто: {len(members_list)} судей")
        self.logger.info(f"список упомянутых судей: {judges_mention_names}")

    async def wait_for_message(self, thread):
            """
                Wait for first message, if found - return if not - None
            """
            try:
                async for message in thread.history(limit=1, oldest_first=False):
                    return message
                
                await asyncio.sleep(2)
                
                async def check_message():
                    async for message in thread.history(limit=1, oldest_first=False):
                        return message
                    return None

                start_time = datetime.now()
                while (datetime.now() - start_time).seconds < self.max_wait_time:
                    message = await check_message()
                    if message:
                        return message
                    await asyncio.sleep(2)  # Проверяем каждые 2 секунды

                return None

            except Exception as e:
                self.logger.error(f"Ошибка при ожидании сообщения: {e}")
                return None

