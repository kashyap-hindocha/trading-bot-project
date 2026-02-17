"""
Strategy Base Class
===================
Abstract base class for all trading strategies.

All strategies must inherit from this class and implement:
- evaluate() method
- CONFIG dictionary
- get_name() method
- get_description() method
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class TradingStrategy(ABC):
    """
    Abstract base class for trading strategies.

    Each strategy must implement:
    - evaluate(): Main signal generation logic
    - CONFIG: Strategy configuration parameters
    - get_name(): Human-readable strategy name
    - get_description(): Strategy description
    """

    # Default configuration - strategies can override
    CONFIG = {
        "pair":          "B-BTC_USDT",
        "interval":      "5m",
        "leverage":      5,
        "quantity":      0.001,
        "inr_amount":    300.0,
        "tp_pct":        0.015,
        "sl_pct":        0.008,
        "max_open_trades": 5,
        "auto_execute":  True,
        "confidence_threshold": 75.0,
    }

    @abstractmethod
    def get_name(self) -> str:
        """Return human-readable strategy name."""
        pass

    @abstractmethod
    def get_description(self) -> str:
        """Return strategy description."""
        pass

    @abstractmethod
    def evaluate(self, candles: List[Dict], return_confidence: bool = True) -> Union[str, None, Dict]:
        """
        Evaluate candles and return trading signal.

        Args:
            candles: List of candle dicts with OHLCV data
            return_confidence: If True, return dict with confidence metrics

        Returns:
            dict: {"signal": str, "confidence": float, "auto_execute": bool, ...}
            or str: "BUY"/"SELL"/None (if return_confidence=False)
        """
        pass

    @abstractmethod
    def calculate_tp_sl(self, entry_price: float, position_type: str, **kwargs) -> tuple[float, float]:
        """
        Calculate take profit and stop loss prices.

        Args:
            entry_price: Entry price
            position_type: "LONG" or "SHORT"
            **kwargs: Additional parameters (atr, etc.)

        Returns:
            tuple: (tp_price, sl_price)
        """
        pass

    def get_config(self) -> Dict:
        """Return strategy configuration."""
        return self.CONFIG

    def update_config(self, new_config: Dict) -> None:
        """Update strategy configuration."""
        self.CONFIG.update(new_config)
        logger.info(f"Updated config for {self.get_name()}: {new_config}")

    def validate_config(self) -> bool:
        """Validate strategy configuration. Override in subclasses if needed."""
        required_keys = ["pair", "interval", "leverage", "quantity", "tp_pct", "sl_pct"]
        for key in required_keys:
            if key not in self.CONFIG:
                logger.error(f"Missing required config key: {key}")
                return False
        return True