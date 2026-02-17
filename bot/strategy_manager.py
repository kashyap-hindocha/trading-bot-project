"""
Strategy Manager
================
Manages loading, switching, and execution of multiple trading strategies.
"""

import importlib
import importlib.util
import os
import logging
from typing import Dict, List, Optional, Type
from strategy_base import TradingStrategy

logger = logging.getLogger(__name__)


class StrategyManager:
    """
    Manages multiple trading strategies with dynamic loading and switching.
    """

    def __init__(self, strategies_dir: str = "strategies"):
        self.strategies_dir = strategies_dir
        self.strategies: Dict[str, Type[TradingStrategy]] = {}
        self.active_strategy: Optional[TradingStrategy] = None
        self.active_strategy_name: Optional[str] = None

        # Auto-discover and load strategies
        self._load_strategies()

    def _load_strategies(self) -> None:
        """Auto-discover and load all strategy classes from strategies/ directory."""
        strategies_path = os.path.join(os.path.dirname(__file__), self.strategies_dir)

        if not os.path.exists(strategies_path):
            logger.warning(f"Strategies directory not found: {strategies_path}")
            return

        logger.info(f"Loading strategies from: {strategies_path}")

        # Import all .py files in strategies directory
        for filename in os.listdir(strategies_path):
            if filename.endswith('.py') and not filename.startswith('__'):
                module_name = filename[:-3]  # Remove .py extension
                try:
                    # Import using the full path to ensure proper module location
                    spec = importlib.util.spec_from_file_location(
                        f"strategies.{module_name}",
                        os.path.join(strategies_path, filename)
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        # Find strategy classes in the module
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if (isinstance(attr, type) and
                                issubclass(attr, TradingStrategy) and
                                attr != TradingStrategy):
                                strategy_name = attr().get_name().lower().replace(' ', '_')
                                self.strategies[strategy_name] = attr
                                logger.info(f"Loaded strategy: {strategy_name} ({attr.__name__})")

                except Exception as e:
                    logger.error(f"Failed to load strategy {module_name}: {e}")

        logger.info(f"Loaded {len(self.strategies)} strategies: {list(self.strategies.keys())}")

    def get_available_strategies(self) -> List[Dict]:
        """Get list of all available strategies with metadata."""
        strategies_info = []
        for name, strategy_class in self.strategies.items():
            try:
                instance = strategy_class()
                strategies_info.append({
                    "name": name,
                    "display_name": instance.get_name(),
                    "description": instance.get_description(),
                    "config": instance.get_config()
                })
            except Exception as e:
                logger.error(f"Error getting info for strategy {name}: {e}")

        return strategies_info

    def set_active_strategy(self, strategy_name: str) -> bool:
        """
        Set the active strategy by name.

        Args:
            strategy_name: Strategy name (lowercase, underscores)

        Returns:
            bool: True if successful, False otherwise
        """
        if strategy_name not in self.strategies:
            logger.error(f"Strategy not found: {strategy_name}")
            return False

        try:
            self.active_strategy = self.strategies[strategy_name]()
            self.active_strategy_name = strategy_name
            logger.info(f"Activated strategy: {strategy_name} ({self.active_strategy.get_name()})")
            return True
        except Exception as e:
            logger.error(f"Failed to activate strategy {strategy_name}: {e}")
            return False

    def get_active_strategy(self) -> Optional[TradingStrategy]:
        """Get the currently active strategy instance."""
        return self.active_strategy

    def get_active_strategy_name(self) -> Optional[str]:
        """Get the name of the currently active strategy."""
        return self.active_strategy_name

    def evaluate(self, candles: List[Dict], return_confidence: bool = True) -> Optional[Dict]:
        """Evaluate candles using the active strategy."""
        if not self.active_strategy:
            logger.warning("No active strategy set")
            return None

        try:
            return self.active_strategy.evaluate(candles, return_confidence)
        except Exception as e:
            logger.error(f"Strategy evaluation failed: {e}")
            return None

    def calculate_tp_sl(self, entry_price: float, position_type: str, **kwargs) -> tuple[float, float]:
        """Calculate TP/SL using the active strategy."""
        if not self.active_strategy:
            logger.warning("No active strategy set")
            return (0.0, 0.0)

        try:
            return self.active_strategy.calculate_tp_sl(entry_price, position_type, **kwargs)
        except Exception as e:
            logger.error(f"TP/SL calculation failed: {e}")
            return (0.0, 0.0)

    def get_config(self) -> Optional[Dict]:
        """Get active strategy configuration."""
        if not self.active_strategy:
            return None
        return self.active_strategy.get_config()

    def update_config(self, new_config: Dict) -> bool:
        """Update active strategy configuration."""
        if not self.active_strategy:
            logger.warning("No active strategy set")
            return False

        try:
            self.active_strategy.update_config(new_config)
            return True
        except Exception as e:
            logger.error(f"Config update failed: {e}")
            return False

    def reload_strategies(self) -> None:
        """Reload all strategies from disk."""
        self.strategies.clear()
        self._load_strategies()
        logger.info("Reloaded all strategies")


# Global strategy manager instance
strategy_manager = StrategyManager()