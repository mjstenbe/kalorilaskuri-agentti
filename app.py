import streamlit as st
import requests
import sqlite3
import json
from datetime import datetime
from openai import OpenAI

# =========================
# 🔐 CONFIG
# =========================
DAILY_GOAL = 1800
st.write(st.secrets)
client = OpenAI(st.secrets["OPENAI_API_KEY"])

FINELI_BASE = "https://fineli.fi/fineli/api/v1"

# =========================
# 🧠 AI: PARSE FOOD
# =========================
def parse_meal(text):
    prompt = f"""
Pilko ateria osiin ja arvioi määrät.

Palauta JSON:
[
  {{"food": "riisi", "amount": 1, "unit": "dl"}},
  {{"food": "kana", "amount": 150, "unit": "g"}}
]

Ateria: {text}
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return json.loads(res.choices[0].message.content)

# =========================
# ⚖️ UNIT CONVERSION
# =========================
UNIT_TO_GRAMS = {
    "riisi": {"dl": 180, "g": 1},
    "pasta": {"dl": 140, "g": 1},
    "kana": {"g": 1},
    "broilerinkoipi": {"kpl": 180},
    "kananmuna": {"kpl": 60},
    "peruna": {"kpl": 100}
}

def to_grams(food, amount, unit):
    food = food.lower()
    if food in UNIT_TO_GRAMS and unit in UNIT_TO_GRAMS[food]:
        return amount * UNIT_TO_GRAMS[food][unit]
    if unit == "g":
        return amount
    return None

# =========================
# 🌐 FINELI API
# =========================

@st.cache_data
def search_food(name):
    url = f"{FINELI_BASE}/fooditems"
    r = requests.get(url, params={"name": name, "language": "fi"})
    if r.status_code == 200:
        data = r.json()
        if data:
            return data[0]  # paras match
    return None

@st.cache_data
def get_nutrients(food_id):
    url = f"{FINELI_BASE}/fooditems/{food_id}"
    r = requests.get(url)
    if r.status_code != 200:
        return {}

    data = r.json()

    nutrients = {}
    for n in data.get("nutrients", []):
        nutrients[n["name"]] = n["amount"]

    return nutrients

# =========================
# 🧮 CALC ENGINE
# =========================
def calculate(parsed):
    totals = {
        "calories": 0,
        "protein": 0,
        "carbs": 0,
        "fat": 0,
        "fiber": 0,
        "vitamin_c": 0,
        "vitamin_d": 0,
        "b12": 0,
        "iron": 0,
        "calcium": 0,
        "magnesium": 0
    }

    for item in parsed:
        grams = to_grams(item["food"], item["amount"], item["unit"])
        if not grams:
            continue

        food = search_food(item["food"])
        if not food:
            continue

        nutrients = get_nutrients(food["id"])
        factor = grams / 100

        totals["calories"] += nutrients.get("Energy (kcal)", 0) * factor
        totals["protein"] += nutrients.get("Protein", 0) * factor
        totals["carbs"] += nutrients.get("Carbohydrate, available", 0) * factor
        totals["fat"] += nutrients.get("Fat", 0) * factor
        totals["fiber"] += nutrients.get("Fibre, total dietary", 0) * factor

        totals["vitamin_c"] += nutrients.get("Vitamin C", 0) * factor
        totals["vitamin_d"] += nutrients.get("Vitamin D", 0) * factor
        totals["b12"] += nutrients.get("Vitamin B12", 0) * factor
        totals["iron"] += nutrients.get("Iron", 0) * factor
        totals["calcium"] += nutrients.get("Calcium", 0) * factor
        totals["magnesium"] += nutrients.get("Magnesium", 0) * factor

    return totals

# =========================
# 🗄️ DB
# =========================
conn = sqlite3.connect("kalorit.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    description TEXT,
    calories REAL,
    protein REAL,
    carbs REAL,
    fat REAL,
    fiber REAL
)
""")
conn.commit()

# =========================
# ➕ ADD
# =========================
def add_meal(text):
    parsed = parse_meal(text)
    totals = calculate(parsed)

    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        INSERT INTO meals (date, description, calories, protein, carbs, fat, fiber)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        today, text,
        totals["calories"],
        totals["protein"],
        totals["carbs"],
        totals["fat"],
        totals["fiber"]
    ))

    conn.commit()

# =========================
# 📊 FETCH
# =========================
def get_today():
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT * FROM meals WHERE date=?", (today,))
    return cursor.fetchall()

# =========================
# 🎯 RDI
# =========================
RDI = {
    "fiber": 25
}

# =========================
# 🖥️ UI
# =========================
st.title("🥗 Kaloriagentti V4 – Fineli API")

meal = st.text_input("Mitä söit?")

if st.button("Lisää"):
    add_meal(meal)
    st.success("Lisätty!")

rows = get_today()

total_cal = total_p = total_c = total_f = 0

if rows:
    for r in rows:
        total_cal += r[3]
        total_p += r[4]
        total_c += r[5]
        total_f += r[6]

remaining = DAILY_GOAL - total_cal
pct = (total_cal / DAILY_GOAL) * 100

st.subheader("📊 Yhteenveto")
st.metric("Kalorit", int(total_cal))
st.metric("Jäljellä", int(remaining))
st.metric("Käyttö %", round(pct, 1))

st.write(f"Makrot: P {int(total_p)}g | C {int(total_c)}g | F {int(total_f)}g")

st.subheader("🧬 Kuitu")
fiber = sum(r[6] for r in rows)
st.write(f"{fiber} g ({fiber/25*100:.1f} %)")
