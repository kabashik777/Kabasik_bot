import os
import time
import sqlite3
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from telegram import Bot

# =========================
# НАСТРОЙКИ
# =========================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MAX_PRICE = 7000
CHECK_INTERVAL = 180  # 3 минуты

OLX_URL = (
    "https://www.olx.pl/motoryzacja/samochody-osobowe/"
    "?search%5Bfilter_float_price%3Ato%5D=7000"
    "&search%5Border%5D=created_at%3Adesc"
)

DB_FILE = "seen.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
}


# =========================
# БАЗА ОБЪЯВЛЕНИЙ
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            price TEXT
        )
    """)

    conn.commit()
    conn.close()


def is_seen(ad_id):
    conn = sqlite3.connect(DB_FILE)

    result = conn.execute(
        "SELECT id FROM ads WHERE id = ?",
        (ad_id,)
    ).fetchone()

    conn.close()

    return result is not None


def save_ad(ad):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT OR IGNORE INTO ads
        (id, url, title, price)
        VALUES (?, ?, ?, ?)
        """,
        (
            ad["id"],
            ad["url"],
            ad["title"],
            ad["price"]
        )
    )

    conn.commit()
    conn.close()


# =========================
# ПОЛУЧЕНИЕ OLX
# =========================

def get_ads():

    logging.info("Проверяю OLX...")

    response = requests.get(
        OLX_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    cards = soup.select(
        '[data-cy="l-card"]'
    )

    ads = []

    for card in cards:

        link = card.select_one("a")

        if not link:
            continue

        url = link.get("href")

        if not url:
            continue

        url = urljoin(
            "https://www.olx.pl",
            url
        )

        title_element = card.select_one(
            '[data-cy="ad-card-title"]'
        )

        title = (
            title_element.get_text(
                " ",
                strip=True
            )
            if title_element
            else "Samochód"
        )

        price_element = card.select_one(
            '[data-testid="ad-price"]'
        )

        if not price_element:
            price_element = card.select_one(
                '[data-cy="ad-card-price"]'
            )

        price = (
            price_element.get_text(
                " ",
                strip=True
            )
            if price_element
            else "Cena nie podana"
        )

        # Берём идентификатор из URL
        ad_id = url.rstrip("/").split("-")[-1]

        ads.append({
            "id": ad_id,
            "url": url,
            "title": title,
            "price": price
        })

    return ads


# =========================
# TELEGRAM
# =========================

def send_telegram(bot, ad):

    message = (
        "🚨 <b>NOWE AUTO NA OLX</b>\n\n"
        f"🚗 <b>{ad['title']}</b>\n"
        f"💰 {ad['price']}\n\n"
        f"🔗 <a href=\"{ad['url']}\">OTWÓRZ OLX</a>"
    )

    bot.send_message(
        chat_id=CHAT_ID,
        text=message,
        parse_mode="HTML"
    )


# =========================
# ЗАПУСК
# =========================

def main():

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "Не указан TELEGRAM_TOKEN"
        )

    if not CHAT_ID:
        raise RuntimeError(
            "Не указан CHAT_ID"
        )

    init_db()

    bot = Bot(
        token=TELEGRAM_TOKEN
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s"
    )

    first_run = True

    while True:

        try:

            ads = get_ads()

            logging.info(
                "Найдено объявлений: %s",
                len(ads)
            )

            for ad in reversed(ads):

                if is_seen(ad["id"]):
                    continue

                save_ad(ad)

                # При первом запуске не отправляем
                # уже существующие объявления.
                if first_run:
                    continue

                try:

                    send_telegram(
                        bot,
                        ad
                    )

                    logging.info(
                        "Отправлено: %s",
                        ad["title"]
                    )

                except Exception as error:

                    logging.error(
                        "Ошибка Telegram: %s",
                        error
                    )

            first_run = False

        except Exception as error:

            logging.exception(
                "Ошибка проверки OLX: %s",
                error
            )

        time.sleep(
            CHECK_INTERVAL
        )


if __name__ == "__main__":
    main()
