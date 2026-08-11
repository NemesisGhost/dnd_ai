# ADR 0012: Host production on the existing Ubuntu mini-PC

- Status: Accepted
- Date: 2026-08-11
- Supersedes: the production-hosting portions of [ADR 0008](0008-aws-first-deployment-and-verification.md) and [ADR 0011](0011-local-first-development-aws-verified-delivery.md)

## Context

The project already has an Ubuntu mini-PC running FoundryVTT in Docker. An AWS production stack would add recurring cost and operational surface before the application has demonstrated a need for managed cloud capacity. The application boundary is portable, so hosting it beside Foundry does not require coupling their data or lifecycles.

## Decision

Production targets the existing mini-PC. Docker Compose runs the React UI, FastAPI under Uvicorn, PostgreSQL, and any required worker or scheduled-job containers on a private Docker network. A reverse proxy is the only public HTTP/HTTPS entry point and obtains and renews TLS certificates. No-IP maintains the home connection's dynamic DNS record.

The preferred browser topology is:

```text
https://world.<domain>/        -> React UI
https://world.<domain>/api/*   -> FastAPI
https://foundry.<domain>/      -> FoundryVTT
```

The shared `world` origin for UI and API simplifies secure cookies, CSRF controls, and CORS. The repository does not establish whether a custom domain or only a No-IP hostname is controlled. Both are supported: custom-domain DNS can delegate `world` and `foundry` records to the No-IP-managed target; a No-IP-only arrangement may instead use separate available hostnames or path/routing choices supported by that provider. Exact public names are a deployment-time decision.

FoundryVTT and D&D AI remain separately managed services with separate application data, authentication, configuration, lifecycle, and backups. They may share the host and reverse proxy, but D&D AI does not connect to Foundry's database.

FastAPI, command/query services, and database code remain platform-neutral. Lambda, Mangum, API Gateway, RDS, or another cloud adapter may be added as isolated optional deployment adapters, but none is required for production.

## Consequences

Benefits include reuse of owned hardware, lower recurring cost, one local operational surface, simple same-origin browser security, and low-latency access to the separately hosted Foundry service.

Accepted risks include residential power and internet outages, dynamic-IP changes, constrained upload bandwidth, hardware failure, and the operator owning patching, monitoring, backup, restore, and incident response. Mitigations include automatic TLS and No-IP updates, restart policies, health checks, log rotation, disk monitoring, resource limits, and tested onsite plus offsite backups.

Existing AWS resources are transitional, not immediate deletion targets. They remain until local migrations, extensions, bootstrap roles, the Phase 10 vertical slice, reverse-proxy authentication/authorization, backup/restore, and required data migration are verified and teardown is explicitly approved.

A move to a VPS or AWS is justified if measured availability, bandwidth, capacity, security, maintenance burden, disaster-recovery objectives, or multi-operator needs exceed what the residential host can reliably provide. The portable application boundary makes that a deployment change rather than an application rewrite.

## References

- [PLAN.md](../PLAN.md)
- [SYSTEM_ARCHITECTURE.md](../architecture/SYSTEM_ARCHITECTURE.md)
- [LOCAL_DEPLOYMENT.md](../LOCAL_DEPLOYMENT.md)

