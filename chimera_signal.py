# -*- coding: utf-8 -*-
"""
chimera_signal.py — CHIMERA SIGNAL ENGINE v2
=============================================
Трёхуровневый алгоритм поиска лучшей ставки дня.

Уровень 1: МАТЕМАТИКА
  - ELO advantage (разрыв рейтингов)
  - Форма (W/D/L последние 5)
  - Ценность кэфа (наша prob vs implied prob)
  - Сила вероятности

Уровень 2: AI ВЕРИФИКАЦИЯ (быстрый батч-запрос для топ-3)
  - Один промпт → оценка всех кандидатов
  - Бот определяет лучшую ставку и причину

Уровень 3: ИТОГОВЫЙ CHIMERA SCORE
  - Математика + AI boost → финальный рейтинг 0-100
"""

import html
import json
import os
import logging
import re

def _strip_cjk(text: str) -> str:
    return re.sub(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', '', text).strip()
from typing import List, Dict, Optional
from config_thresholds import CHIMERA_WEIGHTS, MIN_CHIMERA_SCORE

logger = logging.getLogger(__name__)

# Веса и пороги из config_thresholds.py — редактируй там
ELO_WEIGHT    = CHIMERA_WEIGHTS["elo"]
FORM_WEIGHT   = CHIMERA_WEIGHTS["form"]
VALUE_WEIGHT  = CHIMERA_WEIGHTS["value"]
PROB_WEIGHT   = CHIMERA_WEIGHTS["prob"]
XG_WEIGHT     = CHIMERA_WEIGHTS["xg"]
LINE_WEIGHT   = CHIMERA_WEIGHTS["line"]
H2H_WEIGHT    = CHIMERA_WEIGHTS["h2h"]
AI_BOOST      = CHIMERA_WEIGHTS["ai_boost"]
AI_PENALTY    = CHIMERA_WEIGHTS["ai_penalty"]

# ─── Исторический калибратор ──────────────────────────────────────────────────
_history_cache: dict = {}
_history_cache_ts: float = 0


def get_historical_calibration() -> dict:
    """
    Читает прошлые результаты из БД и возвращает калибровочные данные:
    - accuracy_by_prob_bucket: точность по диапазонам вероятностей
    - model_bias: системное смещение (наша prob vs реальная частота побед)
    Кэшируется на 1 час.
    """
    import time
    global _history_cache, _history_cache_ts
    if time.time() - _history_cache_ts < 1800 and _history_cache:
        return _history_cache

    result = {"bias": 0.0, "buckets": {}, "total_checked": 0}
    try:
        import sqlite3
        db_path = "chimera_predictions.db"
        if not os.path.exists(db_path):
            return result
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("""
                SELECT ensemble_home, ensemble_draw, ensemble_away,
                       real_outcome, recommended_outcome
                FROM football_predictions
                WHERE real_outcome IS NOT NULL
                  AND ensemble_home IS NOT NULL
                LIMIT 200
            """).fetchall()

        total = len(rows)
        if total < 10:
            return result

        # Считаем смещение: наша вероятность vs реальная частота
        prob_sum = 0.0
        win_count = 0
        buckets: dict = {}  # {bucket_key: {"pred": 0, "win": 0}}

        for row in rows:
            ens_h, ens_d, ens_a, real_out, rec_out = row
            probs = {"home_win": ens_h or 0, "draw": ens_d or 0, "away_win": ens_a or 0}
            pred_prob = probs.get(rec_out or "", 0)
            won = 1 if rec_out == real_out else 0

            prob_sum += pred_prob
            win_count += won

            bucket = int(pred_prob * 10) * 10  # 40, 50, 60, 70...
            if bucket not in buckets:
                buckets[bucket] = {"pred": 0, "win": 0, "count": 0}
            buckets[bucket]["pred"] += pred_prob
            buckets[bucket]["win"] += won
            buckets[bucket]["count"] += 1

        avg_pred = prob_sum / total if total > 0 else 0.5
        avg_real = win_count / total if total > 0 else 0.5
        bias = avg_real - avg_pred  # положительное = мы недооцениваем, отриц = переоцениваем

        result = {
            "bias": round(bias, 3),
            "buckets": buckets,
            "total_checked": total,
            "avg_pred": round(avg_pred, 3),
            "avg_real": round(avg_real, 3),
        }
        logger.info(f"[CHIMERA Cal] {total} матчей | Смещение: {bias:+.1%} | Точность: {avg_real:.1%}")

    except Exception as e:
        logger.warning(f"[CHIMERA Cal] Ошибка чтения истории: {e}")

    _history_cache = result
    _history_cache_ts = time.time()
    return result


def calibrate_probability(prob: float, cal: dict) -> float:
    """Корректирует вероятность на основе исторического смещения модели."""
    if not cal or not cal.get("total_checked", 0):
        return prob
    bias = cal.get("bias", 0.0)
    # Применяем 50% от смещения (не весь bias — могут быть выборки малого объёма)
    calibrated = prob + bias * 0.5
    return max(0.10, min(0.90, calibrated))


def _form_score(form_str: str) -> float:
    """
    Оценивает форму от 0.0 до 1.0 с экспоненциальным весом.
    Последний матч важнее: веса [1.0, 0.65, 0.45, 0.30, 0.20].
    W=3, D=1, L=0 очков за матч, взвешенные по давности.
    """
    if not form_str:
        return 0.5
    results = form_str.upper()[-5:]
    weights = [1.0, 0.65, 0.45, 0.30, 0.20]
    max_pts = sum(3 * w for w in weights[:len(results)])
    if max_pts == 0:
        return 0.5
    pts = sum(
        (3 if c == 'W' else (1 if c == 'D' else 0)) * weights[i]
        for i, c in enumerate(results)
    )
    return min(1.0, pts / max_pts)


def _implied_prob(odds: float) -> float:
    return 1.0 / odds if odds > 1.02 else 0.0


_kelly_cache: dict = {}
_kelly_cache_ts: float = 0


def _get_sport_kelly_multiplier(league: str) -> float:
    """
    Динамический Kelly-множитель на основе реальной точности из БД.
    Чем выше точность ставок по спорту — тем больше Kelly.

    Базовые значения (пока нет данных):
      tennis=0.65, basketball=0.55, football=0.40, hockey=0.35, cs2=0.25
    Обновляются автоматически каждые 2 часа из chimera_predictions.db.
    """
    import time as _t
    global _kelly_cache, _kelly_cache_ts
    if _t.time() - _kelly_cache_ts < 7200 and _kelly_cache:
        pass  # используем кеш
    else:
        # Базовые значения — используются пока данных мало
        defaults = {
            "tennis":     0.65,
            "basketball": 0.55,
            "football":   0.40,
            "hockey":     0.35,
            "cs2":        0.25,
        }
        try:
            import sqlite3, os as _os
            db = "chimera_predictions.db"
            if _os.path.exists(db):
                with sqlite3.connect(db) as _conn:
                    for sport, table in [
                        ("football",   "football_predictions"),
                        ("basketball", "basketball_predictions"),
                        ("tennis",     "tennis_predictions"),
                        ("hockey",     "hockey_predictions"),
                        ("cs2",        "cs2_predictions"),
                    ]:
                        try:
                            row = _conn.execute(f"""
                                SELECT COUNT(*), SUM(is_correct)
                                FROM {table}
                                WHERE bet_signal NOT LIKE '%НЕ%'
                                  AND bet_signal LIKE '%СТАВИТЬ%'
                                  AND is_correct IS NOT NULL
                                  AND real_outcome NOT IN ('expired','')
                            """).fetchone()
                            total, wins = row[0] or 0, row[1] or 0
                            if total >= 15:
                                acc = wins / total
                                # Формула: multiplier = acc * 0.8, диапазон 0.20..0.75
                                defaults[sport] = round(max(0.20, min(0.75, acc * 0.8)), 2)
                        except Exception:
                            pass
        except Exception:
            pass
        _kelly_cache = defaults
        _kelly_cache_ts = _t.time()

    # Определяем спорт по league-строке
    ll = (league or "").lower()
    if any(k in ll for k in ["nba", "nhl", "basket", "euro", "bball", "eur"]):
        return _kelly_cache.get("basketball", 0.55)
    if any(k in ll for k in ["hockey", "icehockey", "shl", "ahl", "liiga"]):
        return _kelly_cache.get("hockey", 0.35)
    if any(k in ll for k in ["tennis", "atp", "wta", "itf"]):
        return _kelly_cache.get("tennis", 0.65)
    if any(k in ll for k in ["cs2", "csgo", "esport"]):
        return _kelly_cache.get("cs2", 0.25)
    return _kelly_cache.get("football", 0.40)


def compute_chimera_score(
    home_team: str,
    away_team: str,
    home_prob: float,
    away_prob: float,
    draw_prob: float,
    bookmaker_odds: dict,
    home_form: str = "",
    away_form: str = "",
    elo_home: float = 1500,
    elo_away: float = 1500,
    league: str = "",
    home_xg_stats: dict = None,
    away_xg_stats: dict = None,
    line_movement: dict = None,
    h2h_data: dict = None,
    apply_calibration: bool = True,
) -> List[Dict]:
    """
    Вычисляет CHIMERA Score для каждого исхода матча.
    Возвращает список кандидатов, отсортированных по баллам (лучший первый).
    apply_calibration=False для баскетбола/хоккея/теннис: калибровка построена
    на футбольных данных и искажает EV других видов спорта.
    """
    candidates = []
    # Калибратор применяем только для футбола — он обучен на football_predictions
    cal = get_historical_calibration() if apply_calibration else {}

    for outcome_key, prob, odds_key, team, form, elo_fav, elo_opp, xg_stats_fav, xg_stats_opp in [
        ("П1", home_prob, "home_win", home_team, home_form, elo_home, elo_away, home_xg_stats, away_xg_stats),
        ("П2", away_prob, "away_win", away_team, away_form, elo_away, elo_home, away_xg_stats, home_xg_stats),
        ("Х",  draw_prob, "draw",     "Ничья",   "",         0,        0,       None,          None),
    ]:
        odds = bookmaker_odds.get(odds_key, 0)
        if not odds or odds <= 1.20 or prob <= 0:
            continue

        implied = _implied_prob(odds)

        # Для футбола: проверяем расхождение ДО калибровки (используем сырую вероятность модели)
        # Данные: крупные расхождения с рынком (>18pp) дают ~15-20% точность (хуже случайного)
        if apply_calibration and outcome_key in ("П1", "П2") and (prob - implied) > 0.12:
            continue

        # Применяем исторический калибратор (только для футбола) — после проверки дивергенции
        prob = calibrate_probability(prob, cal)

        # ── 1. ELO преимущество (0 → 25 pts) ─────────────────────────────
        elo_gap = max(0, elo_fav - elo_opp) if (elo_fav > 0 and elo_opp > 0) else 0
        elo_pts = min(ELO_WEIGHT, elo_gap / 8)

        # ── 2. Форма (0 → 20 pts) ─────────────────────────────────────────
        form_val = _form_score(form) if outcome_key != "Х" else 0.5
        form_pts = form_val * FORM_WEIGHT

        # ── 3. Ценность кэфа (0 → 30 pts) ────────────────────────────────
        # Главный критерий: наша вероятность > подразумеваемой
        value = prob - implied
        # Нормируем: +5% value = 15 pts, +10% = 30 pts
        value_pts = max(0, min(VALUE_WEIGHT, value * 300))

        # ── 4. Сила вероятности (0 → 15 pts) ─────────────────────────────
        # prob=0.52 → 4 pts, prob=0.65 → 15 pts, prob=0.80 → 15 pts (cap)
        prob_pts = max(0, min(PROB_WEIGHT, (prob - 0.50) * 100))

        # ── 5. xG качество (0 → 10 pts) ───────────────────────────────────
        # Бонус: атакующий xG фаворита высок И защитный xG соперника слаб
        xg_pts = 0.0
        if xg_stats_fav and outcome_key != "Х":
            fav_xg  = xg_stats_fav.get('avg_xg_last5', 0.0)
            opp_xga = xg_stats_opp.get('avg_xga_last5', 999.0) if xg_stats_opp else 1.5
            attack_score = min(1.0, max(0.0, (fav_xg - 1.0) / 1.5))
            defence_gap  = min(1.0, max(0.0, (opp_xga - fav_xg) / 1.0))
            xg_pts = (attack_score * 0.6 + defence_gap * 0.4) * XG_WEIGHT

        # ── 6. Движение линии (±15 pts) ────────────────────────────────────
        line_pts = 0.0
        if line_movement:
            try:
                from line_movement import get_movement_score
                outcome_map = {"П1": "home_win", "П2": "away_win", "Х": "draw"}
                line_pts = get_movement_score(line_movement, outcome_map.get(outcome_key, ""))
            except Exception:
                pass

        # ── 7. H2H история (0 → 8 pts) ─────────────────────────────────────
        h2h_pts = 0.0
        if h2h_data and outcome_key != "Х":
            total_h2h = h2h_data.get("total", 0)
            if total_h2h >= 3:
                if outcome_key == "П1":
                    win_rate = h2h_data.get("home_win_rate", 0.33)
                else:
                    win_rate = h2h_data.get("away_win_rate", 0.33)
                # Бонус если H2H win_rate сильно выше базовой 0.33
                h2h_pts = max(0.0, min(H2H_WEIGHT, (win_rate - 0.33) * H2H_WEIGHT / 0.30))

        chimera_score = elo_pts + form_pts + value_pts + prob_pts + xg_pts + line_pts + h2h_pts

        ev = round((prob * odds - 1) * 100, 1)
        kelly_raw = max(0, (prob * odds - 1) / (odds - 1)) * 100 if odds > 1 else 0
        # Smart Kelly: множитель зависит от реальной точности спорта по БД
        _sport_kelly_mult = _get_sport_kelly_multiplier(league)
        kelly = round(min(kelly_raw * _sport_kelly_mult, 10.0), 1)

        candidates.append({
            "sport":         "football",
            "home":          home_team,
            "away":          away_team,
            "outcome":       outcome_key,
            "team":          team,
            "odds":          round(odds, 2),
            "prob":          round(prob * 100, 1),
            "implied_prob":  round(implied * 100, 1),
            "ev":            ev,
            "kelly":         kelly,
            "chimera_score": round(chimera_score, 1),
            "elo_pts":       round(elo_pts, 1),
            "form_pts":      round(form_pts, 1),
            "value_pts":     round(value_pts, 1),
            "prob_pts":      round(prob_pts, 1),
            "xg_pts":        round(xg_pts, 1),
            "line_pts":      round(line_pts, 1),
            "h2h_pts":       round(h2h_pts, 1),
            "form":          form[-5:] if form else "",
            "elo_gap":       round(elo_gap),
            "league":        league,
            "ai_confirmed":  None,   # заполняется позже
            "ai_confidence": None,
            "ai_reason":     None,
        })

    candidates.sort(key=lambda x: x["chimera_score"], reverse=True)
    return candidates


def _build_candidates_text(candidates: List[Dict]) -> str:
    lines = []
    for i, c in enumerate(candidates[:5], 1):
        sport = c.get("sport", "football")
        news_suffix = f"\n   📰 {c['news_context']}" if c.get("news_context") else ""
        if sport == "tennis":
            surf_icons = {"hard": "🎾 hard", "clay": "🟫 clay", "grass": "🟩 grass"}
            surf = surf_icons.get(c.get("surface", "hard"), "hard")
            lines.append(
                f"{i}. {c['home']} vs {c['away']} [{surf}] | "
                f"Победа: {c['team']} (рейт.#{c.get('rank','?')}) @ {c['odds']} | "
                f"Вероятность: {c['prob']}% (бук: {c['implied_prob']}%) | "
                f"EV: {c['ev']:+.1f}% | Разрыв рейтингов: #{c.get('rank','?')} vs #{c.get('opp_rank','?')} | "
                f"Score: {c['chimera_score']}{news_suffix}"
            )
        elif sport == "cs2":
            lines.append(
                f"{i}. {c['home']} vs {c['away']} [CS2] | "
                f"Победа: {c['team']} ({c['outcome']}) @ {c['odds']} | "
                f"Вероятность: {c['prob']}% (бук: {c['implied_prob']}%) | "
                f"EV: {c['ev']:+.1f}% | Score: {c['chimera_score']}{news_suffix}"
            )
        elif sport == "basketball":
            lines.append(
                f"{i}. {c['home']} vs {c['away']} [баскетбол] | "
                f"Победа: {c['team']} ({c['outcome']}) @ {c['odds']} | "
                f"Вероятность: {c['prob']}% (бук: {c['implied_prob']}%) | "
                f"EV: {c['ev']:+.1f}% | ELO разрыв: {c.get('elo_gap', 0)} | Score: {c['chimera_score']}{news_suffix}"
            )
        else:
            line = (
                f"{i}. {c['home']} vs {c['away']} [football] | "
                f"Ставка: {c['team']} ({c['outcome']}) @ {c['odds']} | "
                f"Вероятность: {c['prob']}% (бук: {c['implied_prob']}%) | "
                f"EV: {c['ev']:+.1f}% | Форма: {c['form'] or '—'} | "
                f"ELO разрыв: {c['elo_gap']} | Score: {c['chimera_score']}"
            )
            if c.get("news_context"):
                line += f"\n   📰 Новости: {c['news_context']}"
            lines.append(line)
    return "\n".join(lines)


def run_ai_verification(
    candidates: List[Dict],
    gpt_client=None,
    groq_client=None,
    gpt_model: str = "gpt-4.1-mini",
    llama_model: str = "llama-3.3-70b-versatile",
) -> List[Dict]:
    """
    Двухуровневая AI верификация:
      1. GPT-4.1-mini — выбирает лучшую ставку по математике
      2. Llama 3.3 70B — добавляет логическое обоснование (тактика, тренды)
    Оба AI независимы. Если оба согласны → двойной буст.
    """
    if not candidates:
        return candidates

    top = candidates[:5]
    cands_text = _build_candidates_text(top)

    import concurrent.futures as _cf_ai

    # ── Уровень 1: GPT — математический выбор ─────────────────────────────
    gpt_best_idx   = None
    gpt_confidence = 60
    gpt_reason     = ""
    gpt_skip       = []

    top_sport = top[0].get("sport", "football") if top else "football"
    if top_sport == "tennis":
        criteria = "EV > 3% = ценность, большой разрыв рейтингов = надёжность, специализация на поверхности = ключевой фактор."
    elif top_sport == "cs2":
        criteria = "EV > 3% = ценность, форма WW = хорошо, стабильность команды важна."
    elif top_sport == "basketball":
        criteria = "EV > 3% = ценность, большой ELO разрыв = надёжность, back-to-back штраф = риск."
    else:
        criteria = "EV > 3% = ценность, форма WW = хорошо, большой ELO разрыв = надёжность."

    prompt_gpt = f"""Ты — аналитик ставок. Оцени каждую ставку из {len(top)} кандидатов.

{cands_text}

Критерии: {criteria}

JSON ответ:
{{
  "best": 1,
  "confidence": 70,
  "reason": "краткая причина выбора лучшей ставки — называй команду/игрока по имени, не пиши 'Ставка N'",
  "reasons": ["оценка кандидата 1", "оценка кандидата 2", "оценка кандидата 3"],
  "skip": []
}}
"reasons" — массив из {len(top)} строк, по одной оценке на каждого кандидата (1 предложение каждая).
ВАЖНО: в поле "reason" называй команду/игрока по имени. Никогда не пиши "Ставка 1", "Ставка 2" и т.д."""

    best_c_default = top[0]

    def _call_gpt():
        if not gpt_client:
            return None
        try:
            resp = gpt_client.chat.completions.create(
                model=gpt_model,
                messages=[
                    {"role": "system", "content": "Аналитик ставок. Только JSON."},
                    {"role": "user", "content": prompt_gpt},
                ],
                temperature=0.2,
                max_tokens=180,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            logger.warning(f"[CHIMERA GPT] Ошибка: {e}")
            return None

    # ── Уровень 2: Llama — строим промпт по top[0] (параллельно с GPT) ──
    llama_best_idx = None
    llama_logic    = ""

    if groq_client:
        best_c = top[0]  # используем top[0] — GPT ещё не ответил, запускаем параллельно
        best_sport = best_c.get("sport", "football")

        if best_sport == "tennis":
            surface = best_c.get("surface", "hard")
            surf_names = {"hard": "хард", "clay": "грунт", "grass": "трава"}
            surf_ru = surf_names.get(surface, "хард")
            analyst_role = "тактический аналитик тенниса"
            context_block = (
                f"Поверхность: {surf_ru}\n"
                f"Рейтинг игрока: #{best_c.get('rank', '?')} vs соперник #{best_c.get('opp_rank', '?')}\n"
                f"H2H: {best_c.get('h2h_wins', 0)}/{best_c.get('h2h_total', 0)} в пользу игрока\n"
                f"Форма: {best_c.get('form') or 'нет данных'}"
            )
            questions = (
                "1. Подходит ли стиль игрока этой поверхности?\n"
                "2. Есть ли у игрока психологическое преимущество (H2H, текущая форма)?\n"
                "3. Риски: травмы, усталость, сложный сетка турнира?"
            )
        elif best_sport == "cs2":
            analyst_role = "тактический аналитик CS2"
            context_block = (
                f"Форма: {best_c.get('form') or 'нет данных'}\n"
                f"EV: {best_c['ev']:+.1f}%"
            )
            questions = (
                "1. Подтверждает ли форма и тренд эту ставку?\n"
                "2. Есть ли логические причины НЕ ставить?\n"
                "3. Стабильность состава и текущий моментум?"
            )
        elif best_sport == "basketball":
            analyst_role = "тактический аналитик баскетбола"
            context_block = (
                f"Форма: {best_c.get('form') or 'нет данных'}\n"
                f"ELO разрыв: {best_c.get('elo_gap', 0)} очков\n"
                f"EV: {best_c['ev']:+.1f}%"
            )
            questions = (
                "1. Подтверждает ли форма и тренд эту ставку?\n"
                "2. Есть ли back-to-back усталость или травмы?\n"
                "3. Какова твоя итоговая рекомендация?"
            )
        else:
            analyst_role = "тактический аналитик футбола"
            context_block = (
                f"Форма: {best_c.get('form') or 'нет данных'}\n"
                f"ELO разрыв: {best_c.get('elo_gap', 0)} очков в пользу фаворита\n"
                f"EV: {best_c['ev']:+.1f}%"
            )
            questions = (
                "1. Подтверждает ли форма и тренд эту ставку?\n"
                "2. Есть ли логические причины НЕ ставить?\n"
                "3. Какова твоя итоговая рекомендация?"
            )

        prompt_llama = f"""Ты — {analyst_role}. Оцени эту ставку с точки зрения ЛОГИКИ и ТРЕНДОВ.

Матч: {best_c['home']} vs {best_c['away']}
Ставка: победа {best_c['team']} @ {best_c['odds']}
{context_block}

Также есть альтернативы:
{cands_text}

Вопросы для анализа:
{questions}

Ответь в JSON:
{{"agree": true, "logic": "2 предложения тактического обоснования", "best_index": 1, "warning": ""}}

agree = согласен ли с GPT выбором
logic = твоё обоснование на русском
best_index = твой выбор (1-{len(top)}), может совпадать с GPT
warning = предупреждение если есть риск (иначе пустая строка)"""

        def _call_llama():
            try:
                resp = groq_client.chat.completions.create(
                    model=llama_model,
                    messages=[
                        {"role": "system", "content": f"Тактический {analyst_role}. Отвечай JSON."},
                        {"role": "user", "content": prompt_llama},
                    ],
                    temperature=0.3,
                    max_tokens=250,
                )
                raw = resp.choices[0].message.content.strip()
                if "```" in raw:
                    raw = raw.split("```")[1].lstrip("json").strip()
                return json.loads(raw)
            except Exception as e:
                logger.warning(f"[CHIMERA Llama] Ошибка: {e}")
                return None
    else:
        def _call_llama():
            return None

    # ── Запускаем GPT и Llama параллельно ────────────────────────────────
    _gpt_data   = None
    _llama_data = None
    with _cf_ai.ThreadPoolExecutor(max_workers=2) as _ai_pool:
        _f_gpt   = _ai_pool.submit(_call_gpt)
        _f_llama = _ai_pool.submit(_call_llama)
        try:
            _gpt_data = _f_gpt.result(timeout=25)
        except Exception as _e:
            logger.warning(f"[CHIMERA GPT] Таймаут/ошибка: {_e}")
        try:
            _llama_data = _f_llama.result(timeout=25)
        except Exception as _e:
            logger.warning(f"[CHIMERA Llama] Таймаут/ошибка: {_e}")

    if _gpt_data:
        gpt_best_idx   = max(0, min(len(top)-1, int(_gpt_data.get("best", 1)) - 1))
        gpt_confidence = int(_gpt_data.get("confidence", 60))
        gpt_reason     = str(_gpt_data.get("reason", ""))
        # Вычищаем "Ставка N" — GPT иногда нумерует несмотря на инструкцию
        import re as _re
        gpt_reason = _re.sub(r'\bСтавка\s+\d+\b\s*', '', gpt_reason, flags=_re.IGNORECASE).strip(" ,.")
        gpt_skip       = [max(0, int(i)-1) for i in _gpt_data.get("skip", [])]
        gpt_reasons    = _gpt_data.get("reasons", [])  # оценки всех кандидатов
        logger.info(f"[CHIMERA GPT] Выбор #{gpt_best_idx+1} | {gpt_confidence}%")
        # Раздаём индивидуальные оценки всем кандидатам
        for i, c in enumerate(top):
            if i < len(gpt_reasons) and gpt_reasons[i]:
                c["ai_reason_individual"] = str(gpt_reasons[i])

    if _llama_data:
        llama_best_idx = max(0, min(len(top)-1, int(_llama_data.get("best_index", 1)) - 1))
        llama_logic    = _strip_cjk(str(_llama_data.get("logic", "")))
        llama_warning  = _strip_cjk(str(_llama_data.get("warning", "")))
        llama_agrees   = bool(_llama_data.get("agree", True))
        logger.info(f"[CHIMERA Llama] Выбор #{llama_best_idx+1} | Согласен: {llama_agrees}")
        best_c["llama_logic"]   = llama_logic
        best_c["llama_warning"] = llama_warning
        best_c["llama_agrees"]  = llama_agrees

    # ── Применяем баллы ────────────────────────────────────────────────────
    for i, c in enumerate(top):
        is_gpt_best   = (i == gpt_best_idx)
        is_llama_best = (i == llama_best_idx)
        is_gpt_skip   = (i in gpt_skip)

        if is_gpt_best and is_llama_best:
            # Оба AI согласны → двойной буст
            c["ai_confirmed"]  = True
            c["ai_confidence"] = gpt_confidence
            c["ai_reason"]     = gpt_reason
            c["chimera_score"] += AI_BOOST * 1.5
        elif is_gpt_best:
            c["ai_confirmed"]  = True
            c["ai_confidence"] = gpt_confidence
            c["ai_reason"]     = gpt_reason
            c["chimera_score"] += AI_BOOST
        elif is_llama_best and not is_gpt_best:
            # Llama нашла другую ставку
            c["ai_confirmed"]  = True
            c["ai_confidence"] = 58
            c["ai_reason"]     = "Llama рекомендует как альтернативу"
            c["chimera_score"] += AI_BOOST * 0.7
        elif is_gpt_skip:
            c["ai_confirmed"]  = False
            c["chimera_score"] = max(0, c["chimera_score"] - AI_PENALTY)
        else:
            # AI не выбрал и не пропустил — даём индивидуальную оценку если есть
            if c.get("ai_reason_individual"):
                c["ai_reason"] = c["ai_reason_individual"]

    candidates.sort(key=lambda x: x["chimera_score"], reverse=True)
    return candidates


def score_label(score: float) -> str:
    """Возвращает эмодзи-метку по баллу."""
    if score >= 75:
        return "🔥🔥🔥 ГОРЯЧИЙ"
    elif score >= 55:
        return "🔥🔥 СИЛЬНЫЙ"
    elif score >= 35:
        return "🔥 ХОРОШИЙ"
    else:
        return "✅ СЛАБЫЙ"


def _format_match_time(commence_time: str) -> tuple:
    """
    Возвращает (time_str, is_live).
    time_str = '15 мар, 18:00' или 'Сегодня 18:00'
    is_live = True если матч уже должен идти (< 3ч назад)
    """
    if not commence_time:
        return "", False
    try:
        from datetime import datetime, timezone, timedelta
        # Парсим ISO формат '2025-03-15T18:00:00Z'
        ct = commence_time.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ct)
        now = datetime.now(timezone.utc)
        diff = (now - dt).total_seconds()
        is_live = 0 < diff < 10800  # матч начался и не более 3ч назад

        MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн",
                     "июл", "авг", "сен", "окт", "ноя", "дек"]
        today = now.date()
        tomorrow = today + timedelta(days=1)
        match_date = dt.date()
        time_part = dt.strftime("%H:%M")

        if match_date == today:
            date_part = "Сегодня"
        elif match_date == tomorrow:
            date_part = "Завтра"
        else:
            date_part = f"{match_date.day} {MONTHS_RU[match_date.month - 1]}"

        return f"{date_part} {time_part} UTC", is_live
    except Exception:
        return "", False


MIN_CHIMERA_SCORE_T3 = 30  # CS2 Тир 3 — тот же порог что и остальные


def format_chimera_signals(candidates: List[Dict], show_top: int = 3) -> str:
    """Форматирует CHIMERA сигналы для Telegram (HTML)."""
    # Для CS2 Тир 3 используем пониженный порог
    def _passes(c):
        threshold = MIN_CHIMERA_SCORE_T3 if c.get("cs2_tier3") else MIN_CHIMERA_SCORE
        return c["chimera_score"] >= threshold

    visible = [c for c in candidates if _passes(c)][:show_top]

    if not visible:
        return (
            "📊 <b>CHIMERA SIGNAL</b>\n\n"
            "Сегодня сигналов нет.\n"
            "Рынок не предлагает ценных ставок.\n\n"
            "<i>Попробуйте позже или сделайте полный анализ конкретного матча.</i>"
        )

    best = visible[0]
    label = score_label(best["chimera_score"])
    sport = best.get("sport", "football")
    if sport == "cs2":
        _cs2_tier_label = best.get("tier_label", "")
        sport_emoji = f"{_cs2_tier_label} CS2" if _cs2_tier_label else "🎮 CS2"
    elif sport == "tennis":
        surf = best.get("surface", "hard")
        surf_icons = {"hard": "🎾", "clay": "🟫", "grass": "🟩"}
        sport_emoji = f"{surf_icons.get(surf, '🎾')} ТЕННИС"
    elif sport == "basketball":
        sport_emoji = f"🏀 {best.get('league_name', 'БАСКЕТБОЛ')}"
    else:
        sport_emoji = "⚽ ФУТБОЛ"

    # Время матча и LIVE статус
    time_str, is_live = _format_match_time(best.get("commence_time", ""))
    if is_live:
        live_tag = "🟢 <b>LIVE</b>"
    elif time_str:
        live_tag = f"🕐 {time_str}"
    else:
        live_tag = ""

    # Строка команды/игрока
    if sport == "tennis":
        matchup_line = f"<b>{best['home']} vs {best['away']}</b>"
        bet_line = f"📌 Победа: <b>{best['team']}</b> (рейтинг #{best.get('rank', '?')})"
        if best.get("h2h_total", 0) >= 3:
            bet_line += f" | H2H: {best.get('h2h_wins', 0)}/{best['h2h_total']}"
    else:
        matchup_line = f"<b>{best['home']} vs {best['away']}</b>"
        bet_line = f"📌 Ставка: <b>{best['team']} ({best['outcome']})</b>"

    time_line = f"\n{live_tag}" if live_tag else ""

    lines = [
        f"🎯 <b>CHIMERA SIGNAL — ЛУЧШАЯ СТАВКА ДНЯ</b>",
        f"",
        f"<b>{label} [{best['chimera_score']:.0f}/100]</b>{time_line}",
        f"",
        f"{sport_emoji} | {matchup_line}",
        bet_line,
        f"💰 Кэф: <b>{best['odds']}</b> | Наша вероятность: <b>{best['prob']}%</b>",
        f"📈 EV: <b>{best['ev']:+.1f}%</b> | Ставь: <b>{best['kelly']:.1f}%</b> банка",
    ]

    # AI блок
    if best.get("ai_confirmed") is True:
        llama_agrees = best.get("llama_agrees")
        ai_header = "🐉 Химера единогласна (Змея + Лев + Козёл + Тень)" if llama_agrees else "🐍🦁🐐 Химера подтверждает"
        ai_reason  = html.escape(str(best.get("ai_reason", "") or ""))
        llama_logic = html.escape(str(best.get("llama_logic", "") or ""))
        llama_warn  = html.escape(str(best.get("llama_warning", "") or ""))
        lines += [
            f"",
            f"<b>{ai_header} ({best['ai_confidence']}% уверенности):</b>",
            f"<i>🐍🦁🐐 Химера: «{ai_reason}»</i>",
        ]
        if llama_logic:
            lines.append(f"<i>🌀 Тень: «{llama_logic}»</i>")
        if llama_warn:
            lines.append(f"⚠️ Риск: {llama_warn}")
    elif best.get("ai_confirmed") is False:
        lines.append(f"\n⚠️ AI сомневается в этой ставке")

    # Детали CHIMERA Score
    score_lines = [
        f"",
        f"📊 <b>Детали CHIMERA Score:</b>",
        f"├ ELO преимущество: {best['elo_pts']:+.0f} pts" +
            (f" (разрыв: {best['elo_gap']} очков)" if best['elo_gap'] else ""),
        f"├ Форма команды: {best['form_pts']:+.0f} pts" +
            (f" ({best['form']})" if best['form'] else ""),
        f"├ Ценность кэфа: {best['value_pts']:+.0f} pts" +
            f" ({best['prob']}% vs бук {best['implied_prob']}%)",
        f"├ Сила прогноза: {best['prob_pts']:+.0f} pts",
    ]
    if best.get("xg_pts", 0):
        score_lines.append(f"├ xG качество: {best['xg_pts']:+.0f} pts")
    if best.get("line_pts", 0):
        icon = "📉" if best["line_pts"] > 0 else "⚠️"
        score_lines.append(f"├ {icon} Движение линии: {best['line_pts']:+.0f} pts")
    if best.get("h2h_pts", 0):
        score_lines.append(f"├ ⚔️ H2H история: {best['h2h_pts']:+.0f} pts")
    # Исторический сдвиг Pinnacle
    hist_mov = best.get("hist_movement")
    if hist_mov and hist_mov.get("score_boost"):
        boost = hist_mov["score_boost"]
        label_mov = hist_mov.get("label", "")
        h_ago = hist_mov.get("data_age_hours", 24)
        score_lines.append(
            f"├ {label_mov} ({boost:+.0f} pts, {h_ago}ч назад)"
        )
    score_lines[-1] = score_lines[-1].replace("├", "└")
    lines += score_lines

    # Блок тоталов для лучшего матча
    totals_block = _format_totals_block(best)
    if totals_block:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━━", totals_block]

    lines += [""]
    result = "\n".join(lines)
    if len(result) > 4000:
        result = result[:3990] + "\n…"
    return result


def _format_totals_block(candidate: dict) -> str:
    """
    Формирует блок тоталов для сигнала дня.
    Возвращает пустую строку если тоталы не доступны.
    """
    sport = candidate.get("sport", "football")
    totals = candidate.get("totals_data")

    if sport == "cs2" and totals:
        pred = totals.get("prediction", "")
        conf = totals.get("confidence", 0)
        reason = totals.get("reason", "")
        if pred and conf >= 55:
            return (
                f"📊 <b>Тотал карт:</b> {pred} "
                f"(<b>{conf}%</b>)\n"
                f"<i>{reason}</i>"
            )

    elif sport == "football" and totals:
        over25 = totals.get("over_25", 0)
        under25 = totals.get("under_25", 0)
        if over25 and under25:
            if over25 > 0.58:
                pred = f"OVER 2.5 голов ({int(over25*100)}%)"
            elif under25 > 0.58:
                pred = f"UNDER 2.5 голов ({int(under25*100)}%)"
            else:
                pred = f"OVER 2.5: {int(over25*100)}% | UNDER 2.5: {int(under25*100)}%"
            return f"📊 <b>Тотал голов:</b> {pred}"

    elif sport == "basketball" and totals:
        lean = totals.get("lean", "")
        line = totals.get("total_line", 0)
        conf = totals.get("confidence", 0)
        if lean and line and conf >= 55:
            return (
                f"📊 <b>Тотал очков:</b> {lean} {line} "
                f"(<b>{conf}%</b>)"
            )

    elif sport == "tennis" and totals:
        pred = totals.get("prediction", "")
        conf = totals.get("confidence", 0)
        reason = totals.get("reason", "")
        if pred and conf >= 55:
            return (
                f"📊 <b>Тотал геймов:</b> {pred} "
                f"(<b>{conf}%</b>)\n"
                f"<i>{reason}</i>"
            )

    return ""
