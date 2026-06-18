"""
database.py — вся работа с базой данных розыгрышей.
Отделена от Telegram-логики, чтобы её можно было протестировать
независимо и переиспользовать.
"""
import sqlite3
import random
DB_NAME = "giveaways.db"
def get_connection(db_name=DB_NAME):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_name=DB_NAME):
    """Создаёт таблицы розыгрышей и участников."""
    conn = get = get_connection(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            channel_username TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            winner_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            FOREIGN KEY (giveaway_id) REFERENCES giveaways (id),
            UNIQUE (giveaway_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

def create_giveaway(creator_id, prize, channel_username, db_name=DB_NAME):
    """Создаёт новый розыгрыш и возвращает его id."""
    conn = get_connection(db_name)
    cursor = conn.execute(
        "INSERT INTO giveaways (creator_id, prize, channel_username) VALUES (?, ?, ?)",
        (creator_id, prize, channel_username)
    )
    conn.commit()
    giveaway_id = cursor.lastrowid
    conn.close()
    return giveaway_id

def get_giveaway(giveaway_id, db_name = DB_NAME):
    """Возвращает розыгрыш по id, либо None."""
    conn = get_connection(db_name)
    giveaway = conn.execute(
        "SELECT * FROM giveaways WHERE id = ?", (giveaway_id,)
    ).fetchone()
    conn.close()
    return giveaway

def add_participant(giveaway_id, user_id, username, db_name= DB_NAME):
    """
        Добавляет участника в розыгрыш.
        Возвращает True, если добавлен впервые; False, если уже участвовал.
        """
    conn = get_connection(db_name)
    try:
        conn.execute(
            "INSERT INTO participants (giveaway_id, user_id, username) VALUES (?, ?, ?)",
            (giveaway_id, user_id,username)
        )
        conn.commit()
        result = True
    except sqlite3.IntegrityError:
        result = False
    conn.close()
    return result

def get_participants(giveaway_id, db_name=DB_NAME):
    """Возвращает список участников розыгрыша."""
    conn = get_connection(db_name)
    rows = conn.execute(
        "SELECT * FROM participants WHERE giveaway_id = ?", (giveaway_id,)
    ).fetchall()
    conn.close()
    return rows

def pick_winner(giveaway_id, db_name=DB_NAME):
    """
    Случайно выбирает победителя среди участников розыгрыша,
    завершает розыгрыш и сохраняет id победителя.
    Возвращает участник-победителя (sqlite3.Row) или None, если участников нет.
    """
    participants = get_participants(giveaway_id, db_name)
    if not participants:
        return None

    winner = random.choice(participants)
    conn = get_connection(db_name)
    conn.execute(
        "UPDATE giveaways SET is_active = 0, winner_id = ? WHERE id = ?",
        (winner["user_id"], giveaway_id)
    )
    conn.commit()
    conn.close()

    return winner