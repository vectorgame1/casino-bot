# state_manager.py — сохранение MODS и MOD_LIMITS между рестартами
import json
import os
from datetime import date, datetime

STATE_FILE = "state.json"


def _load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"mods": [], "mod_limits": {}, "prs": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "prs" not in data:
                data["prs"] = []
            return data
    except Exception:
        return {"mods": [], "mod_limits": {}, "prs": []}


def _save(data: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_mods():
    data = _load()
    mods = list(data.get("mods", []))
    limits = {}
    for k, v in data.get("mod_limits", {}).items():
        try:
            ws = v.get("week_start")
            if isinstance(ws, str):
                ws = date.fromisoformat(ws)
            limits[int(k)] = {"week_start": ws or date.today(), "given": int(v.get("given", 0))}
        except Exception:
            continue
    return mods, limits


def save_mods(mods: list, limits: dict):
    data = _load()
    data["mods"] = list(mods)
    data["mod_limits"] = {
        str(uid): {
            "week_start": (lim.get("week_start") or date.today()).isoformat(),
            "given": int(lim.get("given", 0)),
        }
        for uid, lim in limits.items()
    }
    _save(data)


def refresh_week(uid: int, limits: dict) -> dict:
    """Сбрасывает лимит, если прошла неделя."""
    today = date.today()
    lim = limits.get(uid) or {"week_start": today, "given": 0}
    if (today - lim["week_start"]).days >= 7:
        lim = {"week_start": today, "given": 0}
    limits[uid] = lim
    return lim


# ================= ПИАРЩИКИ (НОВЫЕ ФУНКЦИИ) =================

def load_prs():
    data = _load()
    return list(data.get("prs", []))


def save_prs(prs: list):
    data = _load()
    data["prs"] = list(prs)
    _save(data)