import os
import random
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esto-en-produccion")

DB_PATH = os.environ.get("DB_PATH", "raffle.db")

# =========================
# CONFIGURA TUS 8 NOMBRES
# =========================
NAMES = [
    "Fortis",
    "Mara",
    "Diego",
    "Maryem",
    "Zaira",
    "Kami",
    "Laila",
    "Alek",
]

# =========================
# PINs (RECOMENDADO)
# - Si no quieres PIN, pon PIN_REQUIRED = False
# =========================
PIN_REQUIRED = True
PINS = {
    "Fortis": "1111",
    "Mara": "2222",
    "Diego": "3333",
    "Maryem": "4444",
    "Zaira": "5555",
    "Kami": "6666",
    "Laila": "7777",
    "Alek": "8888",
}

# =========================
# REGLAS / RESTRICCIONES
# =========================
FORBIDDEN_PAIRS = {
    ("Fortis", "Mara"),  # Fortis no puede regalar a Mara
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                giver TEXT PRIMARY KEY,
                receiver TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS revealed (
                giver TEXT PRIMARY KEY,
                revealed_at TEXT NOT NULL
            )
        """)
        conn.commit()


def assignments_exist():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM assignments").fetchone()
        return row["c"] > 0


def revealed_set():
    with get_conn() as conn:
        rows = conn.execute("SELECT giver FROM revealed").fetchall()
        return {r["giver"] for r in rows}


def load_receiver(giver: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT receiver FROM assignments WHERE giver = ?",
            (giver,)
        ).fetchone()
        return row["receiver"] if row else None


def mark_revealed(giver: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO revealed (giver, revealed_at) VALUES (?, ?)",
            (giver, datetime.utcnow().isoformat())
        )
        conn.commit()


def is_valid_pair(giver: str, receiver: str) -> bool:
    if giver == receiver:
        return False
    if (giver, receiver) in FORBIDDEN_PAIRS:
        return False
    return True


def generate_secret_santa(names):
    """
    Genera una asignación 1-1 sin repetidos, sin auto-asignación,
    y respetando FORBIDDEN_PAIRS.
    Usa reintentos aleatorios (suficiente para 8) y cae a backtracking si quieres.
    """
    names = list(names)

    # Reintentos con shuffle (rápido para 8)
    for _ in range(5000):
        receivers = names[:]
        random.shuffle(receivers)

        ok = True
        for giver, receiver in zip(names, receivers):
            if not is_valid_pair(giver, receiver):
                ok = False
                break

        # Además asegurar que es permutación válida (ya lo es por construcción)
        if ok:
            return dict(zip(names, receivers))

    raise RuntimeError("No se pudo generar una asignación válida con las restricciones.")


def save_assignments(mapping: dict):
    with get_conn() as conn:
        conn.execute("DELETE FROM assignments")
        conn.execute("DELETE FROM revealed")
        for giver, receiver in mapping.items():
            conn.execute(
                "INSERT INTO assignments (giver, receiver) VALUES (?, ?)",
                (giver, receiver)
            )
        conn.commit()


@app.route("/", methods=["GET"])
def index():
    init_db()

    # Si no existe asignación aún, se crea (1 sola vez)
    if not assignments_exist():
        mapping = generate_secret_santa(NAMES)
        save_assignments(mapping)

    revealed = revealed_set()

    # Lista para el front: nombres disponibles/deshabilitados
    people = []
    for name in NAMES:
        people.append({
            "name": name,
            "disabled": name in revealed
        })

    return render_template("index.html", people=people, pin_required=PIN_REQUIRED)


@app.route("/reveal", methods=["POST"])
def reveal():
    init_db()

    giver = request.form.get("giver", "").strip()
    pin = request.form.get("pin", "").strip()

    if giver not in NAMES:
        flash("Nombre inválido.", "error")
        return redirect(url_for("index"))

    # Ya fue revelado => bloquear
    if giver in revealed_set():
        flash("Ese nombre ya fue utilizado para ver el resultado.", "error")
        return redirect(url_for("index"))

    if PIN_REQUIRED:
        if giver not in PINS or pin != PINS[giver]:
            flash("PIN incorrecto.", "error")
            return redirect(url_for("index"))

    receiver = load_receiver(giver)
    if not receiver:
        flash("No hay asignación generada. (Esto no debería pasar).", "error")
        return redirect(url_for("index"))

    # Marcar como revelado (para deshabilitarlo)
    mark_revealed(giver)

    return render_template("reveal.html", giver=giver, receiver=receiver)


@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    """
    Resetea y re-genera. Protegido con una llave simple por ENV.
    """
    init_db()
    admin_key = os.environ.get("ADMIN_KEY", "")
    provided = request.form.get("admin_key", "")

    if not admin_key or provided != admin_key:
        return "Unauthorized", 401

    mapping = generate_secret_santa(NAMES)
    save_assignments(mapping)
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

@app.route("/admin", methods=["GET"])
def admin_view():
    key = request.args.get("key")
    if key != os.environ.get("ADMIN_KEY"):
        return "Unauthorized", 401

    with get_conn() as conn:
        assignments = conn.execute("SELECT giver, receiver FROM assignments").fetchall()
        revealed = conn.execute("SELECT giver, revealed_at FROM revealed").fetchall()

    html = "<h2>Asignaciones</h2><ul>"
    for a in assignments:
        html += f"<li>{a['giver']} ➜ {a['receiver']}</li>"
    html += "</ul><h2>Ya revelaron</h2><ul>"
    for r in revealed:
        html += f"<li>{r['giver']} ({r['revealed_at']})</li>"
    html += "</ul>"

    html += """
    <form method="POST" action="/admin/reset">
      <input type="hidden" name="admin_key" value="{key}">
      <button type="submit">RESET RIFA</button>
    </form>
    """.format(key=key)

    return html

