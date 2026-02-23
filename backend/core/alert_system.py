"""
Alert System Module for Options Trading
Monitors price, OI, PCR, and other metrics for threshold breaches
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of alerts."""
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PRICE_CHANGE_PCT = "price_change_pct"
    OI_CHANGE_PCT = "oi_change_pct"
    PCR_ABOVE = "pcr_above"
    PCR_BELOW = "pcr_below"
    IV_RANK_ABOVE = "iv_rank_above"
    IV_RANK_BELOW = "iv_rank_below"
    VOLUME_SPIKE = "volume_spike"
    OI_BUILDUP = "oi_buildup"
    GREEKS_THRESHOLD = "greeks_threshold"


class AlertStatus(Enum):
    """Alert status."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    PAUSED = "paused"
    EXPIRED = "expired"


@dataclass
class Alert:
    """Alert configuration."""
    id: str
    name: str
    alert_type: AlertType
    underlying: str
    condition: Dict[str, Any]
    message_template: str
    status: AlertStatus = AlertStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    triggered_at: Optional[str] = None
    trigger_count: int = 0
    cooldown_minutes: int = 15
    last_triggered: Optional[str] = None
    notification_channels: List[str] = field(default_factory=lambda: ['websocket'])

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'alert_type': self.alert_type.value,
            'underlying': self.underlying,
            'condition': self.condition,
            'message_template': self.message_template,
            'status': self.status.value,
            'created_at': self.created_at,
            'triggered_at': self.triggered_at,
            'trigger_count': self.trigger_count,
            'cooldown_minutes': self.cooldown_minutes,
            'notification_channels': self.notification_channels
        }


class AlertSystem:
    """
    Real-time alert system for options trading.

    Features:
    - Price alerts (above/below thresholds)
    - OI change alerts
    - PCR alerts
    - IV rank alerts
    - Volume spike alerts
    - OI buildup pattern alerts
    - Greeks threshold alerts
    """

    def __init__(self):
        self.alerts: Dict[str, Alert] = {}
        self.callbacks: List[Callable] = []
        self.running = False
        self._task = None

    def register_callback(self, callback: Callable):
        """Register a callback for alert notifications."""
        self.callbacks.append(callback)

    def unregister_callback(self, callback: Callable):
        """Unregister a callback."""
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def create_alert(
        self,
        name: str,
        alert_type: AlertType,
        underlying: str,
        condition: Dict[str, Any],
        message_template: Optional[str] = None,
        cooldown_minutes: int = 15,
        notification_channels: Optional[List[str]] = None
    ) -> Alert:
        """
        Create a new alert.

        Args:
            name: Alert name
            alert_type: Type of alert
            underlying: Underlying symbol to monitor
            condition: Alert condition parameters
            message_template: Custom message template
            cooldown_minutes: Minimum time between triggers
            notification_channels: List of notification channels

        Returns:
            Created Alert object
        """
        alert_id = f"{underlying}_{alert_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        if message_template is None:
            message_template = self._get_default_message_template(alert_type)

        alert = Alert(
            id=alert_id,
            name=name,
            alert_type=alert_type,
            underlying=underlying,
            condition=condition,
            message_template=message_template,
            cooldown_minutes=cooldown_minutes,
            notification_channels=notification_channels or ['websocket']
        )

        self.alerts[alert_id] = alert
        logger.info(f"Created alert: {alert_id}")

        return alert

    def delete_alert(self, alert_id: str) -> bool:
        """Delete an alert by ID."""
        if alert_id in self.alerts:
            del self.alerts[alert_id]
            logger.info(f"Deleted alert: {alert_id}")
            return True
        return False

    def pause_alert(self, alert_id: str) -> bool:
        """Pause an alert."""
        if alert_id in self.alerts:
            self.alerts[alert_id].status = AlertStatus.PAUSED
            return True
        return False

    def resume_alert(self, alert_id: str) -> bool:
        """Resume a paused alert."""
        if alert_id in self.alerts:
            self.alerts[alert_id].status = AlertStatus.ACTIVE
            return True
        return False

    def check_alerts(
        self,
        underlying: str,
        data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Check all alerts for a given underlying against current data.

        Args:
            underlying: Underlying symbol
            data: Current market data

        Returns:
            List of triggered alerts
        """
        triggered = []

        for alert in self.alerts.values():
            if alert.underlying != underlying:
                continue

            if alert.status != AlertStatus.ACTIVE:
                continue

            # Check cooldown
            if alert.last_triggered:
                last = datetime.fromisoformat(alert.last_triggered)
                elapsed = (datetime.now() - last).total_seconds() / 60
                if elapsed < alert.cooldown_minutes:
                    continue

            # Check condition
            if self._evaluate_condition(alert.alert_type, alert.condition, data):
                alert.trigger_count += 1
                alert.last_triggered = datetime.now().isoformat()
                alert.triggered_at = alert.last_triggered

                message = self._format_message(alert, data)

                trigger_data = {
                    'alert': alert.to_dict(),
                    'message': message,
                    'data': data,
                    'triggered_at': alert.triggered_at
                }

                triggered.append(trigger_data)

                # Notify callbacks
                for callback in self.callbacks:
                    try:
                        callback(trigger_data)
                    except Exception as e:
                        logger.error(f"Error in alert callback: {e}")

        return triggered

    def _evaluate_condition(
        self,
        alert_type: AlertType,
        condition: Dict[str, Any],
        data: Dict[str, Any]
    ) -> bool:
        """Evaluate if alert condition is met."""
        try:
            if alert_type == AlertType.PRICE_ABOVE:
                value = data.get('price', 0)
                threshold = condition.get('threshold', 0)
                return value > threshold

            elif alert_type == AlertType.PRICE_BELOW:
                value = data.get('price', 0)
                threshold = condition.get('threshold', 0)
                return value < threshold

            elif alert_type == AlertType.PRICE_CHANGE_PCT:
                value = data.get('price_change_pct', 0)
                threshold = condition.get('threshold', 0)
                direction = condition.get('direction', 'above')
                if direction == 'above':
                    return value > threshold
                else:
                    return value < -threshold

            elif alert_type == AlertType.OI_CHANGE_PCT:
                value = data.get('oi_change_pct', 0)
                threshold = condition.get('threshold', 0)
                return abs(value) > threshold

            elif alert_type == AlertType.PCR_ABOVE:
                value = data.get('pcr', 0)
                threshold = condition.get('threshold', 0)
                return value > threshold

            elif alert_type == AlertType.PCR_BELOW:
                value = data.get('pcr', 0)
                threshold = condition.get('threshold', 0)
                return value < threshold

            elif alert_type == AlertType.IV_RANK_ABOVE:
                value = data.get('iv_rank', 0)
                threshold = condition.get('threshold', 0)
                return value > threshold

            elif alert_type == AlertType.IV_RANK_BELOW:
                value = data.get('iv_rank', 0)
                threshold = condition.get('threshold', 0)
                return value < threshold

            elif alert_type == AlertType.VOLUME_SPIKE:
                volume = data.get('volume', 0)
                avg_volume = data.get('avg_volume', 1)
                threshold = condition.get('threshold', 2.0)
                return volume > (avg_volume * threshold)

            elif alert_type == AlertType.OI_BUILDUP:
                pattern = condition.get('pattern', '')
                data_pattern = data.get('oi_buildup_pattern', '')
                return pattern.lower() in data_pattern.lower()

            elif alert_type == AlertType.GREEKS_THRESHOLD:
                greek = condition.get('greek', 'delta')
                threshold = condition.get('threshold', 0)
                value = data.get(f'net_{greek}', 0)
                direction = condition.get('direction', 'above')
                if direction == 'above':
                    return value > threshold
                else:
                    return value < threshold

            return False

        except Exception as e:
            logger.error(f"Error evaluating condition: {e}")
            return False

    def _format_message(self, alert: Alert, data: Dict[str, Any]) -> str:
        """Format alert message with data."""
        message = alert.message_template

        # Replace placeholders
        for key, value in data.items():
            placeholder = f"{{{key}}}"
            if placeholder in message:
                message = message.replace(placeholder, str(value))

        # Add underlying
        message = message.replace("{underlying}", alert.underlying)

        return message

    def _get_default_message_template(self, alert_type: AlertType) -> str:
        """Get default message template for alert type."""
        templates = {
            AlertType.PRICE_ABOVE: "🚀 {underlying} price {price} crossed above {threshold}",
            AlertType.PRICE_BELOW: "🔻 {underlying} price {price} dropped below {threshold}",
            AlertType.PRICE_CHANGE_PCT: "📊 {underlying} price changed {price_change_pct}%",
            AlertType.OI_CHANGE_PCT: "📈 {underlying} OI changed {oi_change_pct}%",
            AlertType.PCR_ABOVE: "🎯 {underlying} PCR {pcr} crossed above {threshold}",
            AlertType.PCR_BELOW: "🎯 {underlying} PCR {pcr} dropped below {threshold}",
            AlertType.IV_RANK_ABOVE: "⚡ {underlying} IV Rank {iv_rank} is elevated",
            AlertType.IV_RANK_BELOW: "💤 {underlying} IV Rank {iv_rank} is depressed",
            AlertType.VOLUME_SPIKE: "🔥 {underlying} volume spike detected: {volume}",
            AlertType.OI_BUILDUP: "📊 {underlying} OI Buildup: {oi_buildup_pattern}",
            AlertType.GREEKS_THRESHOLD: "📐 {underlying} {greek} threshold crossed: {value}"
        }

        return templates.get(alert_type, "Alert triggered for {underlying}")

    def get_alerts(
        self,
        underlying: Optional[str] = None,
        status: Optional[AlertStatus] = None
    ) -> List[Dict[str, Any]]:
        """Get alerts with optional filtering."""
        result = []

        for alert in self.alerts.values():
            if underlying and alert.underlying != underlying:
                continue
            if status and alert.status != status:
                continue
            result.append(alert.to_dict())

        return result

    def create_preset_alerts(self, underlying: str) -> List[Alert]:
        """Create preset alerts for an underlying."""
        presets = []

        # PCR alert - extreme values
        presets.append(self.create_alert(
            name=f"{underlying} PCR High",
            alert_type=AlertType.PCR_ABOVE,
            underlying=underlying,
            condition={'threshold': 1.5},
            message_template=f"🐻 {{underlying}} PCR {{pcr}} - Extreme bearish sentiment detected"
        ))

        presets.append(self.create_alert(
            name=f"{underlying} PCR Low",
            alert_type=AlertType.PCR_BELOW,
            underlying=underlying,
            condition={'threshold': 0.5},
            message_template=f"🐂 {{underlying}} PCR {{pcr}} - Extreme bullish sentiment detected"
        ))

        # OI Change alert
        presets.append(self.create_alert(
            name=f"{underlying} OI Spike",
            alert_type=AlertType.OI_CHANGE_PCT,
            underlying=underlying,
            condition={'threshold': 10},
            message_template=f"📊 {{underlying}} significant OI change: {{oi_change_pct}}%"
        ))

        # IV Rank alerts
        presets.append(self.create_alert(
            name=f"{underlying} IV High",
            alert_type=AlertType.IV_RANK_ABOVE,
            underlying=underlying,
            condition={'threshold': 70},
            message_template=f"⚡ {{underlying}} IV Rank {{iv_rank}} - Good for selling options"
        ))

        presets.append(self.create_alert(
            name=f"{underlying} IV Low",
            alert_type=AlertType.IV_RANK_BELOW,
            underlying=underlying,
            condition={'threshold': 30},
            message_template=f"💤 {{underlying}} IV Rank {{iv_rank}} - Good for buying options"
        ))

        return presets

    async def start_monitoring(self, interval_seconds: int = 5):
        """Start continuous alert monitoring."""
        self.running = True

        while self.running:
            # This would be called with real data in production
            await asyncio.sleep(interval_seconds)

    def stop_monitoring(self):
        """Stop alert monitoring."""
        self.running = False


# Global instance
alert_system = AlertSystem()
