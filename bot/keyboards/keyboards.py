from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from bot.locales import t


def language_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇦 Українська", callback_data="lang:ua")
    builder.button(text="🇷🇺 Русский", callback_data="lang:ru")
    builder.button(text="🇺🇸 English", callback_data="lang:en")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_keyboard(language: str = "en", is_admin: bool = False, is_premium: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=t("btn_search", language))
    builder.button(text=t("btn_profile", language))

    if is_premium or is_admin:
        builder.button(text=t("btn_screenshot_search", language))
        builder.button(text=t("btn_ai_chat", language))
    else:
        builder.button(text=t("btn_screenshot_search_locked", language))
        builder.button(text=t("btn_ai_chat_limited", language))

    builder.button(text=t("btn_history", language))
    builder.button(text=t("btn_favorites", language))
    builder.button(text=t("btn_premium", language))
    builder.button(text=t("btn_referral", language))
    builder.button(text=t("btn_settings", language))
    builder.button(text=t("btn_support", language))

    if is_admin:
        builder.button(text="🔧 Admin Panel")
        builder.adjust(2, 2, 2, 2, 2, 1)
    else:
        builder.adjust(2, 2, 2, 2, 2)

    return builder.as_markup(resize_keyboard=True)


def back_keyboard(language: str = "en") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=t("btn_back", language))
    builder.button(text=t("btn_main_menu", language))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def game_result_keyboard(
    game_id: str,
    game_name: str,
    language: str = "en",
    is_favorite: bool = False,
    page: int = 1,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_favorite:
        builder.button(text=t("btn_remove_favorite", language), callback_data=f"unfav:{game_id}")
    else:
        builder.button(text=t("btn_add_favorite", language), callback_data=f"fav:{game_id}:{game_name[:25]}")
    builder.button(text=t("btn_not_that", language), callback_data="search:again")
    builder.button(text=t("btn_more_results", language), callback_data=f"search:more:{page + 1}")
    builder.adjust(1, 2)
    return builder.as_markup()


def premium_keyboard(language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_7days", language), callback_data="premium:7")
    builder.button(text=t("btn_30days", language), callback_data="premium:30")
    builder.button(text=t("btn_90days", language), callback_data="premium:90")
    builder.button(text=t("btn_forever", language), callback_data="premium:forever")
    builder.adjust(1)
    return builder.as_markup()


def payment_method_keyboard(tariff: str, language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_pay_card", language), callback_data=f"pay:card:{tariff}")
    builder.button(text=t("btn_pay_stars", language), callback_data=f"pay:stars:{tariff}")
    builder.adjust(1)
    return builder.as_markup()


def stars_payment_keyboard(tariff: str, stars: int, language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("btn_pay_now", language, stars=stars),
        callback_data=f"stars:pay:{tariff}:{stars}",
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_payment_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"admin:pay:approve:{payment_id}")
    builder.button(text="❌ Reject", callback_data=f"admin:pay:reject:{payment_id}")
    builder.adjust(2)
    return builder.as_markup()


def admin_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin:stats")
    builder.button(text="👥 Користувачі", callback_data="admin:users")
    builder.button(text="💳 Платежі", callback_data="admin:payments")
    builder.button(text="📨 Тікети", callback_data="admin:support")
    builder.button(text="📢 Розсилка", callback_data="admin:broadcast")
    builder.button(text="⭐ Видати Premium", callback_data="admin:give_premium")
    builder.button(text="❌ Забрати Premium", callback_data="admin:remove_premium")
    builder.button(text="🚫 Заблокувати", callback_data="admin:ban")
    builder.button(text="✅ Розблокувати", callback_data="admin:unban")
    builder.button(text="🔴 Вимкнути бота", callback_data="admin:bot:disable")
    builder.button(text="🟢 Увімкнути бота", callback_data="admin:bot:enable")
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def bot_disable_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, вимкнути", callback_data="admin:bot:disable:confirm")
    builder.button(text="❌ Скасувати", callback_data="admin:bot:cancel")
    builder.adjust(2)
    return builder.as_markup()


def admin_support_ticket_keyboard(ticket_id: int, user_telegram_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Відповісти", callback_data=f"admin:support:reply:{ticket_id}:{user_telegram_id}")
    builder.button(text="✅ Закрити", callback_data=f"admin:support:close:{ticket_id}")
    builder.adjust(2)
    return builder.as_markup()


def settings_keyboard(language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_change_language", language), callback_data="settings:language")
    builder.adjust(1)
    return builder.as_markup()


def referral_keyboard(link: str, language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("btn_share_link", language),
        url=f"https://t.me/share/url?url={link}&text=🎮+Find+games+from+memory!",
    )
    builder.adjust(1)
    return builder.as_markup()


def favorites_keyboard(favorites: list, language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for fav in favorites[:10]:
        builder.button(text=f"🎮 {fav.game_name[:30]}", callback_data=f"fav:view:{fav.game_id}")
    builder.button(text=t("btn_back", language), callback_data="menu:back")
    builder.adjust(1)
    return builder.as_markup()


def ai_chat_keyboard(language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_ai_chat_clear", language), callback_data="aichat:clear")
    builder.button(text=t("btn_back", language), callback_data="menu:back")
    builder.adjust(1)
    return builder.as_markup()


def upgrade_premium_keyboard(language: str = "en") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_premium", language), callback_data="menu:premium")
    builder.adjust(1)
    return builder.as_markup()
