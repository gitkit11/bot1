import sys
from pathlib import Path
import asyncio
import logging

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from meta_learner import MetaLearner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

async def run_meta_learner_update():
    logger.info("=== MetaLearner update started ===")
    meta_learner = MetaLearner(db_path=str(PROJECT_ROOT / 'chimera_predictions.db'), signal_engine_path=str(PROJECT_ROOT / 'signal_engine.py'))

    sports = ["football", "cs2"]
    for sport in sports:
        logger.info(f"Analyzing performance for {sport.upper()}...")
        performance_data = meta_learner.analyze_performance(sport)
        logger.info(f"Performance data for {sport.upper()}: {performance_data}")

        suggested_updates = meta_learner.suggest_config_updates(sport, performance_data)
        if suggested_updates:
            logger.info(f"Suggested updates for {sport.upper()}: {suggested_updates}")
            meta_learner.apply_config_updates(sport, suggested_updates)
            logger.info(f"Applied updates for {sport.upper()}")
        else:
            logger.info(f"No significant updates suggested for {sport.upper()}")
    
    logger.info("=== MetaLearner update finished ===")

if __name__ == "__main__":
    asyncio.run(run_meta_learner_update())
