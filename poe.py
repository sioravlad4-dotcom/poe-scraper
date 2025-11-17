import time
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, time

# --- Імпорти для Selenium ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

URL = "https://www.poe.pl.ua/disconnection/power-outages/"

# --- Вкажіть, яку чергу шукати ---
TARGET_QUEUE = "2 черга"
TARGET_SUBQUEUE = "1"


# ---------------------------------

def download_page_with_selenium(url):
    """
    (Без змін)
    Завантажує сторінку за допомогою Selenium,
    чекає на прогрузку JS-контенту.
    """
    print(f"🛜  Запускаю браузер (selenium) для {url}...")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.get(url)

        print("...Чекаю, поки JavaScript завантажить таблицю...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "turnoff-scheduleui-table-queue"))
        )

        print("✅ Таблицю завантажено (JS виконався). Беру HTML.")
        return driver.page_source

    except Exception as e:
        print(f"❌ Помилка Selenium: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def format_time(t):
    return t.strftime('%H:%M')


def add_minutes(t, minutes):
    dt = datetime.combine(datetime.today(), t) + timedelta(minutes=minutes)
    return dt.time()


def clean_text(text):
    if text is None:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# -----------------------------------------------------------------
# --- 🔴 ОСЬ ЦЯ ФУНКЦІЯ ОНОВЛЕНА 🔴 ---
# -----------------------------------------------------------------
def parse_and_print_schedule(html, target_q, target_sq):
    """
    ОНОВЛЕНА ВЕРСІЯ:
    Знаходить *всі* збіги і виводить *останній* (для графіка "на завтра").
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")

    current_main_queue = None

    # НОВЕ: Список для зберігання *всіх* знайдених графіків
    found_schedules_states = []

    print("\n--- 🔎 Починаю аналіз завантаженої таблиці... ---")

    for i, row in enumerate(rows):
        cells = row.find_all("td")
        if not cells:
            continue

        schedule_cells = []
        current_sub_queue = None

        first_cell_class = cells[0].get("class", [])

        try:
            if "turnoff-scheduleui-table-queue" in first_cell_class:
                current_main_queue = clean_text(cells[0].get_text())
                current_sub_queue = clean_text(cells[1].get_text())
                schedule_cells = cells[2:]

            elif "turnoff-scheduleui-table-subqueue" in first_cell_class:
                current_sub_queue = clean_text(cells[0].get_text())
                schedule_cells = cells[1:]

            else:
                continue

        except IndexError:
            continue

            # Перевіряємо, чи це та черга, яку ми шукаємо
        if current_main_queue == target_q and current_sub_queue == target_sq:
            # Знайшли збіг!
            states = []
            state_map = {"light_1": "ON", "light_2": "OFF", "light_3": "MAYBE_OFF"}

            for cell in schedule_cells:
                cell_class = cell.get("class", [""])[0]
                states.append(state_map.get(cell_class, "UNKNOWN"))

            # Додаємо розпарсений графік до нашого списку
            found_schedules_states.append(states)

            # Ми прибрали 'break', тому цикл продовжується

    # --- НОВЕ: Аналізуємо результати ПІСЛЯ завершення циклу ---

    if not found_schedules_states:
        # Випадок 1: Нічого не знайдено
        print("----------------------------------------")
        print(f"❌ Не вдалося знайти графік для: '{target_q}', підчерга '{target_sq}'")
        print("(Скрипт завантажив таблицю, але текст черги/підчерги не збігся)")

    else:
        # Випадок 2: Знайдено один або більше графіків.
        # Беремо ОСТАННІЙ зі списку.
        target_states = found_schedules_states[-1]

        print(f"✅ ЗНАЙДЕНО ГРАФІК: {target_q}, підчерга {target_sq}")

        if len(found_schedules_states) > 1:
            print(f"(Знайдено {len(found_schedules_states)} графіки. Показую останній, тобто на 'завтра'.)")

        print("----------------------------------------")

        # Викликаємо функцію форматування для останнього графіка
        format_schedule_output(target_states)


# -----------------------------------------------------------------
# --- (Решта функцій без змін) ---
# -----------------------------------------------------------------

def format_schedule_output(states):
    """
    (Без змін)
    Форматує вивід у вашому стилі: HH:MM - HH:MM(HH:MM)
    """
    i = 0
    while i < len(states):
        state = states[i]

        if state == "OFF":
            start_time = add_minutes(time(0, 0), i * 30)

            j = i
            while j < len(states) and states[j] == "OFF":
                j += 1

            end_time = add_minutes(time(0, 0), j * 30)

            if j < len(states) and states[j] == "MAYBE_OFF":
                k = j
                while k < len(states) and states[k] == "MAYBE_OFF":
                    k += 1

                maybe_end_time = add_minutes(time(0, 0), k * 30)
                print(f"{format_time(start_time)} - {format_time(end_time)}({format_time(maybe_end_time)})")
                i = k

            else:
                print(f"{format_time(start_time)} - {format_time(end_time)}")
                i = j

        else:
            i += 1


# --- Головний запуск (Без змін) ---
if __name__ == "__main__":
    html_content = download_page_with_selenium(URL)

    if html_content:
        parse_and_print_schedule(html_content, TARGET_QUEUE, TARGET_SUBQUEUE)
