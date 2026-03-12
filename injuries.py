"""
injuries.py — Модуль получения данных о травмах и дисквалификациях.

Использует GNews для поиска актуальных новостей о травмах,
затем GPT-4o-mini для структурированного извлечения имён игроков.

Кэширует результаты на 6 часов чтобы не спамить API.
"""

import json
import os
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Кэш: {team_name: (data, timestamp)}
_injury_cache: dict = {}
CACHE_TTL = 6 * 3600  # 6 часов


def _cache_get(team: str):
    if team in _injury_cache:
        data, ts = _injury_cache[team]
        if (time.time() - ts) < CACHE_TTL:
            return data
    return None


def _cache_set(team: str, data):
    _injury_cache[team] = (data, time.time())


def fetch_injury_news(team_name: str, max_results: int = 8) -> list:
    """Ищет свежие новости о травмах и дисквалификациях команды через GNews."""
    try:
        from gnews import GNews
        gn = GNews(language='en', country='US', max_results=max_results)
        # Ищем конкретно по травмам
        articles = gn.get_news(f"{team_name} injury suspension doubt miss")
        return articles if articles else []
    except Exception as e:
        logger.warning(f"[Травмы] GNews ошибка для {team_name}: {e}")
        return []


def extract_injuries_with_ai(team_name: str, news_articles: list) -> dict:
    """
    Использует GPT-4o-mini для извлечения структурированных данных о травмах
    из новостных заголовков.
    Возвращает: {'injured': [...], 'suspended': [...], 'doubts': [...], 'returning': [...]}
    """
    if not news_articles:
        return {"injured": [], "suspended": [], "doubts": [], "returning": []}

    try:
        from openai import OpenAI
        client = OpenAI()

        # Собираем заголовки и описания
        headlines = []
        for art in news_articles[:8]:
            title = art.get("title", "")
            desc = art.get("description", "") or ""
            if title:
                headlines.append(f"- {title}. {desc[:100]}")

        news_text = "\n".join(headlines)

        prompt = f"""Analyze these news headlines about {team_name} football club and extract injury/suspension information.

Headlines:
{news_text}

Return a JSON object with these keys:
- "injured": list of player names confirmed injured (e.g. ["Diogo Jota", "Curtis Jones"])
- "suspended": list of player names suspended/banned
- "doubts": list of player names doubtful/uncertain
- "returning": list of player names returning from injury

Rules:
- Only include players clearly mentioned in the headlines
- Use full player names
- If no players found for a category, use empty list []
- Return ONLY valid JSON, no explanation

Example: {{"injured": ["Player A"], "suspended": [], "doubts": ["Player B"], "returning": []}}"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )

        raw = response.choices[0].message.content.strip()
        # Извлекаем JSON из ответа
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()

        data = json.loads(raw)
        return {
            "injured": data.get("injured", []),
            "suspended": data.get("suspended", []),
            "doubts": data.get("doubts", []),
            "returning": data.get("returning", []),
        }

    except Exception as e:
        logger.warning(f"[Травмы] AI-извлечение ошибка для {team_name}: {e}")
        return {"injured": [], "suspended": [], "doubts": [], "returning": []}


def get_team_injuries(team_name: str) -> dict:
    """
    Главная функция — получает данные о травмах/дисквалификациях команды.
    Использует кэш 6 часов.

    Возвращает:
    {
        'team': str,
        'injured': [...],
        'suspended': [...],
        'doubts': [...],
        'returning': [...],
        'total_missing': int,
        'impact': str,  # 'high' / 'medium' / 'low' / 'none'
        'news_count': int,
    }
    """
    cached = _cache_get(team_name)
    if cached:
        logger.info(f"[Травмы] Кэш для {team_name}")
        return cached

    logger.info(f"[Травмы] Запрашиваю данные для {team_name}...")
    print(f"[Травмы] Ищу новости о травмах: {team_name}...")

    articles = fetch_injury_news(team_name)
    print(f"[Травмы] Найдено статей: {len(articles)}")

    if not articles:
        result = {
            "team": team_name,
            "injured": [],
            "suspended": [],
            "doubts": [],
            "returning": [],
            "total_missing": 0,
            "impact": "none",
            "news_count": 0,
        }
        _cache_set(team_name, result)
        return result

    extracted = extract_injuries_with_ai(team_name, articles)

    injured = extracted.get("injured", [])
    suspended = extracted.get("suspended", [])
    doubts = extracted.get("doubts", [])
    returning = extracted.get("returning", [])

    total_missing = len(injured) + len(suspended)

    # Оцениваем влияние на матч
    if total_missing >= 4:
        impact = "high"
    elif total_missing >= 2:
        impact = "medium"
    elif total_missing >= 1 or len(doubts) >= 2:
        impact = "low"
    else:
        impact = "none"

    result = {
        "team": team_name,
        "injured": injured,
        "suspended": suspended,
        "doubts": doubts,
        "returning": returning,
        "total_missing": total_missing,
        "impact": impact,
        "news_count": len(articles),
    }

    _cache_set(team_name, result)
    print(f"[Травмы] {team_name}: травмы={injured}, дискв={suspended}, сомн={doubts}")
    return result


def format_injuries_block(home_team: str, away_team: str,
                           home_injuries: dict, away_injuries: dict) -> str:
    """
    Форматирует блок травм/дисквалификаций для отчёта Telegram.
    """
    def _format_team(team_name: str, data: dict) -> str:
        if not data:
            return f" {team_name}: данные недоступны"

        lines = []
        if data.get("injured"):
            lines.append(f"  🤕 Травмы: {', '.join(data['injured'])}")
        if data.get("suspended"):
            lines.append(f"  🟥 Дискв: {', '.join(data['suspended'])}")
        if data.get("doubts"):
            lines.append(f"  ❓ Под вопросом: {', '.join(data['doubts'])}")
        if data.get("returning"):
            lines.append(f"  ✅ Возвращаются: {', '.join(data['returning'])}")

        if not lines:
            return f" {team_name}: все игроки доступны ✅"

        impact = data.get("impact", "none")
        impact_icons = {"high": "🔴", "medium": "🟡", "low": "🟢", "none": "✅"}
        icon = impact_icons.get(impact, "")
        missing = data.get("total_missing", 0)
        header = f" {team_name} {icon} ({missing} точно не играет):" if missing > 0 else f" {team_name}:"
        return header + "\n" + "\n".join(lines)

    home_block = _format_team(home_team, home_injuries)
    away_block = _format_team(away_team, away_injuries)

    return f"🏥 *ТРАВМЫ И ДИСКВАЛИФИКАЦИИ:*\n{home_block}\n{away_block}"


def get_match_injuries(home_team: str, away_team: str) -> tuple:
    """
    Получает данные о травмах для обоих команд последовательно.
    Для параллельного запуска используй get_match_injuries_async().
    Возвращает (home_injuries, away_injuries, formatted_block).
    """
    home_injuries = get_team_injuries(home_team)
    away_injuries = get_team_injuries(away_team)
    block = format_injuries_block(home_team, away_team, home_injuries, away_injuries)
    return home_injuries, away_injuries, block


async def get_match_injuries_async(home_team: str, away_team: str) -> tuple:
    """
    Асинхронная версия: запрашивает травмы для обоих команд параллельно.
    Сокращает время с ~20 сек до ~10 сек.
    """
    import asyncio
    home_injuries, away_injuries = await asyncio.gather(
        asyncio.to_thread(get_team_injuries, home_team),
        asyncio.to_thread(get_team_injuries, away_team)
    )
    block = format_injuries_block(home_team, away_team, home_injuries, away_injuries)
    return home_injuries, away_injuries, block
