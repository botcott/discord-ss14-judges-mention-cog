import asyncio
import datetime
import json
import logging
import os
import re

import discord
import httpx
from discord.ext import commands

from player_api.player_api import player_api
from .crud import BansInfo

with open(f"{os.path.dirname(__file__)}/config/config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

APPEAL_CHANNEL_ID = int(cfg["appeal_channel_id"])
GUILD_ID = int(cfg["guild_id"])
ENABLE_MENTION = bool(cfg["enable_mention"])
MENTION_ON_VACATION = bool(cfg["mention_on_vacation"])
JUDGE_ROLE_ID = int(cfg["judge_role_id"])
VACATION_ROLE_ID = int(cfg["vacation_role_id"])

LINK_FOR_CONNECT_DISCORD = cfg["link_for_connect_discord"]
CONNECTION_LINK_API_KEY = cfg["connection_link_api_key"]

PDK_WORDS = ["перма дк", "пдк", "перманентная блокировка дк"]
BVO_WORDS = ["бво", "без возможности обжаловат"]
ROLES_FOR_BVO = [1425845377499926679, 1425845451789439096]

logger = logging.getLogger(__name__)


async def get_members_without_vacation(members_with_judge):
    return [member for member in members_with_judge
            if not any(role.id == VACATION_ROLE_ID for role in member.roles)]

async def get_connection_url(member_id: int):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{LINK_FOR_CONNECT_DISCORD}/{member_id}",
                headers={"X-API-Key": CONNECTION_LINK_API_KEY}
            )

            if response.status_code != 200:
                return None

            data = response.json()
            url = data.get("Url")
        except Exception as e:
            logger.warning(f"Error with generating URL for connect Discord: {e}")
            return None
        return url


def create_mentions_string(member_ids):
    mentions = " ".join(f"<@{member_id}>" for member_id in member_ids)
    return f"Пинг судей: {mentions}" if mentions else ""


async def get_judge_members(guild):
    judge_role = guild.get_role(JUDGE_ROLE_ID)
    if not judge_role:
        logger.error(f"Роль судьи с ID {JUDGE_ROLE_ID} не найдена")
        return None

    members = judge_role.members
    if not members:
        logger.warning("Пользователей с ролью судья не обнаружено")
        return None

    return members


def contains_pdk_words(content):
    content_lower = content.lower()
    return any(re.search(keyword, content_lower) for keyword in PDK_WORDS)


def contains_BVO_words(content):
    content_lower = content.lower()
    return any(re.search(keyword, content_lower) for keyword in BVO_WORDS)


class JudgesMentionCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.logger = logger
        self.message_wait_timeout = 15
        self.appeal_view = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self.appeal_view is None:
            self.appeal_view = AppealMenuButtonView()
            self.bot.add_view(self.appeal_view)

    async def is_appeal_forum_thread(self, thread):
        return (isinstance(thread.parent, discord.ForumChannel)
                and thread.parent.id == APPEAL_CHANNEL_ID)

    def log_appeal_creation(self, thread_url, author_name):
        self.logger.info(
            f"Создано новое обжалование | "
            f"Автор: {author_name} | "
            f"Время: {datetime.datetime.now()} | "
            f"Ссылка: {thread_url}"
        )

    def log_judge_mention(self, thread_url, judge_count):
        self.logger.info(
            f"Вызваны судьи | "
            f"Количество: {judge_count} | "
            f"Время: {datetime.datetime.now()} | "
            f"Ссылка: {thread_url}"
        )

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if not ENABLE_MENTION or not await self.is_appeal_forum_thread(thread):
            return

        try:
            def check(message):
                return message.channel.id == thread.id and not message.author.bot

            first_message: discord.Message = await self.bot.wait_for(
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

        menu_view = AppealMenuButtonView()
        await thread.send("Чтобы обжалование было рассмотрено, обязательно нажмите на кнопку снизу (Доступно только "
                          "автору обжалования) и выполните дальнейшие инструкции:", view=menu_view)
        self.log_appeal_creation(thread.jump_url, first_message.author.name)


class AppealMenuButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def get_auth_discord_view(self, member: discord.Member):
        url = await get_connection_url(member.id)
        if not url:
            return None

        button = discord.ui.Button(
            label="Быстрая привязка SS14 к Discord",
            url=url,
            style=discord.ButtonStyle.link
        )

        view = discord.ui.View()
        view.add_item(button)
        return view

    @discord.ui.button(label="Меню", style=discord.ButtonStyle.primary, custom_id="appeal_menu:main")
    async def menu_button(self, button: discord.Button, interaction: discord.Interaction):
        thread: discord.Thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            return

        author_id = thread.owner_id

        if interaction.user.id != author_id:
            await interaction.response.send_message("Это меню доступно только автору обращения", ephemeral=True)
            return

        player = await player_api.get_player_info(discord_id=author_id)
        if not player or not player.get("userId"):
            view = await self.get_auth_discord_view(interaction.user)
            if not view:
                await interaction.response.send_message(
                    f"{thread.owner.mention} вы не привязали Дискорд в игре. "
                    f"Многие функции по обжалованию вам недоступны. Однако сейчас функционал по привязке временно не "
                    f"работает. Попробуйте немного позднее или обратитесь к администратору"
                )
                return
            await interaction.response.send_message(
                f"{thread.owner.mention} вы не привязали Дискорд в игре. "
                f"Многие функции по обжалованию вам недоступны. Сперва привяжи Дискорд, затем нажми кнопку 'Меню' "
                f"повторно", view=await self.get_auth_discord_view(interaction.user), ephemeral=True)
            return

        user_id = player["userId"]
        sub_menu_view = AppealSubMenuView(author_id=author_id, user_id=user_id)
        await interaction.response.send_message(
            "Выберите тип наказания:",
            view=sub_menu_view,
            ephemeral=True
        )


class AppealSubMenuView(discord.ui.View):
    def __init__(self, author_id: int, user_id: str):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.user_id = user_id

    @discord.ui.button(label="Серверные баны", style=discord.ButtonStyle.secondary, custom_id="appeal_menu:serverbans")
    async def server_bans_button(self, button: discord.Button, interaction: discord.Interaction):
        bans = await BansInfo.get_all_active_bans(self.user_id)
        if not bans:
            await interaction.response.send_message("У вас нет активных серверных банов.", ephemeral=True)
            return
        view = BanSelectionView(self.author_id, self.user_id, bans, ban_type="server")
        await interaction.response.send_message("Ваши серверные баны:", view=view, ephemeral=True)

    @discord.ui.button(label="Ролевые баны", style=discord.ButtonStyle.secondary, custom_id="appeal_menu:rolebans")
    async def role_bans_button(self, button: discord.Button, interaction: discord.Interaction):
        role_bans = await BansInfo.get_all_active_role_bans(self.user_id)
        if not role_bans:
            await interaction.response.send_message("У вас нет активных ролевых банов.", ephemeral=True)
            return
        view = BanSelectionView(self.author_id, self.user_id, role_bans, ban_type="role")
        await interaction.response.send_message("Ваши ролевые баны (Если забанено несколько ролей, выберите одну "
                                                "любую):",
                                                view=view, ephemeral=True)

    @discord.ui.button(label="Предупреждения", style=discord.ButtonStyle.secondary, custom_id="appeal_menu:notes")
    async def notes_button(self, button: discord.Button, interaction: discord.Interaction):
        notes = await BansInfo.get_all_active_notes(self.user_id)
        if not notes:
            await interaction.response.send_message("У вас нет активных предупреждений.", ephemeral=True)
            return
        view = BanSelectionView(self.author_id, self.user_id, notes, ban_type="note")
        await interaction.response.send_message("Ваши предупреждения:", view=view, ephemeral=True)


class BanSelectionView(discord.ui.View):
    def __init__(self, author_id: int, user_id: str, items, ban_type: str):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.user_id = user_id
        self.items = items
        self.ban_type = ban_type

        if ban_type == "server":
            options = []
            for i, item in enumerate(items):
                label = f"#{i + 1} | от {item.ban_time.strftime('%Y-%m-%d')} | "
                options.append(discord.SelectOption(
                    label=label + item.reason[:100 - len(label)],
                    value=str(i)))
            # options = [
            #     discord.SelectOption(
            #         label=f"#{i + 1} | от {item.reason[:80] if hasattr(item, 'reason') else 'Без причины'}...",
            #         value=str(i)
            #     )
            #     for i, item in enumerate(items)
            # ]
        elif ban_type == "role":
            options = []
            for i, item in enumerate(items):
                label = f"#{i + 1} | от {item.ban_time.strftime('%Y-%m-%d')} | {item.role_id} | "
                options.append(
                    discord.SelectOption(
                        label=label + item.reason[:100 - len(label)],
                        value=str(i)
                    )
                )
            # options = [
            #     discord.SelectOption(
            #         label=f"#{i + 1} | {item.role_id}"
            #               f" | {item.reason[:60] if hasattr(item, 'reason') else 'Без причины'}...",
            #         value=str(i)
            #     )
            #     for i, item in enumerate(items)
            # ]
        else:
            # Для notes
            options = [
                discord.SelectOption(
                    label=f"#{i + 1} | {item.message[:80] if hasattr(item, 'message') else 'Замечание'}...",
                    value=str(i)
                )
                for i, item in enumerate(items)
            ]

        self.add_item(BanSelect(options, self))


class BanSelect(discord.ui.Select):
    def __init__(self, options, parent_view: BanSelectionView):
        super().__init__(placeholder="Выберите из списка", min_values=1, max_values=1, options=options)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        interaction.response: discord.InteractionResponse
        idx = int(self.values[0])
        item = self.parent_view.items[idx]
        is_pdk = False
        is_bvo = False
        if self.parent_view.ban_type == "server":
            is_pdk = contains_pdk_words(getattr(item, 'reason', 'Не указано'))
            is_bvo = contains_BVO_words(getattr(item, 'reason', 'Не указано'))
            admin_id = item.banning_admin
            description = (
                f"**ID:** {item.server_ban_id}\n"
                f"**Кем выдано:** {getattr(item, 'banning_admin', 'Неизвестно')}\n"
                f"**Причина:** {getattr(item, 'reason', 'Не указано')}\n"
                f"**Дата выдачи:** {item.ban_time.strftime('%Y-%m-%d %H:%M') if item.ban_time else 'Неизвестно'}\n"
                f"**Истекает:** {item.expiration_time.strftime('%Y-%m-%d %H:%M') if item.expiration_time else 'Нет срока'}"
            )
        elif self.parent_view.ban_type == "role":
            admin_id = item.banning_admin
            description = (
                f"**ID:** {item.server_role_ban_id}\n"
                f"**Кем выдано:** {getattr(item, 'banning_admin', 'Неизвестно')}\n"
                f"**Роль:** {getattr(item, 'role_id', 'Не указано')}\n"
                f"**Причина:** {getattr(item, 'reason', 'Не указано')}\n"
                f"**Дата выдачи:** {item.ban_time.strftime('%Y-%m-%d %H:%M') if item.ban_time else 'Неизвестно'}\n"
                f"**Истекает:** {item.expiration_time.strftime('%Y-%m-%d %H:%M') if item.expiration_time else 'Нет срока'}"
            )
        else:  # note
            admin_id = item.created_by_id
            description = (
                f"**ID:** {item.admin_notes_id}\n"
                f"**Кем выдано:** {getattr(item, 'created_by_id', 'Неизвестно')}\n"
                f"**Причина:** {getattr(item, 'message', 'Не указано')}\n"
                f"**Дата выдачи:** {item.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(item, 'created_at') else 'Неизвестно'}\n"
                f"**Истекает:** {item.expiration_time.strftime('%Y-%m-%d %H:%M') if item.expiration_time else 'Нет срока'}"
            )

        await interaction.response.send_message(description)

        if is_bvo:
            await interaction.followup.send(f"Для разбора БВО приглашаются "
                                            f"{' '.join([f'<@&{role_id}>' for role_id in ROLES_FOR_BVO])}")
            return

        admin = await player_api.get_player_info(player_id=admin_id)

        if not admin or not admin.get("discordId"):
            await interaction.followup.send(f"Админ с userId ``{admin_id}`` не найден. Вызываю судей")
        else:
            await interaction.followup.send(f"Вызов админа, выдавшего бан: <@{admin.get("discordId")}>")

        if not is_pdk or not admin or not admin.get("discordId"):
            guild = interaction.guild
            if not guild:
                logger.error(f"Гильдия с ID {GUILD_ID} не найдена")
                return

            judge_members = await get_judge_members(guild)
            if not judge_members:
                return

            if not MENTION_ON_VACATION:
                judge_members = await get_members_without_vacation(judge_members)

            if not judge_members:
                logger.info("Нет судей вызова")
                return
            await interaction.followup.send(f"Активные судьи: "
                                            f"{create_mentions_string([judge.id for judge in judge_members])}."
                                            f"Ожидайте их ответа")
