# Approval Policy Configuration

This directory contains local approval policy rules for `tmp_MCP`.

Default file:

```text
config/approvals/policies.yaml
```

Runtime override:

```text
TMP_MCP_APPROVAL_POLICY_FILE
```

The approval policy is a local guard for approval requests. It does not replace
real identity verification. In AstrBot production integration, ordinary user
sessions should not expose `record_operation_approval_tool`; only trusted
approval channels should record grant, reject, revoke, or renew actions.

External approval identity pre-check:

```text
TMP_MCP_APPROVAL_IDENTITY_SECRET
TMP_MCP_REQUIRE_APPROVAL_IDENTITY
TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE
```

When `TMP_MCP_REQUIRE_APPROVAL_IDENTITY=true`, `record_operation_approval_tool`
requires an HMAC-signed `approval_token`. The signing key must come from a
trusted approval channel or secret manager, never from a normal user session and
never from a repository file.
