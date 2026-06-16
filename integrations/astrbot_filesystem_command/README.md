# AstrBot Deterministic Ops Bridge

This plugin routes a small set of deterministic local operations directly to
`星璇运维MCP` write-plan tools without entering the LLM pipeline.

## Purpose

Use it when the request is highly structured, low-ambiguity, and suitable for a
fixed MCP tool call such as:

- create one folder
- create one file
- restart one known service
- generate one firewall change plan
- generate one log cleanup plan

## Behavior

- The plugin only handles a narrow intent set.
- It always calls MCP tools with `dry_run=true`.
- It stops event propagation so the request does not enter the normal LLM flow.
- It does not execute arbitrary shell commands.

## Security boundary

This bridge only generates or forwards structured MCP write plans.
Real execution still requires the existing approval, execution policy, and
audit chain.
