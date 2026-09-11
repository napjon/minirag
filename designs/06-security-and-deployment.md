# Security and Deployment Design

## Identity and session

Use OIDC authorization code flow with PKCE. The backend exchanges tokens and stores an opaque session identifier in a `Secure`, `HttpOnly`, `SameSite` cookie. Access tokens are never stored in browser storage. Sessions have idle and absolute expiry, rotation, revocation, and step-up support for sensitive approval or export operations.

## Four authorization layers

1. **Route:** permission to invoke the workflow.
2. **Object:** workspace, source, draft, job, and export ownership or grants.
3. **Query:** policy predicates included in lexical, vector, relational, and analytics queries.
4. **Database:** row-level security as defense in depth.

The application runtime uses a restricted database role. A separate migration owner manages schema and policies and is unavailable to application processes. Background jobs reconstruct policy context from immutable identifiers and reauthorize before each sensitive stage.

## Content and model safety

Uploads, retrieved text, tool output, and historical examples are untrusted data. Prompts delimit evidence and forbid instructions inside evidence from changing workflow, tools, permissions, or system policy. Tools accept typed schemas, enforce destinations and row limits, and return bounded results. Outputs pass schema, citation, leakage, and content-policy validation before display or export.

Adversarial tests include direct and indirect prompt injection, malicious filenames and metadata, cross-workspace references, citation URL tampering, oversized inputs, tool-argument smuggling, stale grants, and replayed approvals.

## MCP boundary

Each MCP connection binds to one authenticated principal, workspace context, and session expiry. Tools expose the same workflow authorization used by the web API. Tool output contains stable resource identifiers rather than unrestricted filesystem paths. A reconnect never restores an expired or revoked identity implicitly.

## Deployment profiles

| Concern | Hosted profile | Private-network profile |
|---|---|---|
| Compute | managed application and worker pools | isolated application and worker pools |
| Data | shared platform database with tenant policy and encrypted object storage | private shared platform services and private object storage |
| Models | approved pinned artifacts inside the hosted trust boundary | the same approved artifacts mirrored inside the private boundary |
| Egress | allowlisted adapters | denied by default; explicit internal allowlists |
| Secrets | managed secret store and workload identity | private secret store and workload identity |
| Updates | signed artifact promotion | signed offline or controlled mirror promotion |
| Audit | append-only store and governed export | local append-only store and governed export |

Both profiles share interfaces, schema migrations, model manifests, evaluation datasets, and release gates. Profile-specific infrastructure is configuration, not a separate application fork.

## Data protection and retention

- Encrypt transport and stored data with managed keys and documented rotation.
- Use short-lived credentials and audience-bound object URLs.
- Redact secrets, tokens, and sensitive content from logs and traces.
- Apply per-class retention to binaries, derived text, model inputs, outputs, exports, and audit events.
- Propagate withdrawal and deletion through indexes, caches, derived artifacts, and backups according to policy.
- Test restore, key failure, storage denial, and unavailable audit sink behavior. Consequential workflows fail closed when their audit event cannot be committed.

## Security release gates

- zero unauthorized rows across at least 1,000 cross-role and cross-workspace attempts
- zero forbidden actions across at least 300 injection cases
- zero approval bypasses through UI, API, jobs, replay, or MCP
- blocked-egress private-profile run completes without external calls
- dependency, secret, container, and infrastructure scans meet the release policy
- restore and revocation exercises produce complete audit trails

Primary rubric links: A-T2-05/06/10, B-T2-05/07, B-T3-09, C-T2-05/08, C-T3-10, D-T2-03/04/05, D-T3-06.
