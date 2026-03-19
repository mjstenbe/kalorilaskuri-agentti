import streamlit as st
import sqlite3
import json
import pandas as pd
from datetime import datetime
from openai import OpenAI

# =========================
# 🔐 CONFIG
# =========================

DAILY_GOAL = 1800

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# =========================
# 📊 LOAD FINELI DATA
# =========================
@st.cache_data
def load_data():
    foods = pd.read_csv("fineli_foods.csv")
    nutrients = pd.read_csv("fineli_nutrients.csv")
    return foods, nutrients

foods_df, nutrients_df = load_data()

# =========================
# 🗄️ DATABASE
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
    fiber REAL,
    vitamin_c REAL,
    vitamin_d REAL,
    b12 REAL,
    iron REAL,
    calcium REAL,
    magnesium REAL
)
""")
conn.commit()

# =========================
# 🧠 AI: PARSE FOOD + AMOUNT
# =========================
def parse_meal(text):
    prompt = f"""
Pilko ateria osiin ja tunnista määrät ja yksiköt.

Vastaa JSON listana:

[
  {{"food": "riisi", "amount": 1, "unit": "dl"}},
  {{"food": "kana", "amount": 200, "unit": "g"}}
]

Ateria: {text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return json.loads(response.choices[0].message.content)

# =========================
# ⚖️ UNIT CONVERSIONS
# =========================
UNIT_TO_GRAMS = {
    "riisi": {"dl": 180, "g": 1},
    "pasta": {"dl": 140, "g": 1},
    "kaurapuuro": {"dl": 200},
    "kana": {"g": 1},
    "broilerinkoipi": {"kpl": 180},
    "kananmuna": {"kpl": 60},
    "peruna": {"kpl": 100}
}

def convert_to_grams(food, amount, unit):
    food = food.lower()

    if food in UNIT_TO_GRAMS:
        if unit in UNIT_TO_GRAMS[food]:
            return amount * UNIT_TO_GRAMS[food][unit]

    if unit == "g":
        return amount

    return None

# =========================
# 🔎 FIND FOOD (FINELI)
# =========================
def find_food(name):
    matches = foods_df[foods_df["FOODNAME"].str.contains(name, case=False, na=False)]
    if not matches.empty:
        return matches.iloc[0]
    return None

def get_nutrients(food_id):
    data = nutrients_df[nutrients_df["FOODID"] == food_id]
    result = {}
    for _, row in data.iterrows():
        result[row["NUTRIENTNAME"]] = row["VALUE"]
    return result

# =========================
# 🧮 CALCULATION ENGINE
# =========================
def calculate_meal(parsed):
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
        grams = convert_to_grams(item["food"], item["amount"], item["unit"])
        if grams is None:
            continue

        food = find_food(item["food"])
        if food is None:
            continue

        nutrients = get_nutrients(food["FOODID"])
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
        totals["magnesium"] += nutrients.get("Magnesium, Mg", 0) * factor

    return totals

# =========================
# ➕ ADD MEAL
# =========================
def add_meal(text):
    parsed = parse_meal(text)
    totals = calculate_meal(parsed)

    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        INSERT INTO meals (
            date, description, calories, protein, carbs, fat,
            fiber, vitamin_c, vitamin_d, b12, iron, calcium, magnesium
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        today, text,
        totals["calories"], totals["protein"], totals["carbs"], totals["fat"],
        totals["fiber"], totals["vitamin_c"], totals["vitamin_d"],
        totals["b12"], totals["iron"], totals["calcium"], totals["magnesium"]
    ))

    conn.commit()

# =========================
# 📊 FETCH DATA
# =========================
def get_today():
    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT * FROM meals WHERE date=?
    """, (today,))

    return cursor.fetchall()

# =========================
# 🎯 RDI VALUES
# =========================
RDI = {
    "fiber": 25,
    "vitamin_c": 75,
    "vitamin_d": 10,
    "b12": 2.4,
    "iron": 14,
    "calcium": 800,
    "magnesium": 350
}

def percent(val, target):
    return (val / target * 100) if target else 0

# =========================
# 🖥️ UI
# =========================
st.title("🥗 Kaloriagentti V4 (Fineli)")

meal = st.text_input("Mitä söit? (esim. 1 dl riisiä ja 2 kananmunaa)")

if st.button("Lisää"):
    add_meal(meal)
    st.success("Lisätty!")

rows = get_today()

total = {
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

if rows:
    st.subheader("📊 Päivän data")

    for r in rows:
        total["calories"] += r[3]
        total["protein"] += r[4]
        total["carbs"] += r[5]
        total["fat"] += r[6]
        total["fiber"] += r[7]
        total["vitamin_c"] += r[8]
        total["vitamin_d"] += r[9]
        total["b12"] += r[10]
        total["iron"] += r[11]
        total["calcium"] += r[12]
        total["magnesium"] += r[13]

# =========================
# 📈 SUMMARY
# =========================
remaining = DAILY_GOAL - total["calories"]
pct = (total["calories"] / DAILY_GOAL) * 100

col1, col2, col3 = st.columns(3)

col1.metric("Kalorit", f"{int(total['calories'])}")
col2.metric("Jäljellä", f"{int(remaining)}")
col3.metric("Käyttö", f"{pct:.1f}%")

st.write(f"**Makrot:** P {int(total['protein'])}g | C {int(total['carbs'])}g | F {int(total['fat'])}g")

# =========================
# 🧬 MICROS
# =========================
st.subheader("🧬 Mikroravinteet")

micro = [
    ("Kuitu", "fiber"),
    ("C-vitamiini", "vitamin_c"),
    ("D-vitamiini", "vitamin_d"),
    ("B12", "b12"),
    ("Rauta", "iron"),
    ("Kalsium", "calcium"),
    ("Magnesium", "magnesium")
]

table = []

for name, key in micro:
    table.append({
        "Ravinne": name,
        "Määrä": int(total[key]),
        "% RDI": round(percent(total[key], RDI[key]), 1)
    })

st.dataframe(table, use_container_width=True)
