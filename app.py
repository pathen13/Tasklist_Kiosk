#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reminder – Haupt-Web-UI (Flask + SQLite)
• Benutzerwahl ohne Passwort
• Aufgaben: Beschreibung (<=100), Fälligkeitsdatum, Dringlichkeit (niedrig/normal/hoch),
  Details, Status (Offen/Erledigt/Verworfen)
• CRUD + Filter (Status, von mir erstellt / an mich zugewiesen)
"""

from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import Optional
import os

from flask import Flask, redirect, render_template, request, session, url_for, flash, Response
from jinja2 import DictLoader
from sqlalchemy import create_engine, ForeignKey, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
from sqlalchemy.types import String, Text, Date

# ----------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------
DB_PATH = os.environ.get("REMINDER_DB", "reminder.sqlite3")
SECRET_KEY = os.environ.get("REMINDER_SECRET", "dev-secret-change-me")

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET_KEY)
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)

class Base(DeclarativeBase):
    pass

# ----------------------------------------------------------------------------
# Modelle
# ----------------------------------------------------------------------------
class Priority(str, Enum):
    low = "niedrig"
    normal = "normal"
    high = "hoch"

class Status(str, Enum):
    open = "Offen"
    done = "Erledigt"
    discarded = "Verworfen"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    created_tasks: Mapped[list["Task"]] = relationship(
        back_populates="creator", foreign_keys=lambda: Task.creator_id
    )
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys=lambda: Task.assignee_id
    )

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    description: Mapped[str] = mapped_column(String(100), nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(10), default=Priority.normal.value, nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=Status.open.value, nullable=False)

    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    creator: Mapped[User] = relationship(back_populates="created_tasks", foreign_keys=[creator_id])
    assignee: Mapped[User] = relationship(back_populates="assigned_tasks", foreign_keys=[assignee_id])

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

# DB anlegen (nur hier)
Base.metadata.create_all(engine)

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def get_db() -> Session:
    return Session(engine)

def current_user(db: Session) -> Optional[User]:
    uid = session.get("user_id")
    return db.get(User, uid) if uid else None

def require_user(fn):
    def wrapper(*args, **kwargs):
        with get_db() as db:
            if not current_user(db):
                flash("Bitte zuerst Benutzer wählen oder anlegen.", "warning")
                return redirect(url_for("select_user"))
        return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper

# ----------------------------------------------------------------------------
# Komfort-Routen
# ----------------------------------------------------------------------------
@app.route("/")
def root():
    # Start in die Taskliste (fordert Benutzerwahl, wenn nicht gesetzt)
    return redirect(url_for("list_tasks"))

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

# ----------------------------------------------------------------------------
# Benutzer
# ----------------------------------------------------------------------------
@app.route("/users/select", methods=["GET", "POST"])
def select_user():
    with get_db() as db:
        if request.method == "POST":
            action = request.form.get("action")
            if action == "pick":
                uid = request.form.get("user_id")
                if uid and db.get(User, int(uid)):
                    session["user_id"] = int(uid)
                    flash("Benutzer gesetzt.", "success")
                    return redirect(url_for("list_tasks"))
                flash("Ungültige Auswahl.", "danger")
            elif action == "create":
                name = (request.form.get("name") or "").strip()
                if not name:
                    flash("Name darf nicht leer sein.", "danger")
                else:
                    existing = db.scalar(select(User).where(func.lower(User.name) == name.lower()))
                    if existing:
                        flash("Name existiert bereits.", "danger")
                    else:
                        user = User(name=name)
                        db.add(user)
                        db.commit()
                        session["user_id"] = user.id
                        flash("Benutzer angelegt und angemeldet.", "success")
                        return redirect(url_for("list_tasks"))
        users = db.scalars(select(User).order_by(User.name)).all()
        return render_template("select_user.html", users=users)

@app.route("/logout")
def logout():
    session.clear()
    flash("Abgemeldet.", "info")
    return redirect(url_for("select_user"))

# ----------------------------------------------------------------------------
# Aufgaben
# ----------------------------------------------------------------------------
@app.route("/tasks")
@require_user
def list_tasks():
    with get_db() as db:
        me = current_user(db)
        status = request.args.get("status")
        mine = request.args.get("mine")

        q = select(Task).order_by(
            Task.due_date.is_(None), Task.due_date, Task.priority.desc(), Task.created_at.desc()
        )
        if status in {Status.open.value, Status.done.value, Status.discarded.value}:
            q = q.where(Task.status == status)
        if mine == "created":
            q = q.where(Task.creator_id == me.id)
        elif mine == "assigned":
            q = q.where(Task.assignee_id == me.id)

        tasks = db.scalars(q).all()
        users = db.scalars(select(User).order_by(User.name)).all()
        return render_template("tasks_list.html", tasks=tasks, users=users, me=me, Status=Status, Priority=Priority)

@app.route("/tasks/new", methods=["GET", "POST"])
@require_user
def create_task():
    with get_db() as db:
        me = current_user(db)
        users = db.scalars(select(User).order_by(User.name)).all()
        if request.method == "POST":
            description = (request.form.get("description") or "").strip()
            if len(description) == 0 or len(description) > 100:
                flash("Beschreibung ist Pflicht und max. 100 Zeichen.", "danger")
                return render_template("task_form.html", users=users, me=me, task=None, Priority=Priority, Status=Status)

            due = request.form.get("due_date") or None
            due_date_val = datetime.strptime(due, "%Y-%m-%d").date() if due else None
            priority = request.form.get("priority") or Priority.normal.value
            if priority not in [p.value for p in Priority]:
                priority = Priority.normal.value
            details = request.form.get("details") or ""
            status = request.form.get("status") or Status.open.value
            if status not in [s.value for s in Status]:
                status = Status.open.value

            assignee_id = int(request.form.get("assignee_id") or me.id)
            if not db.get(User, assignee_id):
                assignee_id = me.id

            task = Task(
                description=description,
                due_date=due_date_val,
                priority=priority,
                details=details,
                status=status,
                creator_id=me.id,
                assignee_id=assignee_id,
            )
            db.add(task)
            db.commit()
            flash("Aufgabe erstellt.", "success")
            return redirect(url_for("list_tasks"))
        return render_template("task_form.html", users=users, me=me, task=None, Priority=Priority, Status=Status)

@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@require_user
def edit_task(task_id: int):
    with get_db() as db:
        me = current_user(db)
        task = db.get(Task, task_id)
        if not task:
            flash("Aufgabe nicht gefunden.", "danger")
            return redirect(url_for("list_tasks"))
        users = db.scalars(select(User).order_by(User.name)).all()
        if request.method == "POST__":
            pass  # dummy (wird überschrieben)

        if request.method == "POST":
            description = (request.form.get("description") or "").strip()
            if len(description) == 0 or len(description) > 100:
                flash("Beschreibung ist Pflicht und max. 100 Zeichen.", "danger")
                return render_template("task_form.html", users=users, me=me, task=task, Priority=Priority, Status=Status)

            due = request.form.get("due_date") or None
            task.due_date = datetime.strptime(due, "%Y-%m-%d").date() if due else None
            priority = request.form.get("priority") or Priority.normal.value
            if priority in [p.value for p in Priority]:
                task.priority = priority
            task.details = request.form.get("details") or ""
            status = request.form.get("status") or Status.open.value
            if status in [s.value for s in Status]:
                task.status = status
            assignee_id = int(request.form.get("assignee_id") or me.id)
            if db.get(User, assignee_id):
                task.assignee_id = assignee_id

            db.commit()
            flash("Aufgabe aktualisiert.", "success")
            return redirect(url_for("list_tasks"))

        return render_template("task_form.html", users=users, me=me, task=task, Priority=Priority, Status=Status)

@app.route("/tasks/<int:task_id>/status", methods=["POST"])
@require_user
def change_status(task_id: int):
    with get_db() as db:
        task = db.get(Task, task_id)
        if not task:
            flash("Aufgabe nicht gefunden.", "danger")
        else:
            new_status = request.form.get("status")
            if new_status in [s.value for s in Status]:
                task.status = new_status
                db.commit()
                flash("Status geändert.", "success")
            else:
                flash("Ungültiger Status.", "danger")
    return redirect(url_for("list_tasks"))

@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
@require_user
def delete_task(task_id: int):
    with get_db() as db:
        task = db.get(Task, task_id)
        if task:
            db.delete(task)
            db.commit()
            flash("Aufgabe gelöscht.", "info")
        else:
            flash("Aufgabe nicht gefunden.", "danger")
    return redirect(url_for("list_tasks"))

# ----------------------------------------------------------------------------
# Jinja2 Templates
# ----------------------------------------------------------------------------
TEMPLATES = {
"base.html": r"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reminder</title>
  <link rel="stylesheet" href="https://unpkg.com/@picocss/pico@2/css/pico.min.css">
  <style>
    .status-Offen { background:#fff3cd; }
    .status-Erledigt { background:#d1e7dd; }
    .status-Verworfen { background:#f8d7da; }
    .badge { font-size:.75rem; padding:.2rem .4rem; border-radius:.5rem; }
  </style>
</head>
<body>
  <nav class="container">
    <ul><li><strong>🗓️ Reminder</strong></li></ul>
    <ul>
      {% if me %}<li>Angemeldet als: <strong>{{ me.name }}</strong></li>
      <li><a href="{{ url_for('logout') }}">Abmelden</a></li>{% endif %}
    </ul>
  </nav>
  <main class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div>
          {% for category, message in messages %}
            <article class="{{ category }}">{{ message }}</article>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
""",
"select_user.html": r"""
{% extends 'base.html' %}
{% block content %}
<h2>Benutzer wählen oder erstellen</h2>
<form method="post">
  <input type="hidden" name="action" value="pick">
  <label>Benutzer wählen
    <select name="user_id">
      {% for u in users %}<option value="{{ u.id }}">{{ u.name }}</option>{% endfor %}
    </select>
  </label>
  <button type="submit">Anmelden</button>
</form>
<hr>
<form method="post">
  <input type="hidden" name="action" value="create">
  <label>Neuen Benutzer anlegen
    <input name="name" maxlength="50" placeholder="Name" required>
  </label>
  <button type="submit">Erstellen & Anmelden</button>
</form>
{% endblock %}
""",
"tasks_list.html": r"""
{% extends 'base.html' %}
{% block content %}
<header class="grid">
  <h2>Aufgaben</h2>
  <div style="text-align:right">
    <a href="{{ url_for('create_task') }}" role="button">+ Aufgabe</a>
  </div>
</header>
<form method="get" class="grid">
  <label>Status
    <select name="status">
      <option value="">Alle</option>
      {% for s in [Status.open.value, Status.done.value, Status.discarded.value] %}
        <option value="{{ s }}" {% if request.args.get('status')==s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Filter
    <select name="mine">
      <option value="">Alle</option>
      <option value="created" {% if request.args.get('mine')=='created' %}selected{% endif %}>Von mir erstellt</option>
      <option value="assigned" {% if request.args.get('mine')=='assigned' %}selected{% endif %}>An mich zugewiesen</option>
    </select>
  </label>
  <button type="submit">Anwenden</button>
</form>

<table>
  <thead>
    <tr>
      <th>Beschreibung</th><th>Fällig</th><th>Dringlichkeit</th><th>Status</th>
      <th>Ersteller</th><th>Zugewiesen</th><th></th>
    </tr>
  </thead>
  <tbody>
    {% for t in tasks %}
    <tr class="status-{{ t.status }}">
      <td><strong><a href="{{ url_for('edit_task', task_id=t.id) }}">{{ t.description }}</a></strong><br>
          <small>{{ t.details|truncate(120) }}</small></td>
      <td>{% if t.due_date %}{{ t.due_date.isoformat() }}{% else %}-{% endif %}</td>
      <td>
        {% if t.priority == 'hoch' %}<span class="badge">hoch</span>{% endif %}
        {% if t.priority == 'normal' %}<span class="badge">normal</span>{% endif %}
        {% if t.priority == 'niedrig' %}<span class="badge">niedrig</span>{% endif %}
      </td>
      <td>{{ t.status }}</td>
      <td>{{ t.creator.name }}</td>
      <td>{{ t.assignee.name }}</td>
      <td>
        <form method="post" action="{{ url_for('change_status', task_id=t.id) }}" style="display:inline">
          <select name="status">
            {% for s in [Status.open.value, Status.done.value, Status.discarded.value] %}
              <option value="{{ s }}" {% if t.status==s %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
          <button type="submit">OK</button>
        </form>
        <form method="post" action="{{ url_for('delete_task', task_id=t.id) }}" style="display:inline" onsubmit="return confirm('Wirklich löschen?')">
          <button type="submit" class="contrast">Löschen</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7">Keine Aufgaben gefunden.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
""",
"task_form.html": r"""
{% extends 'base.html' %}
{% block content %}
<h2>{% if task %}Aufgabe bearbeiten{% else %}Neue Aufgabe{% endif %}</h2>
<form method="post" class="grid">
  <label>Beschreibung (max. 100 Zeichen)
    <input name="description" maxlength="100" value="{{ task.description if task else '' }}" required>
  </label>
  <label>Fälligkeitsdatum
    <input type="date" name="due_date" value="{{ task.due_date.isoformat() if task and task.due_date else '' }}">
  </label>
  <label>Dringlichkeit
    <select name="priority">
      {% for p in ['niedrig','normal','hoch'] %}
        <option value="{{ p }}" {% if task and task.priority==p %}selected{% endif %}>{{ p }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Status
    <select name="status">
      {% for s in [Status.open.value, Status.done.value, Status.discarded.value] %}
        <option value="{{ s }}" {% if task and task.status==s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Zugewiesen an
    <select name="assignee_id">
      {% for u in users %}
        <option value="{{ u.id }}" {% if task and task.assignee_id==u.id or (not task and me.id==u.id) %}selected{% endif %}>{{ u.name }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Details
    <textarea name="details" rows="6">{{ task.details if task else '' }}</textarea>
  </label>
  <div>
    <button type="submit">Speichern</button>
    <a href="{{ url_for('list_tasks') }}" role="button" class="secondary">Abbrechen</a>
  </div>
</form>
{% endblock %}
"""
}
app.jinja_loader = DictLoader(TEMPLATES)

# ----------------------------------------------------------------------------
# Dev-Seed (optional)
# ----------------------------------------------------------------------------
@app.cli.command("seed")
def seed():
    with get_db() as db:
        if not db.scalar(select(User)):
            alice = User(name="Alice")
            bob = User(name="Bob")
            db.add_all([alice, bob]); db.commit()
            t1 = Task(description="Müll rausbringen", due_date=date.today(), priority=Priority.normal.value,
                      details="Gelber Sack.", status=Status.open.value, creator_id=alice.id, assignee_id=bob.id)
            t2 = Task(description="Wocheneinkauf", priority=Priority.high.value,
                      details="Liste am Kühlschrank.", status=Status.open.value, creator_id=bob.id, assignee_id=alice.id)
            db.add_all([t1, t2]); db.commit()
            print("Seed-Daten angelegt.")
        else:
            print("Benutzer/Tasks existieren bereits – nichts zu tun.")

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
