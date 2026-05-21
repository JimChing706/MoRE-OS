# Changelog

All notable changes to MoRE OS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - 2026-05-06

### Added
- **Core Architecture**
  - L2 DGM evolution engine with LLM-based variant generation
  - L5 metacognition self-modification with LLM proposals
  - L4 task decomposition using LLM
  - 15 built-in tools (expanded from 5)
  - Request cache with LRU + TTL
  - Rate limiter (token bucket)
  - Circuit breaker for fault tolerance
  - Performance metrics collector

- **Security**
  - ZEN_RULES - 15 highest guiding principles
  - Incident response system with quarantine
  - Unauthorized access blocking
  - RBAC with 5 roles and 18 permissions

- **API Endpoints**
  - `/api/v1/llm/state` - LLM state management
  - `/api/v1/llm/state/update` - Dynamic parameter adjustment
  - `/api/v1/llm/usage` - Usage statistics
  - `/api/v1/llm/providers` - Provider information
  - `/api/v1/zen/rules` - ZEN rules list
  - `/api/v1/zen/compliance` - Compliance report
  - `/api/v1/zen/violations` - Violation tracking

- **Documentation**
  - ARCHITECTURE_ANALYSIS.md
  - CODE_QUALITY_REPORT.md
  - EVOLUTION_ASSESSMENT.md
  - ECONOMIC_ASSESSMENT.md
  - PRICING_MODEL_ASSESSMENT.md
  - LLM_STATE_API.md
  - ZEN_RULES.md
  - SYSTEM_AUDIT_REPORT.md

### Changed
- Default LLM provider changed to LM Studio
- Enhanced L0 execution layer with tool call parsing
- Improved L3 symbolic layer with rule engine
- Optimized LLM manager with better caching

### Fixed
- Empty exception handlers replaced with specific exception types
- Path traversal protection in HyperAgent
- TelegramAdapter platform_name implementation

---

## [0.2.0] - 2026-04-01

### Added
- Six-layer architecture (L0-L5)
- Multi-provider LLM support (Ollama, DeepSeek, OpenAI, Anthropic)
- Message channels (Telegram, Discord, Slack, Webhook, WeChat, QQ)
- Skills system (WebSearch, CodeExecution, DataAnalysis, APICall)
- MCP protocol support
- A2A agent communication
- RBAC security
- Secure sandbox
- Audit logging

### Changed
- Improved layer routing
- Enhanced tool registry

---

## [0.1.0] - 2026-03-01

### Added
- Initial release
- Basic MoRECore orchestration
- L0 execution layer
- L1 orchestration layer
- Basic LLM manager
- Minimal tool registry
- In-memory storage

---

## [0.0.1] - 2026-02-01

### Added
- Project skeleton
- Basic configuration
- Placeholder modules

---

[0.3.0]: https://github.com/qnming/more-os/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qnming/more-os/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/qnming/more-os/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/qnming/more-os/compare/v0.0.0...v0.0.1