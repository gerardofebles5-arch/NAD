"""
Limits Checker for PINAD SaaS
Verifies that tenants stay within their plan limits.
"""

from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from .plans import PlanManager, PlanTier


class LimitsChecker:
    """Checks and enforces plan limits for tenants."""
    
    def __init__(self, plan_manager: Optional[PlanManager] = None):
        self.plan_manager = plan_manager or PlanManager()
    
    def get_tenant_limits(self, tenant_id: str, plan_id: str) -> Dict:
        """Get limits for a specific tenant based on their plan."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return {}
        
        return {
            "tenant_id": tenant_id,
            "plan_id": plan_id,
            "limits": limits,
        }
    
    def check_scan_limit(self, tenant_id: str, plan_id: str, current_month_scans: int) -> Tuple[bool, Dict]:
        """Check if tenant can perform more scans this month."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return False, {"error": "Invalid plan"}
        
        max_scans = limits["scans_per_month"]
        
        # -1 means unlimited
        if max_scans == -1:
            return True, {
                "allowed": True,
                "remaining": "unlimited",
                "limit": "unlimited",
            }
        
        remaining = max_scans - current_month_scans
        allowed = remaining > 0
        
        return allowed, {
            "allowed": allowed,
            "current": current_month_scans,
            "limit": max_scans,
            "remaining": max(0, remaining),
        }
    
    def check_storage_limit(self, tenant_id: str, plan_id: str, current_storage_mb: float) -> Tuple[bool, Dict]:
        """Check if tenant is within storage limits."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return False, {"error": "Invalid plan"}
        
        max_storage = limits["storage_mb"]
        
        # -1 means unlimited
        if max_storage == -1:
            return True, {
                "allowed": True,
                "remaining": "unlimited",
                "limit": "unlimited",
            }
        
        remaining = max_storage - current_storage_mb
        allowed = remaining >= 0
        
        return allowed, {
            "allowed": allowed,
            "current_mb": round(current_storage_mb, 2),
            "limit_mb": max_storage,
            "remaining_mb": round(max(0, remaining), 2),
        }
    
    def check_user_limit(self, tenant_id: str, plan_id: str, current_users: int) -> Tuple[bool, Dict]:
        """Check if tenant can add more users."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return False, {"error": "Invalid plan"}
        
        max_users = limits["max_users"]
        
        # -1 means unlimited
        if max_users == -1:
            return True, {
                "allowed": True,
                "remaining": "unlimited",
                "limit": "unlimited",
            }
        
        remaining = max_users - current_users
        allowed = remaining > 0
        
        return allowed, {
            "allowed": allowed,
            "current": current_users,
            "limit": max_users,
            "remaining": max(0, remaining),
        }
    
    def check_ocr_limit(self, tenant_id: str, plan_id: str, current_month_ocr_pages: int) -> Tuple[bool, Dict]:
        """Check if tenant can perform more OCR pages this month."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return False, {"error": "Invalid plan"}
        
        max_ocr = limits["ocr_pages_per_month"]
        
        # -1 means unlimited
        if max_ocr == -1:
            return True, {
                "allowed": True,
                "remaining": "unlimited",
                "limit": "unlimited",
            }
        
        remaining = max_ocr - current_month_ocr_pages
        allowed = remaining > 0
        
        return allowed, {
            "allowed": allowed,
            "current": current_month_ocr_pages,
            "limit": max_ocr,
            "remaining": max(0, remaining),
        }
    
    def check_api_limit(self, tenant_id: str, plan_id: str, current_month_api_calls: int) -> Tuple[bool, Dict]:
        """Check if tenant can make more API calls this month."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return False, {"error": "Invalid plan"}
        
        max_api = limits["api_calls_per_month"]
        
        # -1 means unlimited
        if max_api == -1:
            return True, {
                "allowed": True,
                "remaining": "unlimited",
                "limit": "unlimited",
            }
        
        remaining = max_api - current_month_api_calls
        allowed = remaining > 0
        
        return allowed, {
            "allowed": allowed,
            "current": current_month_api_calls,
            "limit": max_api,
            "remaining": max(0, remaining),
        }
    
    def check_feature_access(self, tenant_id: str, plan_id: str, feature: str) -> Tuple[bool, Dict]:
        """Check if tenant has access to a specific feature."""
        has_access = self.plan_manager.check_feature_access(plan_id, feature)
        
        return has_access, {
            "allowed": has_access,
            "feature": feature,
            "plan_id": plan_id,
        }
    
    def get_all_limits_status(self, tenant_id: str, plan_id: str, usage_data: Dict) -> Dict:
        """Get comprehensive status of all limits for a tenant."""
        limits = self.plan_manager.get_plan_limits(plan_id)
        if not limits:
            return {"error": "Invalid plan"}
        
        status = {
            "tenant_id": tenant_id,
            "plan_id": plan_id,
            "limits": {},
        }
        
        # Check each limit
        scan_allowed, scan_status = self.check_scan_limit(
            tenant_id, plan_id, usage_data.get("scans_this_month", 0)
        )
        status["limits"]["scans"] = scan_status
        
        storage_allowed, storage_status = self.check_storage_limit(
            tenant_id, plan_id, usage_data.get("storage_used_mb", 0)
        )
        status["limits"]["storage"] = storage_status
        
        user_allowed, user_status = self.check_user_limit(
            tenant_id, plan_id, usage_data.get("user_count", 0)
        )
        status["limits"]["users"] = user_status
        
        ocr_allowed, ocr_status = self.check_ocr_limit(
            tenant_id, plan_id, usage_data.get("ocr_pages_this_month", 0)
        )
        status["limits"]["ocr"] = ocr_status
        
        api_allowed, api_status = self.check_api_limit(
            tenant_id, plan_id, usage_data.get("api_calls_this_month", 0)
        )
        status["limits"]["api"] = api_status
        
        # Overall status
        status["overall_allowed"] = all([
            scan_allowed,
            storage_allowed,
            user_allowed,
            ocr_allowed,
            api_allowed,
        ])
        
        return status
    
    def get_usage_percentage(self, current: int, limit: int) -> float:
        """Calculate usage percentage (0-100)."""
        if limit == -1:  # unlimited
            return 0.0
        if limit == 0:
            return 100.0
        return min(100.0, (current / limit) * 100)
    
    def get_limit_warnings(self, status: Dict) -> list:
        """Get warnings for limits that are near their maximum."""
        warnings = []
        
        for limit_name, limit_status in status.get("limits", {}).items():
            if not isinstance(limit_status, dict):
                continue
            
            current = limit_status.get("current", 0)
            limit = limit_status.get("limit", 0)
            
            if limit == -1:  # unlimited
                continue
            
            percentage = self.get_usage_percentage(current, limit)
            
            if percentage >= 90:
                warnings.append({
                    "limit": limit_name,
                    "severity": "critical",
                    "percentage": percentage,
                    "message": f"{limit_name} está al {percentage:.1f}% de su límite",
                })
            elif percentage >= 75:
                warnings.append({
                    "limit": limit_name,
                    "severity": "warning",
                    "percentage": percentage,
                    "message": f"{limit_name} está al {percentage:.1f}% de su límite",
                })
        
        return warnings


# Singleton instance
limits_checker = LimitsChecker()
