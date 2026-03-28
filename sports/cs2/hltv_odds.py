import logging
import re
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

def get_team_map_stats(team_name: str):
    """
    Парсит статистику карт команды с HLTV.org.
    Возвращает словарь: {map_name: win_rate_percent}
    """
    logger.info(f"Searching HLTV for map stats of: {team_name}")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            
            # 1. Ищем ID команды на HLTV
            search_query = f"{team_name} hltv team stats".replace(" ", "+")
            page.goto(f"https://duckduckgo.com/?q={search_query}", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            
            team_stats_link = page.evaluate("""
                (teamName) => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const hltvLink = links.find(a => a.href.includes('hltv.org/stats/teams/') && a.href.includes('/' + teamName.toLowerCase().replace(/ /g, '-') + '/'));
                    return hltvLink ? hltvLink.href : null;
                }
            """, team_name)
            
            if not team_stats_link:
                logger.warning(f"Team stats link for {team_name} not found on HLTV")
                browser.close()
                return {}
            
            # 2. Переходим на страницу статистики команды
            page.goto(team_stats_link, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            
            # 3. Кликаем на вкладку "Maps" (если она есть и не активна)
            mapsTab = page.query_selector("a.stats-top-menu-item[href$='/maps']")
            if mapsTab:
                isSelected = mapsTab.evaluate("node => node.classList.contains('stats-top-menu-item-selected')")
                if not isSelected:
                    mapsTab.click()
                    page.wait_for_timeout(2000)
            
            # 4. Извлекаем статистику по картам
            mapStats = page.evaluate("""
                () => {
                    const stats = {};
                    const mapRows = document.querySelectorAll('.stats-table tbody tr');
                    mapRows.forEach(row => {
                        const mapNameElement = row.querySelector('.stats-table-map-name');
                        const winRateElement = row.querySelector('.stats-table-win-rate');
                        if (mapNameElement && winRateElement) {
                            const mapName = mapNameElement.innerText.trim();
                            const winRateText = winRateElement.innerText.trim();
                            const winRate = parseFloat(winRateText.replace('%', ''));
                            if (!isNaN(winRate)) {
                                stats[mapName] = winRate;
                            }
                        }
                    });
                    return stats;
                }
            """)
            
            browser.close()
            return mapStats
    except Exception as e:
        logger.error(f"Error scraping HLTV map stats for {team_name}: {e}")
        return {}

def get_hltv_odds(team1: str, team2: str):
    """
    Парсит коэффициенты с HLTV.org для указанных команд.
    Поддерживает поиск по предстоящим матчам и прямым ссылкам.
    """
    logger.info(f"Searching HLTV for: {team1} vs {team2}")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            
            # 1. Идем на страницу матчей
            page.goto("https://www.hltv.org/matches", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            
            # 2. Ищем ссылку на матч по названиям команд (более гибкий поиск)
            match_link = page.evaluate("""
                (t1, t2) => {
                    const matchNodes = document.querySelectorAll('.upcomingMatch, .liveMatch, .match-day .match');
                    for (const node of matchNodes) {
                        const text = node.innerText.toLowerCase();
                        if (text.includes(t1) || text.includes(t2)) {
                            if (text.includes(t1) && text.includes(t2)) {
                                const a = node.querySelector('a');
                                return a ? a.href : null;
                            }
                        }
                    }
                    return null;
                }
            """, team1.lower(), team2.lower())
            
            # 3. Если не нашли на главной, пробуем поиск через DuckDuckGo (более стабильно чем Google без API)
            if not match_link:
                search_query = f"{team1} vs {team2} hltv matches".replace(" ", "+")
                page.goto(f"https://duckduckgo.com/?q={search_query}", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                match_link = page.evaluate("""
                    () => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const hltvLink = links.find(a => a.href.includes('hltv.org/matches/'));
                        return hltvLink ? hltvLink.href : null;
                    }
                """)

            if not match_link:
                logger.warning(f"Match {team1} vs {team2} not found on HLTV")
                browser.close()
                return None
            
            # 4. Переходим на страницу матча
            page.goto(match_link, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            
            # 5. Извлекаем коэффициенты (несколько вариантов селекторов)
            odds = page.evaluate("""
                () => {
                    const result = {};
                    
                    // Вариант 1: Стандартные ячейки
                    const oddsCells = document.querySelectorAll('.odds-cell');
                    if (oddsCells.length >= 2) {
                        result['team1'] = oddsCells[0].innerText.trim();
                        result['team2'] = oddsCells[1].innerText.trim();
                    }
                    
                    // Вариант 2: Блок букмекеров
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
                    
                    // Вариант 3: Сравнение коэффициентов
                    if (!result.team1) {
                        const externalOdds = document.querySelectorAll('.external-odds');
                        if (externalOdds.length >= 2) {
                            result['team1'] = externalOdds[0].innerText.trim();
                            result['team2'] = externalOdds[1].innerText.trim();
                        }
                    }

                    // Вариант 4: Блок сравнения коэффициентов (betting-listing)
                    if (!result.team1) {
                        const bettingListing = document.querySelector('.betting-listing');
                        if (bettingListing) {
                            const odds = bettingListing.querySelectorAll('.percentage');
                            if (odds.length >= 2) {
                                result['team1'] = odds[0].innerText.trim();
                                result['team2'] = odds[1].innerText.trim();
                            }
                        }
                    }
                    
                    return result;
                }
            """)
            
            browser.close()
            
            if odds and 'team1' in odds and 'team2' in odds:
                try:
                    # Очищаем от лишних символов (оставляем только цифры и точку)
                    t1_odds_str = re.sub(r'[^0-9.]', '', odds['team1'])
                    t2_odds_str = re.sub(r'[^0-9.]', '', odds['team2'])
                    
                    if t1_odds_str and t2_odds_str:
                        return {"home_win": float(t1_odds_str), "away_win": float(t2_odds_str)}
                except Exception:
                    pass
                
            return None
    except Exception as e:
        logger.error(f"Error scraping HLTV odds: {e}")
        return None
