"""
Plan Manager for PINAD SaaS
Defines subscription plans (Free, Pro, Enterprise) and manages plan logic.
"""

from enum import Enum
from typing import Dict, Optional
from datetime import datetime
import json


class PlanTier(str, Enum):
    """Plan tiers available in the system."""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# Plan definitions with limits and pricing
PLAN_DEFINITIONS: Dict[PlanTier, Dict] = {
    PlanTier.FREE: {
        "id": "free",
        "name": "Plan Gratuito",
        "description": "Perfecto para empezar y probar el sistema",
        "price_usd": 0,
        "currency": "USD",
        "billing_interval": "monthly",
        "limits": {
            "scans_per_month": 50,
            "max_users": 1,
            "storage_mb": 100,
            "max_documents_per_scan": 5,
            "ocr_pages_per_month": 10,
            "api_calls_per_month": 100,
            "advanced_features": False,
            "priority_support": False,
            "custom_branding": False,
            "webhook_access": False,
        },
        "features": [
            "Escaneo básico de documentos",
            "OCR estándar",
            "Almacenamiento en la nube (100MB)",
            "1 usuario",
            "Soporte por email",
        ],
    },
    PlanTier.PRO: {
        "id": "pro",
        "name": "Plan Profesional",
        "description": "Ideal para equipos pequeños y medianas empresas",
        "price_usd": 10,
        "currency": "USD",
        "billing_interval": "monthly",
        "limits": {
            "scans_per_month": 500,
            "max_users": 5,
            "storage_mb": 5120,  # 5GB
            "max_documents_per_scan": 20,
            "ocr_pages_per_month": 100,
            "api_calls_per_month": 1000,
            "advanced_features": True,
            "priority_support": True,
            "custom_branding": False,
            "webhook_access": True,
        },
        "features": [
            "Todo del plan Free",
            "Escaneo avanzado con IA",
            "OCR premium",
            "5GB de almacenamiento",
            "5 usuarios",
            "API access",
            "Webhooks",
            "Soporte prioritario",
            "Reportes avanzados",
        ],
    },
    PlanTier.ENTERPRISE: {
        "id": "enterprise",
        "name": "Plan Empresarial",
        "description": "Para grandes organizaciones con necesidades personalizadas",
        "price_usd": 50,
        "currency": "USD",
        "billing_interval": "monthly",
        "limits": {
            "scans_per_month": -1,  # -1 means unlimited
            "max_users": 20,
            "storage_mb": 51200,  # 50GB
            "max_documents_per_scan": -1,  # unlimited
            "ocr_pages_per_month": -1,  # unlimited
            "api_calls_per_month": -1,  # unlimited
            "advanced_features": True,
            "priority_support": True,
            "custom_branding": True,
            "webhook_access": True,
        },
        "features": [
            "Todo del plan Pro",
            "Escaneos ilimitados",
            "50GB de almacenamiento",
            "20 usuarios",
            "API ilimitada",
            "Branding personalizado",
            "SLA garantizado",
            "Soporte dedicado 24/7",
            "Integraciones personalizadas",
            "Entrenamiento on-site",
        ],
    },
}


class PlanManager:
    """Manages subscription plans and plan-related operations."""
    
    def __init__(self):
        self.plans = PLAN_DEFINITIONS
    
    def get_plan(self, plan_id: str) -> Optional[Dict]:
        """Get plan definition by ID."""
        try:
            tier = PlanTier(plan_id)
            return self.plans[tier]
        except ValueError:
            return None
    
    def get_all_plans(self) -> Dict[str, Dict]:
        """Get all available plans."""
        return {tier.value: plan for tier, plan in self.plans.items()}
    
    def get_plan_limits(self, plan_id: str) -> Optional[Dict]:
        """Get limits for a specific plan."""
        plan = self.get_plan(plan_id)
        return plan["limits"] if plan else None
    
    def check_feature_access(self, plan_id: str, feature: str) -> bool:
        """Check if a plan has access to a specific feature."""
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        
        limits = plan["limits"]
        return limits.get(feature, False)
    
    def calculate_upgrade_cost(self, current_plan_id: str, new_plan_id: str) -> Dict:
        """Calculate prorated cost for upgrading plans."""
        current_plan = self.get_plan(current_plan_id)
        new_plan = self.get_plan(new_plan_id)
        
        if not current_plan or not new_plan:
            return {"error": "Invalid plan IDs"}
        
        current_price = current_plan["price_usd"]
        new_price = new_plan["price_usd"]
        
        if new_price <= current_price:
            return {"error": "New plan must be more expensive"}
        
        # Simple calculation (in production, use proration based on billing cycle)
        price_difference = new_price - current_price
        
        return {
            "current_plan": current_plan_id,
            "new_plan": new_plan_id,
            "current_price": current_price,
            "new_price": new_price,
            "price_difference": price_difference,
            "currency": "USD",
        }
    
    def validate_plan_transition(self, current_plan_id: str, new_plan_id: str) -> Dict:
        """Validate if a plan transition is allowed."""
        current_plan = self.get_plan(current_plan_id)
        new_plan = self.get_plan(new_plan_id)
        
        if not current_plan or not new_plan:
            return {"valid": False, "reason": "Invalid plan IDs"}
        
        # Allow any transition for now
        # In production, you might want to restrict certain transitions
        return {
            "valid": True,
            "current_plan": current_plan_id,
            "new_plan": new_plan_id,
            "is_upgrade": new_plan["price_usd"] > current_plan["price_usd"],
            "is_downgrade": new_plan["price_usd"] < current_plan["price_usd"],
        }
    
    def get_plan_comparison(self) -> Dict:
        """Get comparison matrix of all plans."""
        comparison = {
            "plans": [],
            "features": set(),
        }
        
        # Collect all features across all plans
        for tier, plan in self.plans.items():
            for feature in plan["features"]:
                comparison["features"].add(feature)
        
        comparison["features"] = sorted(list(comparison["features"]))
        
        # Build comparison matrix
        for tier, plan in self.plans.items():
            plan_features = set(plan["features"])
            plan_data = {
                "id": plan["id"],
                "name": plan["name"],
                "price": plan["price_usd"],
                "features": {
                    feature: feature in plan_features
                    for feature in comparison["features"]
                },
            }
            comparison["plans"].append(plan_data)
        
        return comparison


# Singleton instance
plan_manager = PlanManager()
