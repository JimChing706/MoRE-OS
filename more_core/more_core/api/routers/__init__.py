"""API Router package — modular FastAPI routers for MoRE OS."""

from .health import create_router as create_health_router
from .tasks import create_router as create_tasks_router
from .llm import create_router as create_llm_router
from .zen import create_router as create_zen_router
from .requirements import create_router as create_requirements_router
from .hands import create_router as create_hands_router
from .channels import create_router as create_channels_router
from .cron import create_router as create_cron_router
from .skills import create_router as create_skills_router
from .commands import create_router as create_commands_router
from .security import create_router as create_security_router
from .hotreload import create_router as create_hotreload_router
from .monitor import create_router as create_monitor_router
from .workflows import create_router as create_workflows_router
from .deployments import create_router as create_deployments_router
from .sessions import create_router as create_sessions_router
from .outputs import create_router as create_outputs_router
from .mcp import create_router as create_mcp_router
from .a2a import create_router as create_a2a_router
from .import_task import create_router as create_import_task_router
from .deliberate import create_router as create_deliberate_router
from .admin_api_key import create_router as create_admin_api_key_router
from .delivery import create_router as create_delivery_router

__all__ = [
    "create_health_router",
    "create_tasks_router",
    "create_llm_router",
    "create_zen_router",
    "create_requirements_router",
    "create_hands_router",
    "create_channels_router",
    "create_cron_router",
    "create_skills_router",
    "create_commands_router",
    "create_security_router",
    "create_hotreload_router",
    "create_monitor_router",
    "create_workflows_router",
    "create_deployments_router",
    "create_sessions_router",
    "create_outputs_router",
    "create_mcp_router",
    "create_a2a_router",
    "create_import_task_router",
    "create_deliberate_router",
    "create_admin_api_key_router",
    "create_delivery_router",
]
