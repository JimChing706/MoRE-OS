---
title: Token-Aware Rate Limiter for LLM Providers
version: 1.0.0
author: MoRE OS Core Team
created: 2026-07-22T10:00:00Z
type: code_generation
priority: high
deliverable_kind: code
tags: [llm, rate-limiting, reliability]
estimated_hours: 8.0
pipeline:
  mode: standard
target_confidence: 80.0
max_iterations: 5
timeout_s: 120.0
allow_self_improvement: false
require_metacognitive: false
kill_on_diverge: true
---

# Executive Summary

Implement a sliding-window rate limiter for the LLM provider chain. Currently the
system has no per-provider rate limiting, causing 429 errors from upstream APIs
under burst load. This task adds a sliding-window rate limiter with per-provider
configuration, fallback queuing, and Prometheus metrics export.

# Requirements

## REQ-001: Sliding Window Implementation
**Priority:** HIGH
**Description:** Implement a sliding-window rate limiter that tracks requests per
provider per time window. Window size and max request count must be configurable
per provider.

**Acceptance Criteria:**
- [ ] Rate limiter rejects requests exceeding max_requests per window_seconds
- [ ] Window slides correctly after idle periods
- [ ] Config is reloadable without service restart
- [ ] All edge cases documented (zero window, zero max, concurrent access)

## REQ-002: Provider Configuration
**Priority:** MEDIUM
**Description:** Each LLM provider must expose rate limit settings in its config,
with sensible defaults (LM Studio: 30 req/min, Ollama: 60 req/min, DeepSeek: 3000 req/min).

**Acceptance Criteria:**
- [ ] Default config values for all 3 providers
- [ ] Config overridable via environment variable and .env
- [ ] Configuration validated at startup with clear error messages

## REQ-003: Metrics Export
**Priority:** LOW
**Description:** Expose rate limiter stats via a Prometheus-compatible endpoint
for operational monitoring.

**Acceptance Criteria:**
- [ ] Per-provider request count metric exported
- [ ] Per-provider throttle count metric exported
- [ ] Current window utilization metric exported

# Deliverable Contract

**Kind:** code
**Required Dimensions:** core_output, reasoning, tests, performance
**Minimum Output Length:** 200

**Quality Gates:**
| Gate | Threshold |
|------|-----------|
| min_output_length | 200 |
| must_contain_code_fence | true |
| must_contain_test_cases | true |

**Acceptance Criteria:**
- [ ] All rate limiter unit tests pass with >80% coverage
- [ ] Integration test with mocked providers confirms fallback behavior
- [ ] Benchmark shows <1ms overhead per rate-limited call

# Kill Criteria

| ID | Condition | Severity | Timeline | Fallback |
|----|-----------|----------|----------|----------|
| KC-001 | Test coverage drops below 70% | critical | immediate | Skip tests, file issue |
| KC-002 | Benchmark overhead exceeds 5ms | warning | end-of-run | Log warning, proceed with degraded config |
| KC-003 | API-breaking change required | fatal | immediate | Block, require ADR |

# Resource Budget

**Estimated Tokens:** 12,000
**Estimated Duration:** 30 minutes
**Max Iterations:** 5

# Context and Constraints

## Background
The current LLM manager (llm/manager.py) has a single global rate limit that does
not distinguish between providers. This causes DeepSeek API calls to be
unnecessarily throttled by LM Studio's conservative limits.

## Constraints
- Must not introduce new external dependencies
- Must maintain backward compatibility with existing provider configs
- Rate limiter must be debuggable: expose stats endpoint

## References
- llm/manager.py
- core/config.py
