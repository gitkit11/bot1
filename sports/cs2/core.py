# -*- coding: utf-8 -*-
from .veto_logic import simulate_bo3_veto, get_map_impact_score
from .pandascore import get_team_stats, get_head_to_head
from .hltv_odds import get_hltv_odds
import json
import asyncio

# ELO-подобные рейтинги топ-команд CS2 (обновляются вручную)
# Для неизвестных команд используется 1000 (средний)
CS2_ELO = {
    "Team Vitality": 1820,
    "Natus Vincere": 1780,
    "FaZe Clan": 1760,
    "G2 Esports": 1750,
    "Team Spirit": 1740,
    "MOUZ": 1720,
    "Heroic": 1700,
    "Astralis": 1680,
    "ENCE": 1660,
    "Cloud9": 1640,
    "Liquid": 1630,
    "FURIA": 1620,
    "BIG": 1600,
    "OG": 1580,
    "Complexity": 1560,
}
DEFAULT_ELO = 1000

def get_elo_prob(home_team, away_team):
    """Рассчитывает вероятность победы на основе ELO рейтингов."""
    h_elo = CS2_ELO.get(home_team, DEFAULT_ELO)
    a_elo = CS2_ELO.get(away_team, DEFAULT_ELO)
    # Формула ELO
    h_prob = 1 / (1 + 10 ** ((a_elo - h_elo) / 400))
    return round(h_prob, 3), round(1 - h_prob, 3)

def calculate_cs2_win_prob(home_team, away_team):
    """
    Расчёт вероятности победы — 3 источника данных:
    1. MIS (Map Impact Score) из вето-симуляции — 40%
    2. ELO рейтинг команд — 35%
    3. Реальный винрейт из PandaScore (последние 20 матчей) — 25%
    """
    # 1. Симулируем мап-вето
    maps, veto_log = simulate_bo3_veto(home_team, away_team)

    # 2. Считаем MIS для каждой карты
    map_scores = []
    for m in maps:
        h_mis = get_map_impact_score(home_team, m)
        a_mis = get_map_impact_score(away_team, m)
        total = h_mis + a_mis
        if total == 0:
            h_prob, a_prob = 0.5, 0.5
        else:
            h_prob = h_mis / total
            a_prob = a_mis / total
        map_scores.append((m, h_prob, a_prob))

    # Взвешенный MIS (пики важнее десайдера)
    weights = [0.35, 0.35, 0.30]
    mis_h = sum(map_scores[i][1] * weights[i] for i in range(3))

    # 3. ELO вероятность
    elo_h, elo_a = get_elo_prob(home_team, away_team)

    # 4. Реальный винрейт из PandaScore
    print(f"[CS2-Core] Загружаю статистику {home_team}...")
    h_stats = get_team_stats(home_team)
    print(f"[CS2-Core] Загружаю статистику {away_team}...")
    a_stats = get_team_stats(away_team)

    h_winrate = h_stats["winrate"]
    a_winrate = a_stats["winrate"]

    # Нормализуем винрейты чтобы сумма = 1
    total_wr = h_winrate + a_winrate
    if total_wr > 0:
        h_wr_norm = h_winrate / total_wr
    else:
        h_wr_norm = 0.5

    # 5. Личные встречи (бонус/штраф)
    h2h = get_head_to_head(home_team, away_team)
    h2h_bonus = 0.0
    if h2h["total"] >= 3:
        h2h_h = h2h["team1_wins"] / h2h["total"]
        h2h_bonus = (h2h_h - 0.5) * 0.1  # Максимум ±5%

    # 6. Финальный ансамбль
    final_h = (mis_h * 0.40) + (elo_h * 0.35) + (h_wr_norm * 0.25) + h2h_bonus
    final_h = max(0.05, min(0.95, final_h))  # Ограничиваем 5%-95%
    final_a = 1 - final_h

    return {
        "home_prob": round(final_h, 2),
        "away_prob": round(final_a, 2),
        "maps": map_scores,
        "veto_log": veto_log,
        "home_stats": h_stats,
        "away_stats": a_stats,
        "elo_home": CS2_ELO.get(home_team, DEFAULT_ELO),
        "elo_away": CS2_ELO.get(away_team, DEFAULT_ELO),
        "h2h": h2h,
        # Детали расчёта
        "detail": {
            "mis": round(mis_h, 2),
            "elo": round(elo_h, 2),
            "winrate": round(h_wr_norm, 2),
            "h2h_bonus": round(h2h_bonus, 3)
        }
    }

def get_golden_signal(analysis_data, bookmaker_odds):
    """
    Алгоритм "Золотого сигнала" с высокой проходимостью.
    Условия:
    1. Наша вероятность > 60%
    2. Коэффициент букмекера > 1.60
    3. EV (Expected Value) > 15%
    """
    h_prob = analysis_data["home_prob"]
    a_prob = analysis_data["away_prob"]

    h_odds = bookmaker_odds.get("home_win", 0)
    a_odds = bookmaker_odds.get("away_win", 0)

    signals = []

    if h_odds > 1.0:
        h_ev = (h_prob * h_odds) - 1
        if h_prob >= 0.60 and h_odds >= 1.60 and h_ev >= 0.15:
            signals.append({
                "type": "GOLDEN",
                "team": analysis_data.get("home_team", ""),
                "outcome": "Победа (П1)",
                "odds": h_odds,
                "ev": round(h_ev * 100, 1),
                "confidence": int(h_prob * 100)
            })

    if a_odds > 1.0:
        a_ev = (a_prob * a_odds) - 1
        if a_prob >= 0.60 and a_odds >= 1.60 and a_ev >= 0.15:
            signals.append({
                "type": "GOLDEN",
                "team": analysis_data.get("away_team", ""),
                "outcome": "Победа (П2)",
                "odds": a_odds,
                "ev": round(a_ev * 100, 1),
                "confidence": int(a_prob * 100)
            })

    return signals

def format_cs2_full_report(home_team, away_team, analysis, gpt_analysis, llama_analysis, golden_signals, bookmaker_odds=None):
    """Форматирует профессиональный отчет для CS2 v4.5."""
    h_stats = analysis.get("home_stats", {})
    a_stats = analysis.get("away_stats", {})
    h2h = analysis.get("h2h", {})
    detail = analysis.get("detail", {})

    report = f"🎮 *CHIMERA AI CS2 v4.5 — АНАЛИЗ МАТЧА*\n"
    report += f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    report += f"⚔️ *{home_team} vs {away_team}*\n\n"

    # Коэффициенты букмекеров
    if bookmaker_odds:
        h_odds = bookmaker_odds.get("home_win", 0)
        a_odds = bookmaker_odds.get("away_win", 0)
        
        # Если коэффициенты в API нулевые, пробуем получить их с HLTV
        if h_odds == 0 or a_odds == 0:
            try:
                hltv_odds = get_hltv_odds(home_team, away_team)
                if hltv_odds:
                    h_odds = hltv_odds.get("home_win", 0)
                    a_odds = hltv_odds.get("away_win", 0)
            except Exception as e:
                print(f"[HLTV] Ошибка при получении коэффициентов: {e}")

        report += f"💰 *КОЭФФИЦИЕНТЫ БУКМЕКЕРОВ:*\n"
        if h_odds > 0 and a_odds > 0:
            report += f" 🔹 {home_team}: *{h_odds:.2f}* | 🔸 {away_team}: *{a_odds:.2f}*\n\n"
        else:
            report += f" ⚠️ Коэффициенты временно недоступны\n\n"

    # Статистика команд
    report += f"📊 *СТАТИСТИКА КОМАНД (PandaScore):*\n"
    if h_stats.get("matches", 0) > 0:
        report += f" 🔹 {home_team}: {h_stats['wins']}В/{h_stats['losses']}П | WR: {int(h_stats['winrate']*100)}% | Форма: {h_stats['form']}\n"
    else:
        report += f" 🔹 {home_team}: нет данных\n"
    if a_stats.get("matches", 0) > 0:
        report += f" 🔸 {away_team}: {a_stats['wins']}В/{a_stats['losses']}П | WR: {int(a_stats['winrate']*100)}% | Форма: {a_stats['form']}\n"
    else:
        report += f" 🔸 {away_team}: нет данных\n"

    # Личные встречи
    if h2h.get("total", 0) >= 2:
        report += f" 🤝 Личные встречи: {home_team} {h2h['team1_wins']}:{h2h['team2_wins']} {away_team}\n"
    report += "\n"

    # ELO
    report += f"⚡ *ELO РЕЙТИНГ CS2:*\n"
    report += f" {home_team}: {analysis.get('elo_home', '?')} | {away_team}: {analysis.get('elo_away', '?')}\n\n"

    # Вето симуляция
    report += f"🗺 *СИМУЛЯЦИЯ VETO (BO3):*\n"
    for log in analysis["veto_log"]:
        report += f" {log}\n"
    report += "\n"

    # Вероятности по картам
    report += f"📈 *ВЕРОЯТНОСТЬ ПО КАРТАМ (MIS):*\n"
    for m, hp, ap in analysis["maps"]:
        bar_h = "█" * int(hp * 10)
        bar_a = "█" * int(ap * 10)
        report += f" • {m}: {int(hp*100)}% {bar_h}|{bar_a} {int(ap*100)}%\n"
    report += "\n"

    # Итоговый расчёт
    report += f"🔢 *ИТОГОВЫЙ РАСЧЁТ (ансамбль):*\n"
    report += f" 🔹 {home_team}: *{int(analysis['home_prob']*100)}%*\n"
    report += f" 🔸 {away_team}: *{int(analysis['away_prob']*100)}%*\n"
    report += f" Веса: MIS 40% + ELO 35% + WR 25%\n\n"

    # AI анализ
    if gpt_analysis and gpt_analysis != "—":
        report += f"🧠 *GPT-4 (Стратег):*\n_{gpt_analysis}_\n\n"
    if llama_analysis and llama_analysis != "—":
        report += f"🤖 *Llama (Тактик):*\n_{llama_analysis}_\n\n"

    # Сигнал
    if golden_signals:
        report += f"🌟 *ЗОЛОТОЙ СИГНАЛ:*\n"
        for sig in golden_signals:
            report += f"🔥 {sig['outcome']} {sig['team']} @ {sig['odds']}\n"
            report += f"   Уверенность: {sig['confidence']}% | EV: +{sig['ev']}%\n"
    else:
        report += f"⏸ *СИГНАЛ: ПРОПУСТИТЬ*\n"
        report += f"_Нет достаточной уверенности (нужно >60% и EV >15%)_\n"

    return report
