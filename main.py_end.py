
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    asyncio.create_task(run_hltv_update_task())
    asyncio.create_task(check_results_task(bot))
    asyncio.create_task(auto_elo_recalibration_task())
    asyncio.create_task(auto_refresh_matches_task())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
