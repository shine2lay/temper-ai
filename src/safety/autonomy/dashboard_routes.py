"""FastAPI routes for autonomy dashboard."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from src.safety.autonomy.dashboard_service import AutonomyDataService

HTTP_404 = 404


class EmergencyStopRequest(BaseModel):
    """Request body for emergency stop activation."""
    reason: str
    triggered_by: str = "dashboard"


class ResumeRequest(BaseModel):
    """Request body for emergency stop deactivation."""
    reason: str


class EscalateRequest(BaseModel):
    """Request body for manual escalation."""
    agent_name: str
    domain: str = "general"
    level: Optional[int] = None
    reason: str = "manual dashboard escalation"


class DeescalateRequest(BaseModel):
    """Request body for manual de-escalation."""
    agent_name: str
    domain: str = "general"
    reason: str = "manual dashboard de-escalation"


def create_autonomy_router(service: AutonomyDataService) -> APIRouter:
    """Create autonomy API router."""
    router = APIRouter(prefix="/autonomy", tags=["autonomy"])
    _register_get_routes(router, service)
    _register_post_routes(router, service)
    return router


def _register_get_routes(router: APIRouter, service: AutonomyDataService) -> None:
    """Register GET endpoints on the router."""

    @router.get("/status")
    def get_status() -> Dict[str, Any]:
        """Get autonomy status summary."""
        return service.get_status_summary()

    @router.get("/transitions")
    def get_transitions(
        agent_name: Optional[str] = None, limit: int = 50  # scanner: skip-magic
    ) -> List[Dict[str, Any]]:
        """Get recent autonomy transitions."""
        return service.get_transitions(agent_name=agent_name, limit=limit)

    @router.get("/budget")
    def get_budget() -> List[Dict[str, Any]]:
        """Get budget overview."""
        return service.get_budget_overview()

    @router.get("/emergency")
    def get_emergency() -> Dict[str, Any]:
        """Get emergency stop status."""
        return service.get_emergency_status()


def _register_post_routes(router: APIRouter, service: AutonomyDataService) -> None:
    """Register POST endpoints on the router."""
    _register_emergency_routes(router, service)
    _register_transition_routes(router, service)


def _register_emergency_routes(router: APIRouter, service: AutonomyDataService) -> None:
    """Register emergency stop POST routes."""

    @router.post("/emergency-stop")
    def activate_emergency_stop(req: EmergencyStopRequest) -> Dict[str, Any]:
        """Activate emergency stop."""
        from src.safety.autonomy.emergency_stop import EmergencyStopController

        controller = EmergencyStopController(store=service.store)
        event = controller.activate(triggered_by=req.triggered_by, reason=req.reason)
        return {"id": event.id, "status": "activated", "reason": req.reason}

    @router.post("/resume")
    def deactivate_emergency_stop(req: ResumeRequest) -> Dict[str, Any]:
        """Deactivate emergency stop."""
        from src.safety.autonomy.emergency_stop import EmergencyStopController

        controller = EmergencyStopController(store=service.store)
        controller.deactivate(resolution_reason=req.reason)
        return {"status": "deactivated", "reason": req.reason}


def _register_transition_routes(router: APIRouter, service: AutonomyDataService) -> None:
    """Register escalation/de-escalation POST routes."""

    @router.post("/escalate")
    def escalate_agent(req: EscalateRequest) -> Dict[str, Any]:
        """Manually escalate an agent."""
        from src.safety.autonomy.manager import AutonomyManager
        from src.safety.autonomy.schemas import AutonomyLevel

        manager = AutonomyManager(
            store=service.store, max_level=AutonomyLevel.STRATEGIC,
        )
        target = AutonomyLevel(req.level) if req.level is not None else None
        transition = manager.escalate(
            req.agent_name, req.domain,
            reason=req.reason, target_level=target,
        )
        if transition is None:
            return {"status": "no_change", "reason": "Cooldown, max level, or already at level"}
        return {
            "status": "escalated",
            "from_level": transition.from_level,
            "to_level": transition.to_level,
        }

    @router.post("/deescalate")
    def deescalate_agent(req: DeescalateRequest) -> Dict[str, Any]:
        """Manually de-escalate an agent."""
        from src.safety.autonomy.manager import AutonomyManager
        from src.safety.autonomy.schemas import AutonomyLevel

        manager = AutonomyManager(
            store=service.store, max_level=AutonomyLevel.STRATEGIC,
        )
        transition = manager.de_escalate(req.agent_name, req.domain, reason=req.reason)
        if transition is None:
            return {"status": "no_change", "reason": "Already at SUPERVISED or cooldown"}
        return {
            "status": "deescalated",
            "from_level": transition.from_level,
            "to_level": transition.to_level,
        }
