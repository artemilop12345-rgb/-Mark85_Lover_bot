"""
bot.py — Telegram-бот для розыгрышей с проверкой подписки на канал.

Сценарий использования:
1. Создатель пишет боту /create и проходит через несколько вопросов
   (приз, юзернейм канала для проверки подписки).
2. Бот создаёт розыгрыш и присылает сообщение с кнопкой "Участвовать",
   которое можно переслать или скопировать в канал.
3. Пользователь жмёт "Участвовать" → бот проверяет подписку на канал
   через getChatMember → если подписан, добавляет в участники.
4. Создатель завершает розыгрыш командой /finish <id>,
   бот случайно выбирает победителя и объявляет его.
"""

import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import database as db

# На Render токен передаётся через переменную окружения BOT_TOKEN
# (задаётся в панели Render, не хранится в коде).
# Локально, если переменной окружения нет, токен берётся из config.py.
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class CreateGiveaway(StatesGroup):
    """
    Состояния FSM (конечного автомата) для пошагового создания розыгрыша.
    Бот должен последовательно спросить приз, потом канал —
    эти состояния помогают ему "помнить", на каком шаге диалога мы находимся.
    """
    waiting_for_prize = State()
    waiting_for_channel = State()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я бот для розыгрышей.\n\n"
        "Команды:\n"
        "/create — создать новый розыгрыш\n"
        "/finish <id> — завершить розыгрыш и выбрать победителя\n"
        "/mygiveaways — список твоих розыгрышей"
    )


@dp.message(Command("create"))
async def cmd_create(message: Message, state: FSMContext):
    await message.answer("Какой приз ты разыгрываешь? Напиши текстом.")
    await state.set_state(CreateGiveaway.waiting_for_prize)


@dp.message(CreateGiveaway.waiting_for_prize)
async def process_prize(message: Message, state: FSMContext):
    await state.update_data(prize=message.text)
    await message.answer(
        "Теперь укажи юзернейм канала для проверки подписки.\n"
        "Например: @my_channel\n\n"
        "Важно: я должен быть администратором этого канала, "
        "иначе не смогу проверять подписку."
    )
    await state.set_state(CreateGiveaway.waiting_for_channel)


@dp.message(CreateGiveaway.waiting_for_channel)
async def process_channel(message: Message, state: FSMContext):
    channel_username = message.text.strip()
    if not channel_username.startswith("@"):
        await message.answer("Юзернейм канала должен начинаться с @. Попробуй ещё раз.")
        return

    data = await state.get_data()
    prize = data["prize"]

    try:
        bot_member = await bot.get_chat_member(channel_username, bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await message.answer(
                "Я не администратор этого канала. "
                "Добавь меня в админы канала и попробуй снова."
            )
            await state.clear()
            return
    except Exception as e:
        await message.answer(
            f"Не получилось проверить канал ({channel_username}). "
            "Убедись, что юзернейм верный и я добавлен в админы.\n"
            f"Техническая причина: {e}"
        )
        await state.clear()
        return

    giveaway_id = db.create_giveaway(
        creator_id=message.from_user.id,
        prize=prize,
        channel_username=channel_username,
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎉 Участвовать", callback_data=f"join_{giveaway_id}")]
    ])

    # Публикуем пост прямо в канал, чтобы кнопка точно работала
    # (при обычной пересылке Telegram не переносит инлайн-кнопки).
    try:
        await bot.send_message(
            chat_id=channel_username,
            text=f"🎁 Розыгрыш: {prize}\n\nЖми кнопку ниже, чтобы участвовать!",
            reply_markup=keyboard
        )
    except Exception as e:
        await message.answer(
            "Не получилось опубликовать пост в канал. "
            "Убедись, что у меня есть право публиковать сообщения "
            "(Администраторы → права бота → 'Публикация сообщений').\n"
            f"Техническая причина: {e}"
        )
        await state.clear()
        return

    await message.answer(
        f"Розыгрыш создан и опубликован в {channel_username}!\n\n"
        f"ID: {giveaway_id}\n"
        f"🎁 Приз: {prize}\n\n"
        f"Когда захочешь завершить розыгрыш, напиши: /finish {giveaway_id}"
    )

    await state.clear()


@dp.callback_query(F.data.startswith("join_"))
async def process_join(callback: CallbackQuery):
    giveaway_id = int(callback.data.split("_")[1])
    giveaway = db.get_giveaway(giveaway_id)

    if giveaway is None:
        await callback.answer("Этот розыгрыш не найден.", show_alert=True)
        return

    if giveaway["is_active"] == 0:
        await callback.answer("Этот розыгрыш уже завершён.", show_alert=True)
        return

    channel_username = giveaway["channel_username"]
    user_id = callback.from_user.id

    try:
        member = await bot.get_chat_member(channel_username, user_id)
        is_subscribed = member.status in ("member", "administrator", "creator")
    except Exception:
        is_subscribed = False

    if not is_subscribed:
        await callback.answer(
            f"Сначала подпишись на {channel_username}, потом жми кнопку снова!",
            show_alert=True
        )
        return

    added = db.add_participant(
        giveaway_id=giveaway_id,
        user_id=user_id,
        username=callback.from_user.username or callback.from_user.first_name,
    )

    if added:
        await callback.answer("Ты участвуешь в розыгрыше! Удачи 🍀", show_alert=True)
    else:
        await callback.answer("Ты уже участвуешь в этом розыгрыше.", show_alert=True)


@dp.message(Command("finish"))
async def cmd_finish(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Укажи ID розыгрыша: /finish <id>")
        return

    try:
        giveaway_id = int(command.args.strip())
    except ValueError:
        await message.answer("ID розыгрыша должен быть числом.")
        return

    giveaway = db.get_giveaway(giveaway_id)
    if giveaway is None:
        await message.answer("Розыгрыш с таким ID не найден.")
        return

    if giveaway["creator_id"] != message.from_user.id:
        await message.answer("Завершить розыгрыш может только его создатель.")
        return

    if giveaway["is_active"] == 0:
        await message.answer("Этот розыгрыш уже завершён.")
        return

    winner = db.pick_winner(giveaway_id)
    if winner is None:
        await message.answer("В этом розыгрыше пока нет участников.")
        return

    winner_name = f"@{winner['username']}" if winner["username"] else f"id{winner['user_id']}"
    await message.answer(
        f"🎉 Розыгрыш завершён!\n\n"
        f"🎁 Приз: {giveaway['prize']}\n"
        f"🏆 Победитель: {winner_name}"
    )


async def handle_health_check(request):
    """
    Простой ответ 'я живой' для внешних пингов (например, UptimeRobot).
    Render и подобные платформы видят такие запросы как 'активность'
    и не выключают сервис.
    """
    return web.Response(text="Bot is alive")


async def start_web_server():
    """Запускает минимальный веб-сервер на порту, который укажет Render."""
    app = web.Application()
    app.router.add_get("/", handle_health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Веб-сервер для health-check запущен на порту {port}")


async def main():
    db.init_db()
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot),
    )


if __name__ == "__main__":
    asyncio.run(main())