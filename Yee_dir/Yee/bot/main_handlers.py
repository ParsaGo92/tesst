
import logging
from typing import Any, Dict

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.user_manager import user_data_manager
from bot.keyboards import (
    get_main_keyboard,
    get_cancel_keyboard,
    get_filter_settings_keyboard,
    get_max_price_keyboard,
    get_max_cycle_keyboard,
    get_min_price_keyboard,
)
from bot.logger import log_command, log_button_click, log_charge, log_bot_error
from bot.messages import *
from gift.loader import gift_loader
from gift.sender import get_gift_sender
from bot.telegram_client import get_shared_client
from pyrogram.types import (
    InlineKeyboardMarkup as PyroInlineKeyboardMarkup,
    InlineKeyboardButton as PyroInlineKeyboardButton,
)


logger = logging.getLogger(__name__)


router = Router()

AUTHORIZED_USER_IDS = [
    6098807937,
    833333518,
]

user_main_messages = {}

def check_user_access(user_id: int) -> bool:
    return user_id in AUTHORIZED_USER_IDS

async def cleanup_previous_messages(chat_id: int, bot):
    try:
        if chat_id in user_main_messages:
            old_message_id = user_main_messages[chat_id]
            try:
                await bot.delete_message(chat_id, old_message_id)
            except Exception as e:
                logger.debug(f"Could not delete old message {old_message_id}: {e}")
    except Exception as e:
        logger.debug(f"Error in cleanup: {e}")

async def send_or_edit_main_message(message_or_callback, text: str, reply_markup=None, parse_mode="MarkdownV2"):
    user_id = message_or_callback.from_user.id
    chat_id = message_or_callback.chat.id if hasattr(message_or_callback, 'chat') else message_or_callback.message.chat.id
    
    if hasattr(message_or_callback, 'message'):
        await message_or_callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        user_main_messages[chat_id] = message_or_callback.message.message_id
    else:
        await cleanup_previous_messages(chat_id, message_or_callback.bot)
        new_message = await message_or_callback.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        user_main_messages[chat_id] = new_message.message_id


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    
    await state.clear()
    
    user_id = message.from_user.id
    
    username = message.from_user.username or "No Username"
    print(f"User trying to access bot: ID={user_id}, Username=@{username}")
    
    if not check_user_access(user_id):
        await message.answer(f"*❌ Access Denied*\n\nUser ID: `{user_id}`\nUsername: @{username}", parse_mode="MarkdownV2")
        return
    
    user_data = await user_data_manager.get_user_data(user_id)
    
    log_command(message, "start")
    
    autobuy_status = "On" if user_data['autobuy_enabled'] else "Off"
    filter_status = "On" if user_data['filter_enabled'] else "Off"
    
    message_text = format_main_menu(
        user_data['stars_balance'],
        autobuy_status,
        filter_status
    )
    
    await send_or_edit_main_message(
        message,
        message_text,
        reply_markup=get_main_keyboard(),
        parse_mode="MarkdownV2"
    )


@router.message(F.text == ".panel")
async def handle_panel(message: Message, state: FSMContext):
    """Handle .panel command using the user's account instead of the bot."""
    if not check_user_access(message.from_user.id):
        # Ignore unauthorized users without any response
        return

    await state.clear()
    user_id = message.from_user.id

    user_data = await user_data_manager.get_user_data(user_id)
    log_command(message, "panel")

    autobuy_status = "On" if user_data['autobuy_enabled'] else "Off"
    filter_status = "On" if user_data['filter_enabled'] else "Off"

    message_text = format_main_menu(
        user_data['stars_balance'],
        autobuy_status,
        filter_status,
    )

    client = get_shared_client()
    if client:
        aiogram_kb = get_main_keyboard()
        pyrogram_kb = PyroInlineKeyboardMarkup(
            [
                [
                    PyroInlineKeyboardButton(text=btn.text, callback_data=btn.callback_data)
                    for btn in row
                ]
                for row in aiogram_kb.inline_keyboard
            ]
        )
        await client.send_message(
            chat_id=message.chat.id,
            text=message_text,
            reply_markup=pyrogram_kb,
            parse_mode="markdown",
        )
    else:
        # Fallback to bot if client is unavailable
        await send_or_edit_main_message(
            message,
            message_text,
            reply_markup=get_main_keyboard(),
            parse_mode="MarkdownV2",
        )


@router.callback_query(F.data == "toggle_autobuy")
async def handle_toggle_autobuy(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return
        
    log_button_click(callback, "toggle_autobuy")
    user_id = callback.from_user.id
    new_state = await user_data_manager.toggle_autobuy(user_id)
    
    status = "Enabled" if new_state else "Disabled"
    
    try:
        await callback.message.edit_text(
            format_autobuy_toggled(status),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Back", callback_data="back_to_menu")]
            ]),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing autobuy message: {e}")
    await callback.answer(f"⚙️ AutoBuy {status}")

@router.callback_query(F.data == "view_balance")
async def show_balance(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return

    log_button_click(callback, "view_balance")
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    autobuy_status = "On" if user_data['autobuy_enabled'] else "Off"
    filter_status = "On" if user_data['filter_enabled'] else "Off"
    
    message = format_balance_view(
        user_data['stars_balance'],
        autobuy_status,
        filter_status,
        user_data.get('min_price_limit', 0),
        user_data['max_price_limit'],
        user_data['max_buy_per_cycle']
    )
    
    try:
        await callback.message.edit_text(
            message,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Back", callback_data="back_to_menu")]
            ]),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing balance message: {e}")
    await callback.answer("✅ Updated")

@router.callback_query(F.data == "view_gifts")
async def show_available_gifts(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    log_button_click(callback, "view_gifts")
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    try:
        all_gifts = await gift_loader.load_gifts()
        
        filtered_gifts = await gift_loader.filter_available_gifts(
            all_gifts,
            filter_limited_only=user_data['filter_enabled'],
            max_price=user_data['max_price_limit'],
            min_price=user_data.get('min_price_limit', 0)
        )
        
        available_gifts = filtered_gifts
        
        if not available_gifts:
            filter_status = "On" if user_data['filter_enabled'] else "Off"
            message = format_no_gifts_found(
                filter_status,
                user_data['max_price_limit'],
                user_data['stars_balance']
            )
            
            try:
                await callback.message.edit_text(
                    message,
                    reply_markup=get_main_keyboard(),
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                if "message is not modified" not in str(e):
                    logger.error(f"Error editing no gifts message: {e}")
        else:
            total_pages = max(1, (len(available_gifts) - 1) // 3 + 1)
            filter_status = "On" if user_data['filter_enabled'] else "Off"
            
            message = format_available_gifts(
                len(available_gifts),
                1,
                total_pages,
                filter_status,
                user_data['max_price_limit'],
                user_data['stars_balance']
            )
            
            keyboard = create_gifts_keyboard(available_gifts, 0, total_pages)
            
            try:
                await callback.message.edit_text(
                    message,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                if "message is not modified" not in str(e):
                    logger.error(f"Error editing gifts list: {e}")
            
    except Exception as e:
        logger.error(f"Error showing gifts: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            await callback.message.edit_text(
                f"Error Loading Gifts: {str(e)}",
                reply_markup=get_main_keyboard()
            )
        except:
            await callback.answer("Error loading gifts", show_alert=True)
    
    await callback.answer()

def create_gifts_keyboard(gifts, page, total_pages):
    keyboard = []
    
    start_idx = page * 3
    end_idx = min(start_idx + 3, len(gifts))
    
    for i in range(start_idx, end_idx):
        gift = gifts[i]
        gift_id = str(gift.get('gift_id', gift.get('id', 'Unknown')))
        stars = gift.get('stars', 0)
        short_id = gift_id[-4:] if len(gift_id) > 4 else gift_id
        
        button_text = f"Gift {short_id} - {stars}★"
        callback_data = f"view_gift:{gift_id}:{page}"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Prev",
            callback_data=f"gifts_page:{page-1}"
        ))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text="Next ▶️",
            callback_data=f"gifts_page:{page+1}"
        ))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(
        text="Back",
        callback_data="back_to_menu"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@router.callback_query(F.data.startswith("gifts_page:"))
async def handle_gifts_pagination(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Handle gifts page navigation"""
    log_button_click(callback, "gifts_pagination")
    page = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    try:
        all_gifts = await gift_loader.load_gifts()
        filtered_gifts = await gift_loader.filter_available_gifts(
            all_gifts,
            filter_limited_only=user_data['filter_enabled'],
            max_price=user_data['max_price_limit'],
            min_price=user_data.get('min_price_limit', 0)
        )
        
        available_gifts = filtered_gifts
        
        total_pages = max(1, (len(available_gifts) - 1) // 3 + 1)
        filter_status = "On" if user_data['filter_enabled'] else "Off"
        
        message = format_available_gifts(
            len(available_gifts),
            page + 1,
            total_pages,
            filter_status,
            user_data['max_price_limit'],
            user_data['stars_balance']
        )
        
        keyboard = create_gifts_keyboard(available_gifts, page, total_pages)
        
        await callback.message.edit_text(
            message,
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        
    except Exception as e:
        logger.error(f"Error in pagination: {e}")
    
    await callback.answer()

@router.callback_query(F.data.startswith("view_gift:"))
async def show_gift_detail(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Show individual gift details"""
    log_button_click(callback, "view_gift")
    parts = callback.data.split(":")
    gift_id = parts[1]
    page = int(parts[2])
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    try:

        all_gifts = await gift_loader.load_gifts()
        target_gift = None
        
        for gift in all_gifts:
            if str(gift.get('gift_id', gift.get('id', ''))) == gift_id:
                target_gift = gift
                break
        
        if not target_gift:
            await callback.message.edit_text(
                "*⚠️ Gift Not Found*\n\n_This gift is no longer available\\._",
                reply_markup=get_main_keyboard(),
                parse_mode="MarkdownV2"
            )
            await callback.answer()
            return
        
        stars = target_gift.get('stars', 0)
        available = target_gift.get('available_amount', 0)
        is_limited = target_gift.get('is_limited', False)
        
        message = format_gift_details(
            gift_id,
            stars,
            available,
            is_limited,
            user_data['stars_balance']
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Confirm Purchase",
                callback_data=f"confirm_purchase:{gift_id}:{page}"
            )],
            [InlineKeyboardButton(
                text="Back",
                callback_data="view_gifts"
            )]
        ])
        
        await callback.message.edit_text(
            message,
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        
    except Exception as e:
        logger.error(f"Error showing gift detail: {e}")
        await callback.message.edit_text(
            f"*⚠️ Error*\n\n{str(e)}",
            reply_markup=get_main_keyboard(),
            parse_mode="MarkdownV2"
        )
    
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_purchase:"))
async def confirm_gift_purchase(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Confirm and execute gift purchase"""
    log_button_click(callback, "confirm_purchase")
    parts = callback.data.split(":")
    gift_id = parts[1]
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    try:

        all_gifts = await gift_loader.load_gifts()
        target_gift = None
        
        for gift in all_gifts:
            if str(gift.get('gift_id', gift.get('id', ''))) == gift_id:
                target_gift = gift
                break
        
        if not target_gift:
            await callback.message.edit_text(
                "*⚠️ Gift Not Found*",
                reply_markup=get_main_keyboard(),
                parse_mode="MarkdownV2"
            )
            await callback.answer()
            return
        
        stars = target_gift.get('stars', 0)
        
        if user_data['stars_balance'] < stars:
            message = format_insufficient_stars(stars, user_data['stars_balance'])
            await callback.message.edit_text(
                message,
                reply_markup=get_main_keyboard(),
                parse_mode="MarkdownV2"
            )
            await callback.answer()
            return
        
        gift_sender = get_gift_sender(callback.bot)
        gift_sent = await gift_sender.send_gift_to_user(
            user_id=user_id,
            gift_id=gift_id
        )
        
        if gift_sent:
            new_balance = user_data['stars_balance'] - stars
            await user_data_manager.update_user_setting(user_id, 'stars_balance', new_balance)
            
            message = format_purchase_success(gift_id, stars, new_balance)
            
            await callback.message.edit_text(
                message,
                parse_mode="MarkdownV2"
            )
        else:
            await callback.message.edit_text(
                "*⚠️ Gift Purchase Failed*\n\nUnable to send gift\\. Please try again later\\.",
                reply_markup=get_main_keyboard(),
                parse_mode="MarkdownV2"
            )
        
    except Exception as e:
        logger.error(f"Error in purchase: {e}")
        await callback.message.edit_text(
            f"*⚠️ Purchase Error*\n\n{str(e)}",
            reply_markup=get_main_keyboard(),
            parse_mode="MarkdownV2"
        )
    
    await callback.answer()

@router.callback_query(F.data == "filter_settings")
async def handle_filter_settings(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return
    """Handle filter settings submenu"""
    log_button_click(callback, "filter_settings")
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    limited_status = "On" if user_data['filter_enabled'] else "Off"
    
    message_text = format_filter_settings(
        limited_status,
        user_data.get('min_price_limit', 0),
        user_data['max_price_limit'],
        user_data['max_buy_per_cycle']
    )
    
    try:
        await callback.message.edit_text(
            message_text,
            reply_markup=get_filter_settings_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing filter settings message: {e}")
    await callback.answer("⚙️ Settings")

@router.callback_query(F.data == "toggle_limited_filter")
async def handle_toggle_limited_filter(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Toggle limited filter setting"""
    log_button_click(callback, "toggle_limited_filter")
    user_id = callback.from_user.id
    new_state = await user_data_manager.toggle_filter(user_id)
    
    status = "On" if new_state else "Off"
    
    try:
        await callback.message.edit_text(
            format_filter_toggled(status),
            reply_markup=get_filter_settings_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing filter toggle: {e}")
    await callback.answer()

@router.callback_query(F.data == "set_max_price_menu")
async def handle_set_max_price_menu(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Show max price selection menu"""
    log_button_click(callback, "set_max_price_menu")
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    message = f"""*💰 Select Max Price*

*Current Setting:* `{user_data['max_price_limit']:,}` stars

_Choose your maximum price per gift:_"""
    
    try:
        await callback.message.edit_text(
            message, 
            reply_markup=get_max_price_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing max price menu: {e}")
    await callback.answer()

@router.callback_query(F.data.startswith("set_price:"))
async def handle_set_price(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return
    """Handle price selection"""
    log_button_click(callback, f"set_price")
    price = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    await user_data_manager.update_user_setting(user_id, 'max_price_limit', price)
    
    try:
        await callback.message.edit_text(
            format_price_set(price),
            reply_markup=get_filter_settings_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing price set: {e}")
    await callback.answer("✅ Max price updated")

@router.callback_query(F.data == "set_min_price_menu")
async def handle_set_min_price_menu(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Show min price selection menu"""
    log_button_click(callback, "set_min_price_menu")
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    message = f"""*💰 Select Min Price*

*Current Setting:* `{user_data.get('min_price_limit', 0):,}` stars

_Choose your minimum price per gift:_"""
    
    try:
        await callback.message.edit_text(
            message, 
            reply_markup=get_min_price_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing min price menu: {e}")
    await callback.answer()

@router.callback_query(F.data.startswith("set_min_price:"))
async def handle_set_min_price(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return
    """Handle min price selection"""
    log_button_click(callback, "set_min_price")
    price = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    await user_data_manager.update_user_setting(user_id, 'min_price_limit', price)
    
    try:
        await callback.message.edit_text(
            format_price_set(price),
            reply_markup=get_filter_settings_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing min price set: {e}")
    await callback.answer("✅ Min price updated")

@router.callback_query(F.data == "set_max_cycle_menu")
async def handle_set_max_cycle_menu(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Show max cycle selection menu"""
    log_button_click(callback, "set_max_cycle_menu")
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    message = f"""*🔄 Select Max Per Cycle*

*Current Setting:* `{user_data['max_buy_per_cycle']}`

_Choose max gifts per AutoBuy cycle:_"""
    
    try:
        await callback.message.edit_text(
            message, 
            reply_markup=get_max_cycle_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing max cycle menu: {e}")
    await callback.answer()

@router.callback_query(F.data.startswith("set_cycle:"))
async def handle_set_cycle(callback: CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("Bot is Private", show_alert=True)
        return
    """Handle cycle selection"""
    log_button_click(callback, "set_cycle")
    cycle = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    await user_data_manager.update_user_setting(user_id, 'max_buy_per_cycle', cycle)
    
    try:
        await callback.message.edit_text(
            format_cycle_set(cycle),
            reply_markup=get_filter_settings_keyboard(),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing cycle set: {e}")
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def handle_back_to_menu(callback: CallbackQuery, state: FSMContext):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return
    log_button_click(callback, "back_to_menu")
    await state.clear()
    
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    autobuy_status = "On" if user_data['autobuy_enabled'] else "Off"
    filter_status = "On" if user_data['filter_enabled'] else "Off"
    
    message_text = format_main_menu(
        user_data['stars_balance'],
        autobuy_status,
        filter_status
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_main_keyboard(),
        parse_mode="MarkdownV2"
    )
    await callback.answer("Back")

@router.callback_query(F.data == "cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext):
    if not check_user_access(callback.from_user.id):
        await callback.answer("❌ Access Denied", show_alert=True)
        return
    log_button_click(callback, "cancel")
    await state.clear()
    
    user_id = callback.from_user.id
    user_data = await user_data_manager.get_user_data(user_id)
    
    autobuy_status = "On" if user_data['autobuy_enabled'] else "Off"
    filter_status = "On" if user_data['filter_enabled'] else "Off"
    
    message_text = format_main_menu(
        user_data['stars_balance'],
        autobuy_status,
        filter_status
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=get_main_keyboard(),
        parse_mode="MarkdownV2"
    )
    await callback.answer("❌ Cancelled")