#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reminder – Kiosk UI (480x320)
• Auto-Refresh (KIOSK_REFRESH_SECONDS, default 30s)
• Zustands-Zyklus (1..4) bleibt per Session erhalten
• Farbige Karten/Tags, amber 'hoch'-Tag, rotes 'Überfällig'
• Bestätigungsdialog für Erledigt/Verwerfen
• 'Fällig': Datum + (Tage/Stunden), rot bei < 24h (inkl. überfällig)
• NEU: Ansichts-Indikator (zeigt Modus + Stückzahl pro Priorität)
"""

from __future__ import annotations
from datetime import date, datetime, time
from enum import Enum
from typing import Optional
import os, math
from collections import Counter

from flask import Flask, render_template, request, redirect, url_for, session, Response
from jinja2 import DictLoader
from sqlalchemy import create_engine, ForeignKey, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, relationship
from sqlalchemy.types import String, Text, Date

# ----------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------
DB_PATH = os.environ.get("REMINDER_DB", "reminder.sqlite3")
SECRET_KEY = os.environ.get("REMINDER_SECRET", "dev-secret-change-me")
DEFAULT_KIOSK_USER = os.environ.get("KIOSK_DEFAULT_USER")  # optional Redirect von /
REFRESH_SECONDS = int(os.environ.get("KIOSK_REFRESH_SECONDS", "30"))  # Auto-Refresh

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET_KEY, SEND_FILE_MAX_AGE_DEFAULT=0)
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)

class Base(DeclarativeBase): pass

# ----------------------------------------------------------------------------
# Modelle (Strings müssen zur Main-App passen)
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
    creator = relationship("User", foreign_keys=[creator_id])
    assignee = relationship("User", foreign_keys=[assignee_id])
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

def get_db() -> Session: return Session(engine)
def _ci_name(db: Session, name: str) -> Optional[User]:
    return db.scalar(select(User).where(func.lower(User.name) == (name or "").strip().lower()))

# ----------------------------------------------------------------------------
# Komfort: Root & Favicon
# ----------------------------------------------------------------------------
@app.route("/")
def root():
    if DEFAULT_KIOSK_USER:
        return redirect(url_for("kiosk_view", name=DEFAULT_KIOSK_USER))
    return ("Kiosk läuft. Aufruf: /kiosk/<NAME> (z. B. /kiosk/Alice) "
            "– oder KIOSK_DEFAULT_USER setzen.", 200,
            {"Content-Type": "text/plain; charset=utf-8"})

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

# ----------------------------------------------------------------------------
# Templates (mit Ansichts-Indikator)
# ----------------------------------------------------------------------------
TEMPLATES = {
"base.html": r"""
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=480, height=320, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Kiosk</title>
<style>
  :root{
    --bg:#0c0e12; --fg:#e8eaf0; --muted:#9aa3b2; --accent:#5aa2ff;
    --pad:6px; --fs-xs:10px; --fs-m:14px; --touch:40px;

    /* Hoch – Tag amber (nicht rot), Karte rötlich */
    --hi-tag:#f59e0b;   --hi-tag-border:#b45309; --hi-tag-text:#000;
    --hi-bg:#3b2020;    --hi-border:#692a2a;

    /* Normal (Blau) */
    --nm-tag:#264ea6;   --nm-bg:#1a2646;   --nm-border:#273b78;

    /* Niedrig (Teal/Grün) */
    --lo-tag:#0c6e56;   --lo-bg:#122e27;   --lo-border:#1f4a40;

    /* Überfällig (Rot) */
    --ov-tag:#b91c1c;   --ov-border:#8a1313;

    /* Zeitwarnung */
    --hrs-warn:#ff6b6b;
  }

  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);
            font-family: system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;}
  .app{display:flex;width:100vw;height:100vh}
  .left{flex:2;padding:var(--pad)}
  .right{flex:1;padding:var(--pad);border-left:1px solid #0e1220;display:flex;flex-direction:column;gap:6px}

  .task{display:grid;grid-template-columns:1fr;gap:2px;align-items:center;
        padding:6px;margin-bottom:4px;border-radius:8px;min-height:var(--touch);cursor:pointer;}
  .hdr{display:flex;align-items:center;justify-content:space-between;gap:6px}
  .desc{font-size:var(--fs-m);font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
  .tags{display:flex;gap:4px}
  .due{font-size:var(--fs-xs); color:var(--muted)}
  .due .timebreak.soon{ color:var(--hrs-warn); font-weight:800; }
  .tag{font-size:var(--fs-xs);padding:2px 6px;border-radius:999px;color:#fff;border:1px solid transparent}

  .task.high   { background:var(--hi-bg); border:1px solid var(--hi-border); }
  .task.normal { background:var(--nm-bg); border:1px solid var(--nm-border); }
  .task.low    { background:var(--lo-bg); border:1px solid var(--lo-border); }

  .tag.high   { background:var(--hi-tag);   border-color:var(--hi-tag-border); color:var(--hi-tag-text); }
  .tag.normal { background:var(--nm-tag);   border-color:#1f3e85; }
  .tag.low    { background:var(--lo-tag);   border-color:#0a5746; }
  .tag.overdue{ background:var(--ov-tag);   border-color:var(--ov-border); }

  .sel{outline:2px solid var(--accent); outline-offset:0}

  .btn{width:100%;height:var(--touch);border-radius:10px;border:1px solid #2a344e;
       font-weight:800;font-size:var(--fs-m);color:var(--fg);background:#1a2238}
  .ok{background:#1d8f5a;border-color:#256e4c}
  .bad{background:#9b3a2f;border-color:#7a2c25}
  .alt{background:#28324f;border-color:#2c3a64}
  .btn:active{transform:scale(.98)}

  .empty{color:var(--muted);font-size:var(--fs-xs);text-align:center;padding:6px}

  /* Modal */
  #confirm_overlay{
    position:fixed; inset:0; background:rgba(0,0,0,.55);
    display:none; align-items:center; justify-content:center; z-index:9999;
  }
  .confirm_card{
    width:calc(100% - 40px); max-width:420px; background:#101623;
    border:1px solid #2a344e; border-radius:12px; padding:10px; display:flex; flex-direction:column; gap:8px;
  }
  .confirm_title{ font-weight:800; font-size:var(--fs-m) }
  .confirm_text{ font-size:var(--fs-xs); color:var(--muted) }
  .confirm_actions{ display:flex; gap:8px }
  .btn.sm{ height:34px; font-size:12px; font-weight:800; }

  /* Mode indicator */
  .modebox{
    background:#0f1422; border:1px solid #2a344e; border-radius:10px;
    padding:8px; display:flex; flex-direction:column; gap:4px;
  }
  .mode-title{ font-weight:800; font-size:var(--fs-m) }
  .mode-desc{ font-size:var(--fs-xs); color:var(--muted) }
</style>
</head>
<body>
  <div class="app">
    <div class="left">{% block left %}{% endblock %}</div>
    <div class="right">{% block right %}{% endblock %}</div>
  </div>

  <!-- Bestätigungsdialog -->
  <div id="confirm_overlay" role="dialog" aria-modal="true" aria-labelledby="confirm_title">
    <div class="confirm_card">
      <div id="confirm_title" class="confirm_title">Bestätigen</div>
      <div id="confirm_text" class="confirm_text">Aktion wirklich ausführen?</div>
      <div class="confirm_actions">
        <button id="confirm_cancel" class="btn sm">Abbrechen</button>
        <button id="confirm_ok" class="btn sm">Bestätigen</button>
      </div>
    </div>
  </div>

<script>
  // Auswahl-Logik
  const selectTask = (id) => {
    document.querySelectorAll('.task').forEach(el=>el.classList.remove('sel'));
    const el=document.querySelector(`.task[data-id="${id}"]`);
    if(el){el.classList.add('sel');}
    const hidden=document.getElementById('selected_task_id');
    if(hidden) hidden.value=id;
  };

  // Buttons & Confirm
  let pendingAction = null;
  const form         = document.getElementById('action_form');
  const btnDone      = document.getElementById('btn_done');
  const btnDiscard   = document.getElementById('btn_discard');
  const btnCycle     = document.getElementById('btn_cycle');
  const overlay      = document.getElementById('confirm_overlay');
  const confirmText  = document.getElementById('confirm_text');
  const confirmOk    = document.getElementById('confirm_ok');
  const confirmCancel= document.getElementById('confirm_cancel');
  const actionInput  = document.getElementById('action_input');

  function openConfirm(action){
    const id = document.getElementById('selected_task_id').value;
    if(!id){
      alert("Bitte zuerst eine Aufgabe auswählen.");
      return;
    }
    pendingAction = action;
    const el = document.querySelector(`.task[data-id="${id}"] .desc`);
    const title = (action==='done' ? "Erledigt" : "Verwerfen");
    confirmText.textContent = `${title} – „${el ? el.textContent : 'Ausgewählte Aufgabe'}“?`;
    confirmOk.classList.remove('ok','bad','btn');
    confirmOk.classList.add(action==='done' ? 'ok' : 'bad', 'btn'); // grün/rot
    overlay.style.display='flex';
  }
  function closeConfirm(){ overlay.style.display='none'; pendingAction=null; }

  if(btnDone){    btnDone.addEventListener('click', ()=>openConfirm('done')); }
  if(btnDiscard){ btnDiscard.addEventListener('click', ()=>openConfirm('discard')); }
  if(btnCycle){
    btnCycle.addEventListener('click', ()=>{
      actionInput.value='cycle';
      form.submit();
    });
  }

  confirmCancel.addEventListener('click', closeConfirm);
  confirmOk.addEventListener('click', ()=>{
    if(!pendingAction) return;
    actionInput.value=pendingAction;
    closeConfirm();
    form.submit();
  });

  // Erste Auswahl vornehmen
  window.addEventListener('DOMContentLoaded',()=>{
    const first=document.querySelector('.task');
    if(first) selectTask(first.dataset.id);
  });

  // ---- Auto-Refresh (pausiert, wenn Confirm-Dialog offen ist) ----
  const REFRESH_MS = {{ refresh_ms }};
  if (REFRESH_MS > 0) {
    setInterval(() => {
      const ov = document.getElementById('confirm_overlay');
      const isOpen = ov && getComputedStyle(ov).display !== 'none';
      if (!isOpen) {
        const url = new URL(window.location.href);
        url.searchParams.set('_ts', Date.now().toString());
        window.location.replace(url.toString());
      }
    }, REFRESH_MS);
  }
</script>
</body>
</html>
""",

"view.html": r"""
{% extends 'base.html' %}
{% block left %}
  {% for t in tasks_to_show %}
    {% set cls = 'high' if t.priority == 'hoch' else ('normal' if t.priority == 'normal' else 'low') %}
    {% set overdue = (t.due_date is not none) and (t.due_date < today) %}
    {% set hrs_total = hours_left_map.get(t.id) %}
    {% set dh_text = dh_text_map.get(t.id) %}
    <div class="task {{ cls }}" data-id="{{ t.id }}" onclick="selectTask('{{ t.id }}')">
      <div class="hdr">
        <div class="desc">{{ t.description }}</div>
        <div class="tags">
          <div class="tag {{ cls }}">{{ t.priority }}</div>
          {% if overdue %}<div class="tag overdue">Überfällig</div>{% endif %}
        </div>
      </div>
      <div class="due">
        Fällig: {{ t.due_date.isoformat() if t.due_date else '–' }}
        {% if hrs_total is not none %}
          (<span class="timebreak {% if hrs_total < 24 %}soon{% endif %}">{{ dh_text }}</span>)
        {% endif %}
      </div>
    </div>
  {% endfor %}
  {% if not tasks_to_show %}<div class="empty">Keine offenen Aufgaben</div>{% endif %}
{% endblock %}

{% block right %}
  <!-- Ansicht-Indicator -->
  <div class="modebox">
    <div class="mode-title">Ansicht {{ mode }}</div>
    <div class="mode-desc">{{ mode_summary }}</div>
    <div class="mode-desc">Aktualisierung: alle {{ refresh_sec }}s</div>
  </div>

  <form id="action_form" method="post" action="{{ url_for('kiosk_action', name=user.name) }}" style="display:flex;flex-direction:column;gap:6px;margin-top:6px">
    <input type="hidden" id="selected_task_id" name="task_id" value="">
    <input type="hidden" id="action_input"   name="action"  value="">
    <button class="btn ok"  id="btn_done"    type="button">✔ Erledigt</button>
    <button class="btn bad" id="btn_discard" type="button">🗑 Verwerfen</button>
    <button class="btn alt" id="btn_cycle"   type="button">↻ Ansicht wechseln</button>
  </form>
{% endblock %}
"""
}
app.jinja_loader = DictLoader(TEMPLATES)

# ----------------------------------------------------------------------------
# Routen & Logik
# ----------------------------------------------------------------------------
@app.route("/kiosk/<name>")
def kiosk_view(name: str):
    with get_db() as db:
        user = _ci_name(db, name)
        if not user:
            return (f"Unbekannter Benutzer: {name}", 404)

        key = f"mode_{user.name.strip().lower()}"
        mode = session.get(key, 1)
        if mode not in (1, 2, 3, 4): mode = 1

        # Offene Aufgaben – datierte zuerst (früheste oben), undatierte zuletzt
        q = (
            select(Task)
            .where(Task.assignee_id == user.id, Task.status == Status.open.value)
            .order_by(Task.due_date.is_(None), Task.due_date, Task.created_at)
        )
        all_open_sorted = db.scalars(q).all()

        today = date.today()

        def base_for_mode():
            if mode == 1:
                # Nur due_date >= heute (keine Vergangenheit, keine undatierten)
                return [t for t in all_open_sorted if t.due_date is not None and t.due_date >= today]
            # Modi 2–4: inkl. Vergangenheit & undatiert
            return list(all_open_sorted)

        base = base_for_mode()

        def take(prio: str, n: int):
            return [t for t in base if t.priority == prio][:n]

        if mode == 1:
            tasks_to_show = take(Priority.high.value, 1) + \
                            take(Priority.normal.value, 2) + \
                            take(Priority.low.value, 1)
        elif mode == 2:
            tasks_to_show = take(Priority.high.value, 4)
        elif mode == 3:
            tasks_to_show = take(Priority.normal.value, 4)
        else:
            tasks_to_show = take(Priority.low.value, 4)

        # ---- Zeit bis Ende des Fälligkeitstags (in Stunden) + Darstellung "x Tag(e), y Stunde(n)"
        def hours_left_until_day_end(d: Optional[date]) -> Optional[int]:
            if d is None:
                return None
            now = datetime.now()
            due_end = datetime.combine(d, time(23, 59, 59))
            delta = due_end - now
            return math.floor(delta.total_seconds() / 3600)

        def de_plural(n: int, singular: str, plural: str) -> str:
            return singular if abs(n) == 1 else plural

        def format_days_hours(total_hours: int) -> str:
            sign = "-" if total_hours < 0 else ""
            ah = abs(total_hours)
            days = ah // 24
            hours = ah % 24
            if days == 0:
                return f"{sign}{hours} {de_plural(hours,'Stunde','Stunden')}"
            else:
                return f"{sign}{days} {de_plural(days,'Tag','Tage')}, {hours} {de_plural(hours,'Stunde','Stunden')}"

        hours_left_map = {t.id: hours_left_until_day_end(t.due_date) for t in tasks_to_show}
        dh_text_map = {tid: (format_days_hours(h) if h is not None else None)
                       for tid, h in hours_left_map.items()}

        # ---- Ansichts-Indikator: echte Stückzahlen pro Prio der aktuell sichtbaren Liste
        cnt = Counter(t.priority for t in tasks_to_show)
        mode_summary = f"{cnt.get('hoch',0)}× hoch, {cnt.get('normal',0)}× normal, {cnt.get('niedrig',0)}× niedrig"

        # Refresh-Intervall
        refresh_sec = max(0, int(REFRESH_SECONDS))
        refresh_ms = refresh_sec * 1000

        return render_template("view.html",
                               user=user,
                               tasks_to_show=tasks_to_show,
                               today=today,
                               refresh_ms=refresh_ms,
                               refresh_sec=refresh_sec,
                               hours_left_map=hours_left_map,
                               dh_text_map=dh_text_map,
                               mode=mode,
                               mode_summary=mode_summary)

@app.route("/kiosk/<name>/action", methods=["POST"])
def kiosk_action(name: str):
    action = request.form.get("action")

    if action == "cycle":
        key = f"mode_{name.strip().lower()}"
        mode = session.get(key, 1)
        session[key] = 1 if mode >= 4 else mode + 1
        session.modified = True
        return redirect(url_for("kiosk_view", name=name))

    # Statusänderung erfordert gewählte Task-ID
    task_id = request.form.get("task_id")
    if not task_id:
        return redirect(url_for("kiosk_view", name=name))

    with get_db() as db:
        task = db.get(Task, int(task_id))
        if not task:
            return redirect(url_for("kiosk_view", name=name))
        if action == "done":
            task.status = Status.done.value
        elif action == "discard":
            task.status = Status.discarded.value
        db.commit()
    return redirect(url_for("kiosk_view", name=name))

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
