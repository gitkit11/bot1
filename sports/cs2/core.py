# -*- coding: utf-8 -*-
from .veto_logic import simulate_bo3_veto, get_map_impact_score, get_team_player_stats
from .pandascore import get_team_stats, get_head_to_head
from .hltv_odds import get_hltv_odds, get_team_map_stats
import json
import asyncio

# ELO-подобные рейтинги топ-команд CS2 (обновляются вручную)
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
    h_elo = CS2_ELO.get(home_team, DEFAULT_ELO)
    a_elo = CS2_ELO.get(away_team, DEFAULT_ELO)
    h_prob = 1 / (1 + 10 ** ((a_elo - h_elo) / 400))
    return round(h_prob, 3), round(1 - h_prob, 3)

def calculate_cs2_win_prob(home_team, away_team):
    """
    Расчёт вероятности победы — 4 источника данных:
    1. MIS (Map Impact Score) из вето-симуляции — 30%
    2. ELO рейтинг команд — 30%
    3. Реальный винрейт из PandaScore (последние 20 матчей) — 20%
    4. Рейтинг игроков с HLTV — 20%
    """
    # 1. Получаем статистику карт и игроков
    home_map_stats = get_team_map_stats(home_team)
    away_map_stats = get_team_map_stats(away_team)
    team_map_stats_combined = {home_team: home_map_stats, away_team: away_map_stats}

    home_players = get_team_player_stats(home_team)
    away_players = get_team_player_stats(away_team)

    # 2. Симулируем мап-вето
    maps, veto_log = simulate_bo3_veto(home_team, away_team, team_map_stats_combined)

    # 3. Считаем MIS для каждой карты
    map_scores = []
    for m in maps:
        h_mis = get_map_impact_score(home_team, m, team_map_stats_combined)
        a_mis = get_map_impact_score(away_team, m, team_map_stats_combined)
        total = h_mis + a_mis
        h_prob, a_prob = (h_mis / total, a_mis / total) if total > 0 else (0.5, 0.5)
        map_scores.append((m, h_prob, a_prob))

    weights = [0.35, 0.35, 0.30]
    mis_h = sum(map_scores[i][1] * weights[i] for i in range(3))

    # 4. ELO вероятность
    elo_h, elo_a = get_elo_prob(home_team, away_team)

    # 5. Реальный винрейт из PandaScore
    h_stats = get_team_stats(home_team)
    a_stats = get_team_stats(away_team)
    total_wr = h_stats["winrate"] + a_stats["winrate"]
    h_wr_norm = h_stats["winrate"] / total_wr if total_wr > 0 else 0.5

    # 6. Рейтинг игроков (HLTV)
    h_rating = sum(p['rating'] for p in home_players) / len(home_players) if home_players else 1.0
    a_rating = sum(p['rating'] for p in away_players) / len(away_players) if away_players else 1.0
    total_rating = h_rating + a_rating
    h_rating_norm = h_rating / total_rating if total_rating > 0 else 0.5

    # 7. Личные встречи
    h2h = get_head_to_head(home_team, away_team)
    h2h_bonus = (h2h["team1_wins"] / h2h["total"] - 0.5) * 0.1 if h2h["total"] >= 3 else 0.0

    # 8. Финальный ансамбль
    final_h = (mis_h * 0.30) + (elo_h * 0.30) + (h_wr_norm * 0.20) + (h_rating_norm * 0.20) + h2h_bonus
    final_h = max(0.05, min(0.95, final_h))
    
    return {
        "home_prob": round(final_h, 2),
        "away_prob": round(1 - final_h, 2),
        "maps": map_scores,
        "veto_log": veto_log,
        "home_stats": h_stats,
        "away_stats": a_stats,
        "home_players": home_players,
        "away_players": away_players,
        "elo_home": CS2_ELO.get(home_team, DEFAULT_ELO),
        "elo_away": CS2_ELO.get(away_team, DEFAULT_ELO),
        "h2h": h2h,
        "detail": {
            "mis": round(mis_h, 2),
            "elo": round(elo_h, 2),
            "winrate": round(h_wr_norm, 2),
            "player_rating": round(h_rating_norm, 2),
            "h2h_bonus": round(h2h_bonus, 3)
        }
    }

def get_golden_signal(analysis_data, bookmaker_odds):
    h_prob = analysis_data["home_prob"]
    a_prob = analysis_data["away_prob"]
    h_odds = bookmaker_odds.get("home_win", 0)
    a_odds = bookmaker_odds.get("away_win", 0)
    signals = []
    if h_odds > 1.0:
        h_ev = (h_prob * h_odds) - 1
        if h_prob >= 0.60 and h_odds >= 1.60 and h_ev >= 0.15:
            signals.append({"type": "GOLDEN", "team": analysis_data.get("home_team", ""), "outcome": "Победа (П1)", "odds": h_odds, "ev": round(h_ev * 100, 1), "confidence": int(h_prob * 100)})
    if a_odds > 1.0:
        a_ev = (a_prob * a_odds) - 1
        if a_prob >= 0.60 and a_odds >= 1.60 and a_ev >= 0.15:
            signals.append({"type": "GOLDEN", "team": analysis_data.get("away_team", ""), "outcome": "Победа (П2)", "odds": a_odds, "ev": round(a_ev * 100, 1), "confidence": int(a_prob * 100)})
    return signals

def format_cs2_full_report(home_team, away_team, analysis, gpt_analysis, llama_analysis, golden_signals, bookmaker_odds=None):
    h_stats = analysis.get("home_stats", {})
    a_stats = analysis.get("away_stats", {})
    h_players = analysis.get("home_players", [])
    a_players = analysis.get("away_players", [])
    h2h = analysis.get("h2h", {})
    
    report = f"🎮 *CHIMERA AI CS2 v4.6 — АНАЛИЗ МАТЧА*\n"
    report += f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    report += f"⚔️ *{home_team} vs {away_team}*\n\n"

    if bookmaker_odds:
        h_odds = bookmaker_odds.get("home_win", 0)
        a_odds = bookmaker_odds.get("away_win", 0)
        if h_odds > 0 and a_odds > 0:
            report += f"💰 *КЭФЫ:* {home_team}: *{h_odds:.2f}* | {away_team}: *{a_odds:.2f}*\n\n"

    report += f"👥 *СОСТАВЫ (HLTV Rating):*\n"
    h_p_str = ", ".join([f"{p['name']} ({p['rating']})" for p in h_players[:3]])
    a_p_str = ", ".join([f"{p['name']} ({p['rating']})" for p in a_players[:3]])
    report += f" 🔹 {home_team}: {h_p_str}...\n"
    report += f" 🔸 {away_team}: {a_p_str}...\n\n"

    report += f"🗺 *СИМУЛЯЦИЯ VETO (BO3):*\n"
    for log in analysis["veto_log"]: report += f" {log}\n"
    report += "\n"

    report += f"📈 *ВЕРОЯТНОСТЬ ПО КАРТАМ (MIS):*\n"
    for m, hp, ap in analysis["maps"]:
        report += f" • {m}: {int(hp*100)}% — {int(ap*100)}%\n"
    report += "\n"

    report += f"🔢 *ИТОГОВЫЙ РАСЧЁТ:* {home_team} *{int(analysis['home_prob']*100)}%* — *{int(analysis['away_prob']*100)}%* {away_team}\n"
    report += f"_Веса: MIS 30%, ELO 30%, WR 20%, Players 20%_\n\n"

    if gpt_analysis and gpt_analysis != "—": report += f"🧠 *GPT-4:* _{gpt_analysis}_\n\n"
    if golden_signals:
        for sig in golden_signals:
            report += f"🌟 *ЗОЛОТОЙ СИГНАЛ:* 🔥 {sig['outcome']} {sig['team']} @ {sig['odds']} (EV: +{sig['ev']}%)\n"
    else:
        report += f"⏸ *СИГНАЛ: ПРОПУСТИТЬ*\n"

    return report
