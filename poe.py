import time
import requests
import re
import os # 👈 Новий імпорт
from datetime import datetime, timedelta, time
from bs4 import BeautifulSoup
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

# --- 💡 Читаємо "секрети", які ми додали в GitHub ---
WP_URL = os.environ.get("WORDPRESS_URL")
WP_KEY = os.environ.get("WORDPRESS_SECRET_KEY")
# -----------------------------------------------

def download_page_with_selenium(url):
    """
    Версія для GitHub Actions (працює в Linux-контейнері).
    """
    print(f"🛜  Запускаю браузер (selenium) в режимі headless...")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    # 🔴 ОБОВ'ЯЗКОВІ прапори для запуску в контейнері
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = None
    try:
        # Використовуємо ChromeDriverManager, він сам завантажить драйвер
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

def clean_text(text):
    if text is None: return ""
    return re.sub(r'\s+', ' ', text).strip()

def format_time(t):
    return t.strftime('%H:%M')

def add_minutes(t, minutes):
    dt = datetime.combine(datetime.today(), t) + timedelta(minutes=minutes)
    return dt.time()

def format_schedule_output(states):
    """
    ОНОВЛЕННЯ: Тепер ця функція ПОВЕРТАЄ список рядків, а не друкує.
    """
    lines_to_send = []
    i = 0
    while i < len(states):
        state = states[i]
        
        if state == "OFF":
            start_time = add_minutes(time(0, 0), i * 30)
            j = i
            while j < len(states) and states[j] == "OFF": j += 1
            end_time = add_minutes(time(0, 0), j * 30)
            
            if j < len(states) and states[j] == "MAYBE_OFF":
                k = j
                while k < len(states) and states[k] == "MAYBE_OFF": k += 1
                maybe_end_time = add_minutes(time(0, 0), k * 30)
                # Додаємо рядок до списку
                lines_to_send.append(f"{format_time(start_time)} - {format_time(end_time)}({format_time(maybe_end_time)})")
                i = k
            else:
                # Додаємо рядок до списку
                lines_to_send.append(f"{format_time(start_time)} - {format_time(end_time)}")
                i = j
        else:
            i += 1
    return lines_to_send


def parse_and_get_schedule(html, target_q, target_sq):
    """
    ОНОВЛЕННЯ: Знаходить останній графік і ПОВЕРТАЄ його у вигляді списку.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    current_main_queue = None
    found_schedules_states = [] 
    
    print("\n--- 🔎 Починаю аналіз завантаженої таблиці... ---")
    
    for i, row in enumerate(rows):
        cells = row.find_all("td")
        if not cells: continue
        
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

        if current_main_queue == target_q and current_sub_queue == target_sq:
            states = []
            state_map = {"light_1": "ON", "light_2": "OFF", "light_3": "MAYBE_OFF"}
            for cell in schedule_cells:
                cell_class = cell.get("class", [""])[0] 
                states.append(state_map.get(cell_class, "UNKNOWN"))
            found_schedules_states.append(states)
            
    if not found_schedules_states:
        print(f"❌ Не вдалося знайти графік для: '{target_q}', підчерга '{target_sq}'")
        return None
    else:
        print(f"✅ ЗНАЙДЕНО ГРАФІК: {target_q}, підчерга {target_sq}")
        if len(found_schedules_states) > 1:
            print(f"(Знайдено {len(found_schedules_states)} графіки. Беру останній.)")
        
        # Беремо ОСТАННІЙ і форматуємо його
        return format_schedule_output(found_schedules_states[-1])

def send_to_wordpress(schedule_lines):
    """
    Відправляє дані на ваш WordPress сайт.
    """
    if not WP_URL or not WP_KEY:
        print("❌ Не можу відправити: 'Секрети' WORDPRESS_URL або WORDPRESS_SECRET_KEY не встановлені.")
        return

    if not schedule_lines:
        print("...Графік не знайдено, нічого відправляти.")
        return

    # Перетворюємо список ["01:00 - 04:00", "08:00 - 11:00"]
    # на один рядок "01:00 - 04:00<br>08:00 - 11:00"
    data_to_send = "<br>".join(schedule_lines)
    
    payload = {
        "secret_key": WP_KEY,
        "schedule_data": data_to_send
    }
    
    try:
        print(f"🚀 Відправляю дані на {WP_URL}...")
        requests.post(WP_URL, data=payload)
        print("✅ Дані успішно відправлено на WordPress!")
    except Exception as e:
        print(f"❌ Помилка відправки на WordPress: {e}")

# --- Головний запуск ---
if __name__ == "__main__":
    html_content = download_page_with_selenium(URL)
    
    if html_content:
        # 1. Отримуємо список рядків
        schedule_list = parse_and_get_schedule(html_content, TARGET_QUEUE, TARGET_SUBQUEUE)
        
        # 2. Відправляємо на WordPress
        send_to_wordpress(schedule_list)
