"""Security module — Defense in Depth for QNMing MoRE OS.

Reference: OpenFang's 16 security systems. We implement a layered
security architecture with independently testable components.

Security Layers:
 1. API Authentication (Bearer token)
 2. RBAC — Role-Based Access Control
 3. Input Sanitization & Validation
 4. Path Traversal Protection (file tools)
 5. Command Injection Prevention (shell tools)
 6. Sandbox Isolation (subprocess + cgroup)
 7. Rate Limiting (token bucket)
 8. Circuit Breaker (fault isolation)
 9. Secret Redaction (config injection)
10. Audit Logging (JSONL trail)
11. Policy Enforcement (governance)
12. ZEN Rules (behavioral constraints)
13. Incident Response (auto-escalation)
14. Taint Tracking (data provenance)
15. Request Signing (HMAC integrity)
16. Output Filtering (PII/sensitive data)
"""

from .rbac import (
    UnifiedRBAC,
    RBACManager,
    Role,
    Permission,
    require_permission,
    requires_permission,
    set_rbac_instance,
)
from .taint import TaintTracker, TaintLabel
from .signing import RequestSigner
from .output_filter import OutputFilter
from .api_key_ops import (
    generate_api_key,
    validate_api_key_report,
    inject_api_key_into_env,
    sign_rotation_proof,
    verify_rotation_proof,
    APIKeyReport,
)

__all__ = [
    "UnifiedRBAC",
    "RBACManager",
    "Role",
    "Permission",
    "require_permission",
    "requires_permission",
    "set_rbac_instance",
    "TaintTracker",
    "TaintLabel",
    "RequestSigner",
    "OutputFilter",
    "generate_api_key",
    "validate_api_key_report",
    "inject_api_key_into_env",
    "sign_rotation_proof",
    "verify_rotation_proof",
    "APIKeyReport",
]
