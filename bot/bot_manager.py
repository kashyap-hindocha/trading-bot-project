"""
Bot Manager — Spawns and manages multiple bot instances
========================================================
Reads enabled pairs from DB and spawns a bot process for each.
"""

import os
import sys
import time
import signal
import logging
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/ubuntu/trading-bot/data/bot_manager.log"),
    ],
)
logger = logging.getLogger(__name__)

# Track spawned processes
bot_processes = {}
shutdown_flag = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_flag
    logger.info("Received shutdown signal, stopping all bots...")
    shutdown_flag = True
    stop_all_bots()
    sys.exit(0)


def start_bot_for_pair(pair: str):
    """Start a bot process for a specific trading pair."""
    try:
        # Python interpreter path
        python_exe = sys.executable
        bot_script = Path(__file__).parent / "main.py"
        
        logger.info(f"Starting bot for {pair}...")
        
        # Spawn bot process with pair as argument
        proc = subprocess.Popen(
            [python_exe, str(bot_script), pair],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        bot_processes[pair] = proc
        logger.info(f"Bot started for {pair} (PID: {proc.pid})")
        db.log_event("INFO", f"Started bot for {pair} (PID: {proc.pid})")
        
        return proc
    except Exception as e:
        logger.error(f"Failed to start bot for {pair}: {e}")
        db.log_event("ERROR", f"Failed to start bot for {pair}: {e}")
        return None


def stop_bot_for_pair(pair: str):
    """Stop a bot process for a specific trading pair."""
    if pair not in bot_processes:
        return
    
    proc = bot_processes[pair]
    try:
        logger.info(f"Stopping bot for {pair} (PID: {proc.pid})...")
        proc.terminate()
        
        # Wait up to 5 seconds for graceful shutdown
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning(f"Bot {pair} didn't stop gracefully, killing...")
            proc.kill()
            proc.wait()
        
        logger.info(f"Bot stopped for {pair}")
        db.log_event("INFO", f"Stopped bot for {pair}")
    except Exception as e:
        logger.error(f"Error stopping bot for {pair}: {e}")
    finally:
        del bot_processes[pair]


def stop_all_bots():
    """Stop all running bot processes."""
    pairs = list(bot_processes.keys())
    for pair in pairs:
        stop_bot_for_pair(pair)


def sync_bots_with_config():
    """Sync running bots with enabled pairs in database."""
    try:
        enabled_pairs = db.get_enabled_pairs()
        enabled_pair_names = {p["pair"] for p in enabled_pairs}
        running_pairs = set(bot_processes.keys())
        
        # Stop bots for disabled pairs
        to_stop = running_pairs - enabled_pair_names
        for pair in to_stop:
            stop_bot_for_pair(pair)
        
        # Start bots for newly enabled pairs
        to_start = enabled_pair_names - running_pairs
        for pair in to_start:
            start_bot_for_pair(pair)
        
        # Check if any bots have crashed
        for pair in list(bot_processes.keys()):
            proc = bot_processes[pair]
            if proc.poll() is not None:  # Process has exited
                logger.warning(f"Bot for {pair} has stopped (exit code: {proc.returncode}), restarting...")
                db.log_event("WARNING", f"Bot for {pair} crashed, restarting...")
                del bot_processes[pair]
                if pair in enabled_pair_names:
                    start_bot_for_pair(pair)
        
    except Exception as e:
        logger.error(f"Error syncing bots: {e}")


def main():
    """Main bot manager loop."""
    logger.info("=== Bot Manager Starting ===")
    
    # Initialize database
    os.makedirs("/home/ubuntu/trading-bot/data", exist_ok=True)
    db.init_db()
    db.log_event("INFO", "Bot Manager started")
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Main monitoring loop
    try:
        while not shutdown_flag:
            sync_bots_with_config()
            
            # Log status
            if bot_processes:
                logger.info(f"Running bots: {', '.join(bot_processes.keys())}")
            else:
                logger.info("No bots currently running (no pairs enabled)")
            
            # Wait 30 seconds before next sync
            time.sleep(30)
    
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        stop_all_bots()
        logger.info("Bot Manager stopped")
        db.log_event("INFO", "Bot Manager stopped")


if __name__ == "__main__":
    main()
