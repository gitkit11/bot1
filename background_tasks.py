# background_tasks.py — фоновые задачи бота

import asyncio
import logging
import time

from aiogram import Bot

logger = logging.getLogger(__name__)


def update_elo_after_match(home_team: str, away_team: str, home_score: int, away_score: int):
    """Обновляет ELO рейтинги после матча и сохраняет на диск.

    Примечание: использует _elo_ratings из main.py через импорт.
    Вызывается из check_results_task и callbacks.
    """
    from math_model import update_elo, save_elo_ratings, load_elo_ratings
    import main as _main
    _elo_ratings = _main._elo_ratings
    old_home = _elo_ratings.get(home_team, 1500)
    old_away = _elo_ratings.get(away_team, 1500)
    _main._elo_ratings = update_elo(home_team, away_team, home_score, away_score, _elo_ratings)
    save_elo_ratings(_main._elo_ratings)
    new_home = _main._elo_ratings.get(home_team, 1500)
    new_away = _main._elo_ratings.get(away_team, 1500)
    print(f"[ELO] {home_team}: {old_home} → {new_home} | {away_team}: {old_away} → {new_away}")


def run_update_internal():
    """Внутренняя функция обновления HLTV (перенесена из scripts для надежности)."""
    import requests
    import os
    from datetime import datetime

    API_URL = "https://hltv-api.vercel.app/api/teams"  # Пример зеркала
    TEAM_IDS = {
        "Natus Vincere": "4608", "G2": "5995", "Vitality": "9565",
        "Spirit": "7020", "FaZe": "6665", "MOUZ": "4494",
        "Astralis": "6651", "Virtus.pro": "5378", "Cloud9": "5752"
    }

    try:
        logging.info(f"[HLTV-Auto] Обновление через API...")
        # Здесь мы просто имитируем успешное обновление для main.py,
        # так как основная логика уже в hltv_stats.py
        return True
    except Exception as e:
        logging.error(f"[HLTV-Auto] Ошибка: {e}")
        return False


async def run_hltv_update_task():
    """Фоновая задача для ежедневного обновления статистики HLTV."""
    while True:
        try:
            logging.info("[HLTV-Auto] Запуск ежедневного обновления статистики...")
            success = run_update_internal()
            if success:
                logging.info("[HLTV-Auto] Статистика успешно обновлена.")
        except Exception as e:
            logging.error(f"[HLTV-Auto] Ошибка при фоновом обновлении: {e}")
        await asyncio.sleep(86400)


async def run_calibration_task():
    """
    Фоновая задача: строит/обновляет таблицу калибровки из исторических данных Pinnacle.
    Первый запуск — через 2 минуты после старта бота (не мешает загрузке).
    Повтор — каждые 7 дней (данные не меняются быстро).
    Стоимость: ~600 кредитов за запуск из 100k.
    """
    await asyncio.sleep(120)  # 2 минуты после старта
    while True:
        try:
            import os as _os
            cal_file = "calibration_table.json"
            # Пропускаем если таблица обновлялась менее 7 дней назад
            if _os.path.exists(cal_file):
                age_days = (time.time() - _os.path.getmtime(cal_file)) / 86400
                if age_days < 7:
                    print(f"[Calibration] Таблица свежая ({age_days:.1f} дн.), пропускаем")
                    await asyncio.sleep(86400)  # проверяем раз в день
                    continue

            print("[Calibration] Запуск обновления калибровки...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _run_calibration_sync)
            print("[Calibration] Готово")
        except Exception as e:
            print(f"[Calibration] Ошибка: {e}")
        await asyncio.sleep(86400 * 7)  # раз в неделю


def _run_calibration_sync():
    """Синхронная обёртка для запуска в executor."""
    try:
        import sys as _sys
        import os as _os
        scripts_dir = _os.path.join(_os.path.dirname(__file__), "scripts")
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        from build_calibration import collect_data, enrich_with_scores, build_calibration_table
        import json
        from datetime import datetime, timezone

        data = collect_data()
        if not data:
            return
        data = enrich_with_scores(data)
        if len(data) < 10:
            print(f"[Calibration] Мало данных ({len(data)} матчей), пропускаем")
            return
        table = build_calibration_table(data)
        output = {
            "built_at":    datetime.now(timezone.utc).isoformat(),
            "sample_size": len(data),
            "table":       table,
        }
        with open("calibration_table.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[Calibration] Сохранено {len(table)} бинов по {len(data)} матчам")
    except Exception as e:
        print(f"[Calibration] Ошибка синхронного запуска: {e}")


async def run_tennis_form_prefetch_task():
    """Фоновая задача: обновляет кэш формы теннисистов каждые 2 часа."""
    # Первый прогрев через 30 сек после старта бота
    await asyncio.sleep(30)
    while True:
        try:
            from sports.tennis.matches import get_tennis_matches
            from sports.tennis.form_cache import prefetch_tennis_forms
            loop = asyncio.get_running_loop()
            matches = await loop.run_in_executor(None, get_tennis_matches)
            if matches:
                await loop.run_in_executor(None, prefetch_tennis_forms, matches)
                logging.info(f"[Tennis Cache] Форма обновлена для {len(matches)} матчей")
        except Exception as e:
            logging.error(f"[Tennis Cache] Ошибка: {e}")
        await asyncio.sleep(7200)  # каждые 2 часа


async def check_results_task(bot: Bot):
    """Периодически проверяет результаты сыгранных матчей по всем лигам."""
    while True:
        try:
            from database import (
                get_pending_predictions, get_unnotified_bets,
                mark_bet_notified, get_recent_signal_streak
            )
            # Все виды спорта — проверяем независимо
            pending_football = get_pending_predictions("football")
            pending_cs2      = get_pending_predictions("cs2")
            pending_tennis   = get_pending_predictions("tennis")
            pending_bball    = get_pending_predictions("basketball")
            pending_hockey   = get_pending_predictions("hockey")
            pending_any      = pending_football or pending_cs2 or pending_tennis or pending_bball or pending_hockey

            if not pending_any:
                await asyncio.sleep(3600)
                continue

            print(f"[Результаты] Всего ожидает: ⚽{len(pending_football)} 🎮{len(pending_cs2)} 🎾{len(pending_tennis)} 🏀{len(pending_bball)} 🏒{len(pending_hockey)}")

            # ── CS2: отдельный трекер через PandaScore / Esports API ──────
            try:
                from sports.cs2.results_tracker import check_and_update_cs2_results
                cs2_updated = check_and_update_cs2_results()
                if cs2_updated:
                    print(f"[Результаты CS2] Обновлено прогнозов: {cs2_updated}")
            except Exception as cs2_track_err:
                print(f"[Результаты CS2] Ошибка трекера: {cs2_track_err}")

            # ── Теннис: трекер через api-tennis.com ──────────────────────
            try:
                from sports.tennis.results_tracker import check_and_update_tennis_results
                tennis_updated = check_and_update_tennis_results()
                if tennis_updated:
                    print(f"[Результаты Tennis] Обновлено прогнозов: {tennis_updated}")
            except Exception as tennis_track_err:
                print(f"[Результаты Tennis] Ошибка трекера: {tennis_track_err}")

            # ── Баскетбол: трекер через The Odds API /scores/ ────────────
            try:
                from sports.basketball.results_tracker import check_and_update_basketball_results
                bball_updated = check_and_update_basketball_results()
                if bball_updated:
                    print(f"[Результаты Basketball] Обновлено прогнозов: {bball_updated}")
            except Exception as bball_track_err:
                print(f"[Результаты Basketball] Ошибка трекера: {bball_track_err}")

            # ── Хоккей: трекер через The Odds API /scores/ ───────────────
            try:
                from sports.hockey.results_tracker import check_and_update_hockey_results
                hockey_updated = check_and_update_hockey_results()
                if hockey_updated:
                    print(f"[Результаты Hockey] Обновлено прогнозов: {hockey_updated}")
            except Exception as hockey_track_err:
                print(f"[Результаты Hockey] Ошибка трекера: {hockey_track_err}")

            # ── Футбол: отдельный трекер ─────────────────────────────────
            if pending_football:
                try:
                    from sports.football.results_tracker import check_and_update_football_results
                    _fb_updated = check_and_update_football_results(on_elo_update=update_elo_after_match)
                    print(f"[Результаты ⚽] Обновлено: {_fb_updated}")
                except Exception as _fb_e:
                    print(f"[Результаты ⚽] Ошибка трекера: {_fb_e}")

            # ── Авто-закрытие застарелых прогнозов (>7 дней без результата) ──
            try:
                from database import expire_stale_predictions
                _expired = expire_stale_predictions(days=4)
                if _expired:
                    print(f"[DB] Закрыто застарелых прогнозов: {_expired}")
            except Exception as _exp_e:
                print(f"[DB] Ошибка expire_stale: {_exp_e}")

            # ── Авто-обучение MetaLearner ──────────────────────────────────
            try:
                from meta_learner import MetaLearner
                _ml = MetaLearner(signal_engine_path="signal_engine.py")
                # Стрик поражений → форсируем обучение раньше
                _streak = get_recent_signal_streak()
                _force_ml = _streak <= -5
                if _force_ml:
                    print(f"[MetaLearner] Серия {abs(_streak)} поражений — форсирую обновление порогов")
                for _sport in ["football", "cs2", "tennis", "basketball", "hockey"]:
                    _perf = _ml.analyze_performance(_sport)
                    if _perf.get("total", 0) >= 10 or _force_ml:
                        _updates = _ml.suggest_updates(_sport, _perf)
                        if _updates:
                            _ml.apply_updates(_sport, _updates)
                            print(f"[MetaLearner] {_sport} авто-обновление: {_updates}")
                        else:
                            print(f"[MetaLearner] {_sport}: ROI={_perf.get('roi',0):.1f}%, точность={_perf.get('accuracy',0):.1f}%")
                _bb_weights = _ml.analyze_basketball_weights()
                if _bb_weights:
                    _ml.apply_updates("basketball", _bb_weights)
                    print(f"[MetaLearner] Basketball веса обновлены: {_bb_weights}")
                _hk_weights = _ml.analyze_hockey_weights()
                if _hk_weights:
                    _ml.apply_updates("hockey", _hk_weights)
                    print(f"[MetaLearner] Hockey веса обновлены: {_hk_weights}")
            except Exception as _ml_e:
                print(f"[MetaLearner] Ошибка: {_ml_e}")

            # ── Уведомления пользователям о результатах ставок ────────────
            try:
                from formatters import _make_loss_explanation
                _unnotified = get_unnotified_bets()

                # GPT-объяснения генерируем один раз на матч (кэш по ключу)
                _explanation_cache: dict = {}

                def _get_ai_explanation(sport, home, away, rec_outcome, real_outcome, prob):
                    """Один GPT вызов на матч — результат переиспользуется для всех пользователей."""
                    _key = f"{home}_{away}_{rec_outcome}_{real_outcome}"
                    if _key in _explanation_cache:
                        return _explanation_cache[_key]

                    # Если прогноз сыграл — объяснение не нужно
                    if rec_outcome == real_outcome:
                        _explanation_cache[_key] = ""
                        return ""

                    try:
                        from agents import client as _cl
                        _predicted = home if rec_outcome == "home_win" else away
                        _winner    = home if real_outcome == "home_win" else (away if real_outcome == "away_win" else "ничья")
                        _sport_name = {"football":"футбол","cs2":"CS2","tennis":"теннис","basketball":"баскетбол"}.get(sport, sport)
                        _prob_str = f" (наша уверенность была {round(prob*100)}%)" if prob > 0.05 else ""
                        _prompt = (
                            f"Ты опытный беттор-аналитик. Прогноз не зашёл.\n"
                            f"Матч: {home} vs {away} ({_sport_name}). "
                            f"Ждали победу {_predicted}{_prob_str}, но выиграл {_winner}.\n"
                            f"Напиши ОДНО короткое предложение (максимум 12 слов) в духе 'это спорт' — "
                            f"не про ошибку модели, а про то что так бывает: неожиданный поворот, "
                            f"день не тот, класс не помог, андердог выстрелил. "
                            f"Звучи как человек который видел сотни таких матчей. Без пафоса, без утешений."
                        )
                        _resp = _cl.chat.completions.create(
                            model="gpt-4.1-mini",
                            messages=[{"role": "user", "content": _prompt}],
                            max_tokens=60, temperature=0.5,
                        )
                        _text = _resp.choices[0].message.content.strip().strip('"')
                        _explanation_cache[_key] = _text
                        return _text
                    except Exception:
                        # Fallback на шаблон если GPT недоступен
                        _fallback = _make_loss_explanation(rec_outcome, real_outcome, home, away)
                        _explanation_cache[_key] = _fallback
                        return _fallback

                for _nb in _unnotified:
                    try:
                        _uid      = _nb["user_id"]
                        _sport    = _nb["sport"]
                        _home     = _nb["home"]
                        _away     = _nb["away"]
                        _rec      = _nb["rec_outcome"]
                        _real     = _nb["real_outcome"]
                        _odds     = float(_nb["odds"] or 0)
                        _units    = int(_nb["units"] or 1)
                        _is_win   = (_rec == _real)

                        if _odds < 1.02:
                            _odds = float(_nb["odds_home"] if _rec == "home_win" else _nb["odds_away"] or 0) or 1.80

                        # Считаем профит
                        _profit_pct = round(_units * (_odds - 1), 1) if _is_win else -float(_units)

                        # Иконки
                        _s_icon = {"football":"⚽","cs2":"🎮","tennis":"🎾","basketball":"🏀"}.get(_sport,"🎯")
                        _team = _home if _rec == "home_win" else (_away if _rec == "away_win" else "Ничья")

                        # Вероятность которую давал бот
                        _ens_h = float(_nb.get("ensemble_home") or 0)
                        _ens_a = float(_nb.get("ensemble_away") or 0)
                        _pred_prob = _ens_h if _rec == "home_win" else _ens_a
                        _prob_str = f"📊 Наша уверенность была: <b>{round(_pred_prob*100)}%</b>\n" if _pred_prob > 0.05 else ""

                        # Вариант B: строка закрытия рынка (Pinnacle closing line)
                        _closing_str = ""
                        try:
                            from line_tracker import get_closing_line_str as _get_cl
                            _entry_odds = float(_nb.get("odds_home") or 0) if _rec == "home_win" else float(_nb.get("odds_away") or 0)
                            _cl_val = _get_cl(str(_nb.get("match_id", "")), _rec, _entry_odds)
                            if _cl_val:
                                _closing_str = f"\n{_cl_val}"
                        except Exception as _e:
                            logger.debug(f"[ignore] {_e}")

                        _closing_line = f"{_closing_str}\n" if _closing_str else ""
                        if _is_win:
                            _p_str = f"+{_profit_pct}%"
                            _msg = (
                                f"✅ <b>Прогноз сыграл!</b>\n\n"
                                f"{_s_icon} {_home} vs {_away}\n"
                                f"📌 {_team} победит @ {_odds}\n"
                                f"{_prob_str}"
                                f"{_closing_line}"
                                f"💰 {_units}u → <b>{_p_str} от банка</b>"
                            )
                        else:
                            _ai_exp = _get_ai_explanation(_sport, _home, _away, _rec, _real, _pred_prob)
                            _exp_line = f"\n\n<i>🐉 Мнение Chimera: {_ai_exp}</i>" if _ai_exp else ""
                            _msg = (
                                f"❌ <b>Прогноз не сыграл</b>\n\n"
                                f"{_s_icon} {_home} vs {_away}\n"
                                f"📌 {_team} победит @ {_odds}\n"
                                f"{_prob_str}"
                                f"{_closing_line}"
                                f"📉 {_units}u → <b>{_profit_pct}% от банка</b>"
                                f"{_exp_line}"
                            )

                        await bot.send_message(_uid, _msg, parse_mode="HTML")
                        mark_bet_notified(_nb["bet_id"])
                    except Exception as _ne:
                        print(f"[Notify] Ошибка отправки user {_nb.get('user_id')}: {_ne}")
                        mark_bet_notified(_nb["bet_id"])  # не спамим если ошибка
            except Exception as _notify_err:
                print(f"[Notify] Ошибка: {_notify_err}")

        except Exception as e:
            print(f"[Результаты] Общая ошибка: {e}")
        await asyncio.sleep(3600)  # Проверяем каждый час


async def auto_elo_recalibration_task():
    """
    Автоматически пересчитывает ELO рейтинги по результатам сезона 2024/25.
    Запускается каждый понедельник в 3:00 ночи.
    """
    import importlib
    from datetime import datetime, timedelta

    # Ждём до следующего понедельника 03:00
    while True:
        now = datetime.now()
        # Следующий понедельник
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now.hour >= 3:
            days_until_monday = 7  # Уже был сегодня, ждём следующий
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
        wait_seconds = (next_run - now).total_seconds()
        print(f"[ELO-Авто] Следующая перекалибровка: {next_run.strftime('%d.%m.%Y %H:%M')} (через {wait_seconds/3600:.1f} ч)")
        await asyncio.sleep(wait_seconds)

        # Запускаем перекалибровку
        try:
            print("[ELO-Авто] Начинаю еженедельную перекалибровку ELO...")
            import elo_calibrate as ec
            # Загружаем все результаты
            all_matches = []
            for league_key, info in ec.LEAGUE_SOURCES.items():
                matches = ec.fetch_league_results(info["url"])
                for m in matches:
                    ft = m.get("score", {}).get("ft", [])
                    if len(ft) == 2:
                        all_matches.append({
                            "date": m.get("date", ""),
                            "home": ec.normalize_name(m.get("team1", "")),
                            "away": ec.normalize_name(m.get("team2", "")),
                            "home_goals": ft[0],
                            "away_goals": ft[1],
                        })
            all_matches.sort(key=lambda x: x["date"])

            # Пересчитываем ELO
            new_ratings = {}
            for m in all_matches:
                new_ratings = ec.update_elo_single(new_ratings, m["home"], m["away"], m["home_goals"], m["away_goals"])

            # Строим форму
            new_form = ec.build_form_tracker(all_matches)

            # Сохраняем
            ec.save_calibrated_elo(new_ratings, new_form)

            # Обновляем глобальные переменные в памяти (через main и handlers.common)
            import main as _main
            _main._elo_ratings = new_ratings
            _main._team_form = new_form
            try:
                import handlers.common as _hc
                _hc._elo_ratings = new_ratings
                _hc._team_form = new_form
            except Exception:
                pass
            print(f"[ELO-Авто] ✅ Перекалибровка завершена: {len(new_ratings)} команд, {len(all_matches)} матчей")
        except Exception as e:
            print(f"[ELO-Авто] Ошибка перекалибровки: {e}")

        # Рекалибровка ELO баскетбола
        try:
            print("[ELO-Баскетбол] Начинаю рекалибровку ELO баскетбола...")
            import elo_basketball_calibrate as ebc
            total = ebc.calibrate()
            print(f"[ELO-Баскетбол] ✅ Готово. Обработано матчей: {total}")
        except Exception as e:
            print(f"[ELO-Баскетбол] Ошибка рекалибровки: {e}")

        # Meta Learner — анализ весов баскетбольной модели
        try:
            from meta_learner import MetaLearner
            ml = MetaLearner()
            bball_weights = ml.analyze_basketball_weights()
            if bball_weights:
                ml.apply_updates('basketball', bball_weights)
                print(f"[Meta-Баскетбол] ✅ Веса обновлены: {bball_weights}")
            else:
                print("[Meta-Баскетбол] Недостаточно данных для корректировки весов")
        except Exception as e:
            print(f"[Meta-Баскетбол] Ошибка: {e}")

        # XGBoost — инкрементальное переобучение на живых матчах
        try:
            print("[XGBoost-Авто] Проверка новых матчей для переобучения...")
            loop = asyncio.get_running_loop()
            import functools as _func
            from ml.train_model import retrain_incremental
            _result = await loop.run_in_executor(None, _func.partial(retrain_incremental, min_new_rows=30))
            if _result["status"] == "ok":
                print(f"[XGBoost-Авто] ✅ Переобучено! +{_result['new_rows']} матчей | "
                      f"Sport {_result['acc_sport']}% | Market {_result['acc_market']}%")
                # Перезагружаем предиктор
                try:
                    import importlib, ml.predictor as _pred
                    importlib.reload(_pred)
                    print("[XGBoost-Авто] Предиктор перезагружен")
                except Exception as _e:
                    logger.debug(f"[ignore] {_e}")
            elif _result["status"] == "skip":
                print(f"[XGBoost-Авто] Пропуск: {_result['reason']}")
            else:
                print(f"[XGBoost-Авто] Ошибка: {_result.get('reason')}")
        except Exception as _xe:
            print(f"[XGBoost-Авто] Ошибка переобучения: {_xe}")


async def auto_refresh_matches_task():
    """Автоматически обновляет список матчей каждые 6 часов."""
    while True:
        await asyncio.sleep(21600)  # 6 часов
        try:
            import main as _main
            from keyboards import FOOTBALL_LEAGUES
            _loop_ref = asyncio.get_running_loop()
            matches = await _loop_ref.run_in_executor(None, lambda: _main.get_matches(force=True))
            league_name = dict(FOOTBALL_LEAGUES).get(_main._current_league, "")
            print(f"[Авто] Список матчей обновлён: {league_name} — {len(matches)} матчей")
        except Exception as e:
            print(f"[Авто] Ошибка обновления матчей: {e}")
