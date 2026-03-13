import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiohttp
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Хранилище алертов: {user_id: [{coin, percent, direction, interval_min, price_at_set}]}
user_alerts: dict[int, list[dict]] = {}
# Цены при установке алерта: {user_id: {coin: price}}
alert_prices: dict[int, dict] = {}

COINS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "TON": "TONUSDT",
}

class AlertStates(StatesGroup):
    choosing_coin = State()
    choosing_percent = State()
    choosing_direction = State()
    choosing_interval = State()


async def get_price(symbol: str) -> float | None:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status == 200:
                data = await r.json()
                return float(data["price"])
    return None


def coins_keyboard():
    builder = InlineKeyboardBuilder()
    for coin in COINS:
        builder.button(text=coin, callback_data=f"coin_{coin}")
    builder.adjust(3)
    return builder.as_markup()


def direction_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Рост", callback_data="dir_up")
    builder.button(text="📉 Падение", callback_data="dir_down")
    builder.button(text="↕️ Оба", callback_data="dir_both")
    builder.adjust(3)
    return builder.as_markup()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "📊 <b>Crypto Alert Bot</b>\n\n"
        "Слежу за криптовалютами и шлю сигналы когда цена изменилась на нужный %.\n\n"
        "<b>Команды:</b>\n"
        "/alert — создать новый алерт\n"
        "/list — мои алерты\n"
        "/clear — удалить все алерты\n"
        "/prices — текущие цены"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("prices"))
async def cmd_prices(message: Message):
    lines = ["💹 <b>Текущие цены:</b>\n"]
    for coin, symbol in COINS.items():
        price = await get_price(symbol)
        if price:
            lines.append(f"<b>{coin}</b>: ${price:,.2f}")
        else:
            lines.append(f"<b>{coin}</b>: —")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("alert"))
async def cmd_alert(message: Message, state: FSMContext):
    await message.answer("Выбери монету:", reply_markup=coins_keyboard())
    await state.set_state(AlertStates.choosing_coin)


@dp.callback_query(AlertStates.choosing_coin, F.data.startswith("coin_"))
async def choose_coin(callback: CallbackQuery, state: FSMContext):
    coin = callback.data.split("_")[1]
    await state.update_data(coin=coin)
    price = await get_price(COINS[coin])
    price_text = f"${price:,.2f}" if price else "н/д"
    await callback.message.edit_text(
        f"<b>{coin}</b> сейчас: {price_text}\n\nНа сколько % должна измениться цена?\n"
        "Напиши число, например: <code>3</code> (это 3%)",
        parse_mode="HTML"
    )
    await state.set_state(AlertStates.choosing_percent)
    await callback.answer()


@dp.message(AlertStates.choosing_percent)
async def choose_percent(message: Message, state: FSMContext):
    try:
        percent = float(message.text.replace(",", ".").replace("%", ""))
        if percent <= 0 or percent > 100:
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 0.1 до 100, например: <code>2.5</code>", parse_mode="HTML")
        return
    await state.update_data(percent=percent)
    await message.answer(f"Порог: <b>{percent}%</b>\n\nКакое направление отслеживать?",
                         reply_markup=direction_keyboard(), parse_mode="HTML")
    await state.set_state(AlertStates.choosing_direction)


@dp.callback_query(AlertStates.choosing_direction, F.data.startswith("dir_"))
async def choose_direction(callback: CallbackQuery, state: FSMContext):
    direction = callback.data.split("_")[1]
    await state.update_data(direction=direction)
    await callback.message.edit_text(
        "Как часто проверять цену?\n\nНапиши интервал в минутах, например: <code>5</code>",
        parse_mode="HTML"
    )
    await state.set_state(AlertStates.choosing_interval)
    await callback.answer()


@dp.callback_query(AlertStates.choosing_interval)
async def choose_interval_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()


@dp.message(AlertStates.choosing_interval)
async def choose_interval(message: Message, state: FSMContext):
    try:
        interval = int(message.text.strip())
        if interval < 1 or interval > 1440:
            raise ValueError
    except ValueError:
        await message.answer("Введи целое число минут от 1 до 1440:")
        return

    data = await state.get_data()
    coin = data["coin"]
    percent = data["percent"]
    direction = data["direction"]

    current_price = await get_price(COINS[coin])
    if not current_price:
        await message.answer("Не удалось получить цену. Попробуй позже.")
        await state.clear()
        return

    uid = message.from_user.id
    if uid not in user_alerts:
        user_alerts[uid] = []
    if uid not in alert_prices:
        alert_prices[uid] = {}

    alert_prices[uid][f"{coin}_{len(user_alerts[uid])}"] = current_price
    user_alerts[uid].append({
        "id": len(user_alerts[uid]),
        "coin": coin,
        "percent": percent,
        "direction": direction,
        "interval": interval,
        "base_price": current_price,
        "last_check": datetime.now(),
    })

    dir_text = {"up": "📈 рост", "down": "📉 падение", "both": "↕️ рост и падение"}[direction]
    await message.answer(
        f"✅ <b>Алерт установлен!</b>\n\n"
        f"Монета: <b>{coin}</b>\n"
        f"Базовая цена: <b>${current_price:,.2f}</b>\n"
        f"Сигнал при: <b>{percent}%</b> ({dir_text})\n"
        f"Проверка каждые: <b>{interval} мин</b>",
        parse_mode="HTML"
    )
    await state.clear()


@dp.message(Command("list"))
async def cmd_list(message: Message):
    uid = message.from_user.id
    alerts = user_alerts.get(uid, [])
    if not alerts:
        await message.answer("У тебя нет активных алертов. /alert — создать")
        return
    lines = ["🔔 <b>Твои алерты:</b>\n"]
    for i, a in enumerate(alerts, 1):
        dir_text = {"up": "📈", "down": "📉", "both": "↕️"}[a["direction"]]
        lines.append(
            f"{i}. <b>{a['coin']}</b> {dir_text} {a['percent']}% | "
            f"база ${a['base_price']:,.2f} | каждые {a['interval']}мин"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    uid = message.from_user.id
    user_alerts[uid] = []
    await message.answer("🗑 Все алерты удалены.")


async def check_alerts():
    """Фоновая задача — проверяет алерты каждую минуту"""
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        for uid, alerts in list(user_alerts.items()):
            for alert in alerts:
                mins_passed = (now - alert["last_check"]).total_seconds() / 60
                if mins_passed < alert["interval"]:
                    continue
                alert["last_check"] = now
                price = await get_price(COINS[alert["coin"]])
                if not price:
                    continue
                base = alert["base_price"]
                change_pct = ((price - base) / base) * 100
                triggered = False
                direction_text = ""
                if alert["direction"] in ("up", "both") and change_pct >= alert["percent"]:
                    triggered = True
                    direction_text = f"📈 выросла на {change_pct:.2f}%"
                elif alert["direction"] in ("down", "both") and change_pct <= -alert["percent"]:
                    triggered = True
                    direction_text = f"📉 упала на {abs(change_pct):.2f}%"
                if triggered:
                    try:
                        await bot.send_message(
                            uid,
                            f"🚨 <b>СИГНАЛ: {alert['coin']}</b>\n\n"
                            f"Цена {direction_text}\n"
                            f"Было: <b>${base:,.2f}</b>\n"
                            f"Сейчас: <b>${price:,.2f}</b>\n\n"
                            f"Алерт сброшен. /alert — создать новый",
                            parse_mode="HTML"
                        )
                        alert["base_price"] = price  # сбрасываем базу
                    except Exception as e:
                        logging.error(f"Send error: {e}")


async def main():
    asyncio.create_task(check_alerts())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
