"""
Plan Prorating Module for PINAD SaaS
Calculates proportional adjustments for plan changes.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from decimal import Decimal


class ProratingCalculator:
    """Calculates prorated amounts for plan changes."""
    
    def __init__(self):
        pass
    
    def calculate_prorated_amount(
        self,
        original_amount: float,
        original_period_days: int,
        days_used: int,
        new_period_days: Optional[int] = None
    ) -> float:
        """
        Calculate prorated amount based on usage.
        
        Args:
            original_amount: Original plan price
            original_period_days: Original billing period in days
            days_used: Days already used in current period
            new_period_days: New billing period (if changing period)
        
        Returns:
            Prorated amount
        """
        # Calculate remaining days
        remaining_days = original_period_days - days_used
        
        # Calculate daily rate
        daily_rate = original_amount / original_period_days
        
        # Calculate credit for unused days
        credit = daily_rate * remaining_days
        
        return float(credit)
    
    def calculate_upgrade_cost(
        self,
        current_plan_price: float,
        new_plan_price: float,
        days_remaining: int,
        billing_period_days: int = 30
    ) -> Dict[str, Any]:
        """
        Calculate cost for plan upgrade.
        
        Args:
            current_plan_price: Current plan price
            new_plan_price: New plan price
            days_remaining: Days remaining in current period
            billing_period_days: Total billing period
        
        Returns:
            Upgrade cost breakdown
        """
        # Calculate daily rates
        current_daily_rate = current_plan_price / billing_period_days
        new_daily_rate = new_plan_price / billing_period_days
        
        # Calculate credit for remaining days on current plan
        credit = current_daily_rate * days_remaining
        
        # Calculate cost for remaining days on new plan
        cost = new_daily_rate * days_remaining
        
        # Net amount to pay
        net_amount = cost - credit
        
        return {
            'credit_amount': float(credit),
            'new_cost': float(cost),
            'net_amount': float(max(0, net_amount)),
            'days_remaining': days_remaining
        }
    
    def calculate_downgrade_credit(
        self,
        current_plan_price: float,
        new_plan_price: float,
        days_remaining: int,
        billing_period_days: int = 30
    ) -> Dict[str, Any]:
        """
        Calculate credit for plan downgrade.
        
        Args:
            current_plan_price: Current plan price
            new_plan_price: New plan price
            days_remaining: Days remaining in current period
            billing_period_days: Total billing period
        
        Returns:
            Downgrade credit breakdown
        """
        # Calculate daily rates
        current_daily_rate = current_plan_price / billing_period_days
        new_daily_rate = new_plan_price / billing_period_days
        
        # Calculate credit for remaining days
        credit = (current_daily_rate - new_daily_rate) * days_remaining
        
        return {
            'credit_amount': float(max(0, credit)),
            'days_remaining': days_remaining
        }
    
    def calculate_mid_cycle_change(
        self,
        current_plan: Dict[str, Any],
        new_plan: Dict[str, Any],
        subscription_start: str,
        subscription_end: str,
        current_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate adjustments for mid-cycle plan change.
        
        Args:
            current_plan: Current plan details
            new_plan: New plan details
            subscription_start: Subscription start date (ISO)
            subscription_end: Subscription end date (ISO)
            current_date: Current date (ISO, defaults to now)
        
        Returns:
            Prorating calculation results
        """
        if not current_date:
            current_date = datetime.now().isoformat()
        
        start_dt = datetime.fromisoformat(subscription_start)
        end_dt = datetime.fromisoformat(subscription_end)
        current_dt = datetime.fromisoformat(current_date)
        
        # Calculate total period and days used
        total_period = (end_dt - start_dt).days
        days_used = (current_dt - start_dt).days
        days_remaining = total_period - days_used
        
        current_price = current_plan.get('price_usd', 0)
        new_price = new_plan.get('price_usd', 0)
        
        # Determine if upgrade or downgrade
        if new_price > current_price:
            return self.calculate_upgrade_cost(
                current_price, new_price, days_remaining, total_period
            )
        else:
            return self.calculate_downgrade_credit(
                current_price, new_price, days_remaining, total_period
            )
