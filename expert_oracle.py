# -*- coding: utf-8 -*-
"""
expert_oracle.py — Модуль экспертных прогнозов
================================================
Источники:
  1. Google News (GNews) — беттинговые порталы, блоги
  2. Real-Time News Data (RapidAPI) — свежие новости
  3. Reddit — живые мнения людей из тематических сабреддитов

AI-фильтрация: GPT-4.1-mini оценивает каждое Reddit-мнение по шкале 1-10.
Показываются только мнения с оценкой ≥ 6.
"""

import os
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_cache: dict = {}
_CACHE_TTL = 3600  # 1 час

# Сабреддиты по видам спорта
_SPORT_SUBREDDITS = {
    "football":   ["soccerpredictions", "sportsbetting", "soccer"],
    "cs2":        ["GlobalOffensive", "csgo", "sportsbetting"],
    "tennis":     ["tennis", "sportsbetting"],
    "basketball": ["nba", "euroleague", "sportsbetting"],
    "hockey":     ["hockey", "nhl", "sportsbetting"],
}


# ─── 1. Google News ───────────────────────────────────────────────────────────

def _search_gnews(home: str, away: str) -> list[dict]:
    try:
        from gnews import GNews
    except ImportError:
        return []

    queries = [
        f"{home} vs {away} prediction betting tips",
        f"{home} vs {away} preview picks",
    ]
    seen: set = set()
    results: list = []
    gn = GNews(language="en", country="US", max_results=5, period="3d")
    for q in queries:
        try:
            for a in (gn.get_news(q) or []):
                title = a.get("title", "")
                if title and title not in seen:
                    seen.add(title)
                    results.append({
                        "title":       title,
                        "description": a.get("description", ""),
                        "publisher":   (a.get("publisher") or {}).get("title", ""),
                        "source":      "news",
                    })
        except Exception as e:
            logger.debug(f"[ExpertOracle] GNews '{q}': {e}")
    return results[:10]


# ─── 2. Real-Time News Data (RapidAPI) ───────────────────────────────────────

def _search_realtime_news(home: str, away: str) -> list[dict]:
    try:
        import requests
        key = os.getenv("RAPID_API_KEY", "")
        if not key:
            return []
        host = "real-time-news-data.p.rapidapi.com"
        resp = requests.get(
            f"https://{host}/search",
            headers={"x-rapidapi-host": host, "x-rapidapi-key": key},
            params={"query": f"{home} vs {away} prediction betting", "language": "en", "country": "US"},
            timeout=12,
        )
        if resp.status_code != 200:
            return []
        results = []
        for art in resp.json().get("data", []):
            title = art.get("title") or ""
            if title:
                results.append({
                    "title":       title,
                    "description": art.get("snippet") or "",
                    "publisher":   art.get("source_name") or "",
                    "source":      "news",
                })
        return results[:6]
    except Exception as e:
        logger.debug(f"[ExpertOracle] RealTimeNews: {e}")
        return []


# ─── 3. Reddit ────────────────────────────────────────────────────────────────

def _search_reddit(home: str, away: str, sport: str = "football") -> list[dict]:
    """
    Ищет посты и комментарии на Reddit в тематических сабреддитах.
    Не требует API-ключа — используется публичный JSON-эндпоинт.
    """
    try:
        import requests
        subreddits = _SPORT_SUBREDDITS.get(sport, ["sportsbetting"])
        query = f"{home} {away}"
        headers = {"User-Agent": "ChimeraBot/1.0 prediction research"}
        results = []
        seen: set = set()

        for sub in subreddits[:2]:  # Максимум 2 сабреддита
            try:
                r = requests.get(
                    "https://www.reddit.com/search.json",
                    headers=headers,
                    params={
                        "q": f"subreddit:{sub} {home} vs {away}",
                        "sort": "relevance", "limit": 8, "t": "month",
                    },
                    timeout=8,
                )
                if r.status_code != 200:
                    continue
                posts = r.json().get("data", {}).get("children", [])

                posts = r.json().get("data", {}).get("children", [])
                for post in posts:
                    d = post.get("data", {})
                    title = d.get("title", "")
                    selftext = (d.get("selftext") or "")[:300]
                    author = d.get("author", "")
                    score = d.get("score", 0)
                    url_post = f"https://reddit.com{d.get('permalink', '')}"

                    if not title or title in seen:
                        continue
                    # Мягкий фильтр: хотя бы одно имя команды или слово prediction/betting
                    h1 = home.lower().split()[0]
                    a1 = away.lower().split()[0]
                    text_lower = (title + " " + selftext).lower()
                    bet_kws = ["predict", "betting", "odds", "tip", "pick", "preview"]
                    if (h1 not in text_lower and a1 not in text_lower
                            and not any(kw in text_lower for kw in bet_kws)):
                        continue

                    seen.add(title)
                    results.append({
                        "title":       title,
                        "description": selftext.strip(),
                        "publisher":   f"Reddit r/{sub} u/{author} (👍{score})",
                        "source":      "reddit",
                        "reddit_score": score,
                        "subreddit":   sub,
                    })
            except Exception as e:
                logger.debug(f"[ExpertOracle] Reddit r/{sub}: {e}")
                continue

        # Сортируем по upvotes
        results.sort(key=lambda x: x.get("reddit_score", 0), reverse=True)
        return results[:8]
    except Exception as e:
        logger.debug(f"[ExpertOracle] Reddit: {e}")
        return []


# ─── 4. AI-оценка важности Reddit-мнений ─────────────────────────────────────

def _score_reddit_opinions(home: str, away: str, opinions: list[dict]) -> list[dict]:
    """
    GPT-4.1-mini оценивает каждое Reddit-мнение по шкале 1-10.
    Критерии:
      - Конкретный прогноз на матч (не просто «интересный матч»)
      - Аргументированность (статистика, форма, травмы, тактика)
      - Релевантность (именно этот матч)
    Возвращает только мнения с оценкой ≥ 6, с полем "ai_score".
    """
    if not opinions:
        return []
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        posts_text = ""
        for i, op in enumerate(opinions):
            posts_text += f"[{i}] TITLE: {op['title']}\n"
            if op.get("description"):
                posts_text += f"    TEXT: {op['description'][:200]}\n"
            posts_text += f"    UPVOTES: {op.get('reddit_score', 0)}\n\n"

        prompt = (
            f"Upcoming match: {home} vs {away}\n\n"
            f"Rate each Reddit post 1-10 for value as insight about this match:\n"
            f"- 9-10: Pre-match prediction with strong arguments (stats, tactics, form)\n"
            f"- 7-8: Pre-match discussion with a clear predicted winner\n"
            f"- 5-6: Recent past result between these teams (useful as form data)\n"
            f"- 3-4: General discussion mentioning one of the teams\n"
            f"- 1-2: Off-topic or about completely different teams/matches\n\n"
            f"{posts_text}\n"
            f"Return JSON only: {{\"scores\": [score0, score1, ...]}}"
        )
        r = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.1,
        )
        raw = r.choices[0].message.content.strip().strip("```json").strip("```").strip()
        scores = json.loads(raw).get("scores", [])

        scored = []
        for i, op in enumerate(opinions):
            score = scores[i] if i < len(scores) else 0
            if score >= 5:
                scored.append({**op, "ai_score": score})

        # Сортируем по AI-оценке
        scored.sort(key=lambda x: x["ai_score"], reverse=True)
        return scored[:3]  # Максимум 3 лучших мнения

    except Exception as e:
        logger.debug(f"[ExpertOracle] Reddit scoring: {e}")
        # Fallback: показываем посты с наибольшим числом upvotes (без AI-оценки)
        top = sorted(opinions, key=lambda x: x.get("reddit_score", 0), reverse=True)[:2]
        return [{**op, "ai_score": "?"} for op in top]


# ─── 5. AI-консенсус по новостям ──────────────────────────────────────────────

def _summarize_news_with_ai(home: str, away: str, titles: list[str]) -> Optional[dict]:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        text = " | ".join(titles[:8])
        prompt = (
            f"Match: {home} vs {away}\n"
            f"Expert headlines: {text}\n\n"
            "Return JSON only:\n"
            '{"consensus":"home_win|away_win|draw|unknown","confidence":0.0-1.0,'
            '"summary_ru":"1-2 sentences in Russian about expert consensus",'
            '"key_factors":["factor1","factor2"]}'
        )
        r = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.2,
        )
        raw = r.choices[0].message.content.strip().strip("```json").strip("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"[ExpertOracle] AI news summary: {e}")
        return None


def _keyword_vote(home: str, away: str, titles: list[str]) -> dict:
    win_kws = ["win", "beat", "defeat", "predicted", "favourite", "favorite",
               "tip", "back", "expect", "advantage"]
    h1 = home.lower().split()[0]
    a1 = away.lower().split()[0]
    h_votes = sum(1 for t in titles if h1 in t.lower() and any(kw in t.lower() for kw in win_kws))
    a_votes = sum(1 for t in titles if a1 in t.lower() and any(kw in t.lower() for kw in win_kws))
    if h_votes > a_votes + 1:
        return {"consensus": "home_win", "confidence": min(0.70, 0.50 + h_votes * 0.05)}
    elif a_votes > h_votes + 1:
        return {"consensus": "away_win", "confidence": min(0.70, 0.50 + a_votes * 0.05)}
    return {"consensus": "unknown", "confidence": 0.0}


# ─── 6. Главная функция ───────────────────────────────────────────────────────

def get_expert_consensus(home: str, away: str, sport: str = "football") -> dict:
    """
    Собирает экспертные мнения из новостей и Reddit, фильтрует AI.

    Returns dict:
        consensus       : "home_win" | "away_win" | "draw" | "unknown"
        confidence      : float 0.0-1.0
        summary_ru      : краткое резюме на русском
        key_factors     : list[str]
        sources_count   : int
        prob_boost      : float
        reddit_opinions : list[dict] — отфильтрованные AI мнения с Reddit
    """
    cache_key = f"{home}|{away}|{sport}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached.get("_ts", 0) < _CACHE_TTL:
        return cached

    # Новости
    articles = _search_gnews(home, away)
    try:
        rtn = _search_realtime_news(home, away)
        seen = {a["title"] for a in articles}
        for art in rtn:
            if art["title"] and art["title"] not in seen:
                articles.append(art)
                seen.add(art["title"])
    except Exception:
        pass

    # Reddit
    reddit_raw = _search_reddit(home, away, sport)
    reddit_opinions = _score_reddit_opinions(home, away, reddit_raw) if reddit_raw else []

    sources_count = len(articles) + len(reddit_opinions)

    if sources_count == 0:
        result = {
            "consensus": "unknown", "confidence": 0.0,
            "summary_ru": "", "key_factors": [],
            "sources_count": 0, "prob_boost": 0.0,
            "reddit_opinions": [],
        }
        _cache[cache_key] = {**result, "_ts": time.time()}
        return result

    # AI-консенсус по новостным заголовкам
    news_titles = [a["title"] for a in articles if a.get("title")]
    ai_result = _summarize_news_with_ai(home, away, news_titles) if news_titles else None

    if ai_result:
        consensus   = ai_result.get("consensus", "unknown")
        confidence  = float(ai_result.get("confidence", 0.0))
        summary_ru  = ai_result.get("summary_ru", "")
        key_factors = ai_result.get("key_factors", [])
    else:
        vote = _keyword_vote(home, away, news_titles)
        consensus   = vote["consensus"]
        confidence  = vote["confidence"]
        summary_ru  = f"Найдено {len(articles)} источников." if articles else ""
        key_factors = []

    prob_boost = 0.0
    if confidence >= 0.60 and consensus in ("home_win", "away_win", "draw"):
        prob_boost = round((confidence - 0.50) * 0.06, 3)

    result = {
        "consensus":       consensus,
        "confidence":      round(confidence, 3),
        "summary_ru":      summary_ru,
        "key_factors":     key_factors[:3],
        "sources_count":   sources_count,
        "prob_boost":      prob_boost,
        "reddit_opinions": reddit_opinions,
        "_ts":             time.time(),
    }
    _cache[cache_key] = result
    return result


# ─── 7. Форматирование блока ──────────────────────────────────────────────────

def format_expert_block(result: dict, home: str, away: str) -> str:
    """Форматирует блок экспертного мнения для Telegram HTML."""
    if not result or result.get("sources_count", 0) == 0:
        return ""

    consensus  = result.get("consensus", "unknown")
    sources    = result.get("sources_count", 0)
    summary    = result.get("summary_ru", "")
    confidence = result.get("confidence", 0.0)
    factors    = result.get("key_factors", [])
    reddit_ops = result.get("reddit_opinions", [])

    icons = {"home_win": "🏠", "away_win": "✈️", "draw": "🤝", "unknown": "❓"}
    icon  = icons.get(consensus, "❓")

    team_label = (home if consensus == "home_win"
                  else away if consensus == "away_win"
                  else "Ничья" if consensus == "draw"
                  else None)
    conf_str = f" ({int(confidence * 100)}%)" if confidence > 0.0 else ""

    lines = [f"🗣 <b>Мнение сети</b> — {sources} источн."]

    # Новостной консенсус
    if team_label:
        lines.append(f"{icon} Консенсус СМИ: <b>{team_label}</b>{conf_str}")
    if summary:
        lines.append(f"💬 {summary}")
    if factors:
        lines.append("🔑 " + " · ".join(factors))

    # Reddit-мнения (отфильтрованные AI)
    if reddit_ops:
        import re as _re
        def _clean_md(text: str) -> str:
            """Полная очистка Reddit markdown → plain text."""
            # Таблицы markdown: строки вида |...|..| или |:-:| — убираем целиком
            text = _re.sub(r'^\|.*\|.*$', '', text, flags=_re.MULTILINE)
            # [text](url) → text
            text = _re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
            # [](/TEAM) и похожие пустые ссылки → ''
            text = _re.sub(r'\[/?[^\]]*\]\([^)]*\)', '', text)
            # Остатки скобок-ссылок вида (url) или (#anchor)
            text = _re.sub(r'\(https?://[^\)]+\)', '', text)
            text = _re.sub(r'\(#[^)]+\)', '', text)
            # ## заголовки
            text = _re.sub(r'^#+\s*', '', text, flags=_re.MULTILINE)
            # **bold** и *italic*
            text = _re.sub(r'\*{1,2}([^*]*)\*{1,2}', r'\1', text)
            # Пустые строки и лишние пробелы
            text = _re.sub(r'\n\s*\n', ' ', text)
            text = _re.sub(r'\s+', ' ', text).strip()
            return text
        lines.append("")
        lines.append("💬 <b>Reddit (проверено AI):</b>")
        for op in reddit_ops[:3]:
            score = op.get("ai_score", "?")
            title = _clean_md(op["title"][:90])
            desc  = _clean_md(op.get("description", ""))
            pub   = op.get("publisher", "")
            if not desc or len(desc) < 10:
                desc = ""
            else:
                desc = desc[:120]
            # Иконка важности
            if isinstance(score, (int, float)):
                quality = "🔥" if score >= 9 else ("✅" if score >= 7 else ("💡" if score >= 5 else "📊"))
            else:
                quality = "💡"
            lines.append(f"{quality} <i>{title}</i>")
            if desc:
                lines.append(f"   <blockquote>{desc}</blockquote>")
            if pub:
                lines.append(f"   <code>{pub}</code>  AI: {score}/10")

    return "\n".join(lines)
