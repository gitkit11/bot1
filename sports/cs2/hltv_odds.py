import asyncio
import logging
import re
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

async def get_hltv_odds_async(team1: str, team2: str):
    """
    Парсит коэффициенты с HLTV.org для указанных команд.
    """
    search_url = f"https://www.hltv.org/search?query={team1}"
    logger.info(f"Searching HLTV for: {team1} vs {team2}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = await context.new_page()
            
            # 1. Идем на страницу матчей
            await page.goto("https://www.hltv.org/matches", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # 2. Ищем ссылку на матч по названиям команд
            match_link = await page.evaluate(f"""
                () => {{
                    const team1 = "{team1.lower()}";
                    const team2 = "{team2.lower()}";
                    const matchNodes = document.querySelectorAll('.upcomingMatch, .liveMatch');
                    for (const node of matchNodes) {{
                        const text = node.innerText.lower();
                        if (text.includes(team1) && text.includes(team2)) {{
                            const a = node.querySelector('a');
                            return a ? a.href : null;
                        }}
                    }}
                    return null;
                }}
            """)
            
            if not match_link:
                logger.warning(f"Match {team1} vs {team2} not found on HLTV matches page")
                await browser.close()
                return None
            
            # 3. Переходим на страницу матча
            await page.goto(match_link, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            
            # 4. Извлекаем коэффициенты
            odds = await page.evaluate("""
                () => {
                    const result = {};
                    // Ищем в блоке ставок
                    const oddsCells = document.querySelectorAll('.odds-cell');
                    if (oddsCells.length >= 2) {
                        result['team1'] = oddsCells[0].innerText.trim();
                        result['team2'] = oddsCells[1].innerText.trim();
                    }
                    
                    if (!result.team1) {
                        const bookmakerOdds = document.querySelectorAll('.bookmaker-odds-container');
                        if (bookmakerOdds.length > 0) {
                            const oddsValues = bookmakerOdds[0].querySelectorAll('.odds-value');
                            if (oddsValues.length >= 2) {
                                result['team1'] = oddsValues[0].innerText.trim();
                                result['team2'] = oddsValues[1].innerText.trim();
                            }
                        }
                    }
                    return result;
                }
            """)
            
            await browser.close()
            
            if odds and 'team1' in odds and 'team2' in odds:
                # Очищаем от лишних символов
                t1_odds = re.sub(r'[^0-9.]', '', odds['team1'])
                t2_odds = re.sub(r'[^0-9.]', '', odds['team2'])
                return {"home_win": float(t1_odds), "away_win": float(t2_odds)}
                
            return None
    except Exception as e:
        logger.error(f"Error scraping HLTV odds: {e}")
        return None

def get_hltv_odds(team1: str, team2: str):
    """Синхронная обертка для асинхронной функции."""
    try:
        return asyncio.run(get_hltv_odds_async(team1, team2))
    except Exception:
        # Если цикл уже запущен (например, в aiogram), используем другой подход
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Внутри запущенного цикла aiogram это может быть сложно, 
                # но для простоты пока оставим так.
                return None
            return loop.run_until_complete(get_hltv_odds_async(team1, team2))
        except:
            return None
