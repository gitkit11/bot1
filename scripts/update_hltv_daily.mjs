/**
 * scripts/update_hltv_daily.mjs — Ежедневное обновление статистики HLTV
 * =========================================================================
 * Использует npm пакет 'hltv' который обходит Cloudflare через реальный TLS.
 *
 * Что обновляет:
 *   - Рейтинг игроков (HLTV Rating 2.0) для каждой команды
 *   - Текущий состав команды
 *   - Общий винрейт команды (из последних 30 матчей)
 *
 * Что НЕ может получить бесплатно:
 *   - Winrate по отдельным картам (Cloudflare блокирует /stats/* страницы)
 *   - ADR, K/D (только rating доступен через getPlayer)
 *
 * Запуск: node scripts/update_hltv_daily.mjs
 * Автозапуск: каждый день в 06:00 через планировщик Manus
 */

import { HLTV } from 'hltv';
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = join(__dirname, '..');
const STATS_FILE = join(PROJECT_ROOT, 'sports', 'cs2', 'hltv_stats.py');
const LOG_FILE = join(PROJECT_ROOT, 'logs', 'hltv_update.log');

// ─── Команды и их HLTV ID ────────────────────────────────────────────────────
const TEAMS = [
    { name: "Team Vitality",   id: 9565  },
    { name: "G2 Esports",      id: 5995  },
    { name: "FaZe Clan",       id: 6667  },
    { name: "Natus Vincere",   id: 4608  },
    { name: "Team Spirit",     id: 7020  },
    { name: "MOUZ",            id: 4494  },
    { name: "Heroic",          id: 7175  },
    { name: "Astralis",        id: 4411  },
    { name: "Team Liquid",     id: 5973  },
    { name: "FURIA",           id: 8297  },
    { name: "The MongolZ",     id: 11595 },
    { name: "Cloud9",          id: 5005  },
    { name: "BIG",             id: 8068  },
    { name: "Falcons",         id: 12279 },
];

// ─── Вспомогательные функции ─────────────────────────────────────────────────
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function log(msg) {
    const ts = new Date().toISOString().replace('T', ' ').substring(0, 19);
    const line = `[${ts}] ${msg}`;
    console.log(line);
    try {
        mkdirSync(join(PROJECT_ROOT, 'logs'), { recursive: true });
        writeFileSync(LOG_FILE, line + '\n', { flag: 'a' });
    } catch {}
}

// ─── Получить данные команды ─────────────────────────────────────────────────
async function fetchTeamData(team) {
    const result = { name: team.name, players: [], winrate: null };

    // 1. Состав и рейтинги игроков
    try {
        const teamInfo = await HLTV.getTeam({ id: team.id });
        const players = teamInfo.players || [];

        for (const p of players.slice(0, 5)) {
            try {
                const playerInfo = await HLTV.getPlayer({ id: p.id });
                result.players.push({
                    name: p.name,
                    id: p.id,
                    rating: playerInfo.statistics?.rating || null,
                });
                await sleep(600);
            } catch (e) {
                result.players.push({ name: p.name, id: p.id, rating: null });
            }
        }
        log(`  ✅ ${team.name}: ${result.players.length} players fetched`);
    } catch (e) {
        log(`  ⚠️ ${team.name} team info failed: ${e.message?.substring(0, 60)}`);
    }

    // 2. Общий винрейт из истории матчей
    try {
        const results = await HLTV.getResults({ teamIds: [team.id], count: 20 });
        let wins = 0, losses = 0;
        for (const r of results) {
            const isTeam1 = r.team1?.name?.toLowerCase().includes(
                team.name.toLowerCase().replace('team ', '').split(' ')[0]
            );
            const t1 = r.result?.team1 || 0;
            const t2 = r.result?.team2 || 0;
            const won = isTeam1 ? t1 > t2 : t2 > t1;
            if (won) wins++; else losses++;
        }
        const total = wins + losses;
        if (total > 0) {
            result.winrate = Math.round(wins / total * 1000) / 10;
            log(`  ✅ ${team.name}: WR=${result.winrate}% (${wins}W/${losses}L)`);
        }
    } catch (e) {
        log(`  ⚠️ ${team.name} results failed: ${e.message?.substring(0, 60)}`);
    }

    return result;
}

// ─── Генерация Python файла ──────────────────────────────────────────────────
function generatePythonFile(allTeamData, updateDate) {
    // Читаем текущий файл
    let current = '';
    try {
        current = readFileSync(STATS_FILE, 'utf8');
    } catch {
        log('⚠️ Could not read current hltv_stats.py');
        return null;
    }

    // Формируем новый блок PLAYER_STATS
    const playerLines = ['PLAYER_STATS: dict[str, list[dict]] = {\n'];
    for (const team of allTeamData) {
        if (!team || !team.players.length) continue;
        playerLines.push(`    "${team.name}": [\n`);
        for (const p of team.players) {
            const rating = p.rating ? p.rating.toFixed(2) : 'None';
            playerLines.push(`        {"name": "${p.name}", "id": ${p.id}, "rating": ${rating}, "adr": None, "role": None},\n`);
        }
        playerLines.push('    ],\n');
    }
    playerLines.push('}\n');
    const newPlayerBlock = playerLines.join('');

    // Формируем блок TEAM_WINRATES (общий WR из HLTV)
    const wrLines = ['TEAM_WINRATES: dict[str, float | None] = {\n'];
    for (const team of allTeamData) {
        if (!team) continue;
        const wr = team.winrate !== null ? team.winrate : 'None';
        wrLines.push(`    "${team.name}": ${wr},\n`);
    }
    wrLines.push('}\n');
    const newWrBlock = wrLines.join('');

    // Обновляем дату
    let updated = current.replace(
        /# Дата обновления: \d{4}-\d{2}-\d{2}/,
        `# Дата обновления: ${updateDate}`
    );

    // Заменяем или добавляем PLAYER_STATS блок
    if (updated.includes('PLAYER_STATS:')) {
        updated = updated.replace(
            /PLAYER_STATS: dict\[str, list\[dict\]\] = \{[\s\S]*?\n\}/,
            newPlayerBlock.trimEnd()
        );
    } else {
        updated += '\n\n' + newPlayerBlock;
    }

    // Заменяем или добавляем TEAM_WINRATES блок
    if (updated.includes('TEAM_WINRATES:')) {
        updated = updated.replace(
            /TEAM_WINRATES: dict\[str, float \| None\] = \{[\s\S]*?\n\}/,
            newWrBlock.trimEnd()
        );
    } else {
        updated += '\n\n' + newWrBlock;
    }

    return updated;
}

// ─── Главная функция ─────────────────────────────────────────────────────────
async function main() {
    const updateDate = new Date().toISOString().substring(0, 10);
    log(`=== HLTV Daily Update started: ${updateDate} ===`);

    const allTeamData = [];
    let successCount = 0;

    for (const team of TEAMS) {
        log(`\nFetching: ${team.name}...`);
        try {
            const data = await fetchTeamData(team);
            allTeamData.push(data);
            if (data.players.length > 0 || data.winrate !== null) {
                successCount++;
            }
        } catch (e) {
            log(`❌ Fatal error for ${team.name}: ${e.message?.substring(0, 80)}`);
            allTeamData.push(null);
        }
        // Пауза между командами чтобы не перегружать HLTV
        await sleep(2000);
    }

    log(`\n=== Fetched ${successCount}/${TEAMS.length} teams ===`);

    if (successCount > 0) {
        const newContent = generatePythonFile(allTeamData, updateDate);
        if (newContent) {
            writeFileSync(STATS_FILE, newContent, 'utf8');
            log(`✅ hltv_stats.py updated successfully`);
        }
    } else {
        log('⚠️ No data fetched, hltv_stats.py not updated');
    }

    // Вывод итогов в JSON для Python
    const summary = {
        date: updateDate,
        teams_updated: successCount,
        teams_total: TEAMS.length,
        data: allTeamData.filter(Boolean).map(t => ({
            name: t.name,
            winrate: t.winrate,
            players: t.players.map(p => ({ name: p.name, rating: p.rating }))
        }))
    };
    console.log('\n__SUMMARY__');
    console.log(JSON.stringify(summary));
}

main().catch(e => {
    log(`FATAL: ${e.message}`);
    process.exit(1);
});
