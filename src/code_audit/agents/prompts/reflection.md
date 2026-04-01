# Agent Self-Reflection: {{DIMENSION}}

You are reviewing your own findings from a code audit. You originally reviewed as the **{{DIMENSION}}** specialist.

## Your Original Findings
{{OWN_FINDINGS}}

## All Findings From All Agents (After Judge Aggregation)
{{ALL_FINDINGS}}

## Instructions

For each of YOUR original findings, decide one action:

1. **KEEP** — Finding is correct as-is. No changes.
2. **UPGRADE** — After seeing other agents' findings, you're MORE confident. Increase confidence.
3. **DOWNGRADE** — After seeing other agents' findings, you're LESS confident. Decrease confidence.
4. **WITHDRAW** — Finding is a false positive or already covered better by another agent's finding.

You may also add `cross_references` — IDs of findings from other agents that relate to yours.

**PRECISION MANDATE**: Be honest. If another agent found the same issue with a better description, withdraw yours. If seeing the broader context makes your finding weaker, downgrade it. Only upgrade if genuinely corroborated.

Respond with a JSON object matching the required schema.
