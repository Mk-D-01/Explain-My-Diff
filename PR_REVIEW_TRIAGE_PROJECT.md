# PR Review Triage Agent

## 1. Project summary

PR Review Triage Agent helps a junior reviewer understand a large pull request in an unfamiliar codebase. Instead of reading a 400-line diff strictly from top to bottom, the agent divides the diff into meaningful review units, asks independent sub-agents to analyze those units, and merges their findings into a risk-first reading order.

The tool is a review aid, not an approver. It decides **where the reviewer should look first**; the human reviewer still decides whether a change is correct, safe, and acceptable.

### Problem

Large diffs mix high-risk behavioral changes with low-risk formatting, renames, and generated or mechanical edits. A junior reviewer may spend their limited attention on trivial changes before reaching the file containing a serious bug.

### Proposed solution

1. Split the diff by file and/or review concern.
2. Run focused sub-agents in parallel.
3. Require each sub-agent to explain:
   - what changed;
   - why the change may be risky;
   - what assumptions or boundaries deserve human attention.
4. Merge and rank the results by review risk.
5. Present a concise, traceable review plan with the riskiest areas first.

## 2. Goals and success criteria

### Goals

- Reduce the time needed to orient a junior reviewer in an unfamiliar repository.
- Surface behavior-changing and cross-cutting changes before trivial edits.
- Preserve links from every recommendation back to the relevant file and diff hunk.
- Make uncertainty explicit instead of presenting agent output as approval.
- Keep the human reviewer responsible for all review decisions.

### Success criteria

- For each supplied diff, the output contains a complete review order.
- Every changed file is assigned to at least one review unit or explicitly marked as skipped with a reason.
- Each review unit contains “what changed” and “why it might be risky.”
- The merged order places the file containing the planted bug in the top two positions for all three fixed test diffs.
- The output never says that the pull request is approved or safe solely because the agent ran.

## 3. Scope

### In scope

- Ingesting a unified diff and basic repository context.
- Grouping changes by file, dependency relationship, or concern.
- Parallel sub-agent analysis of review units.
- Risk scoring and deterministic tie-breaking.
- Producing a human-readable review plan.
- Running three fixed evaluation diffs with one planted bug in each.
- Checking whether the buggy file ranks in the top two.

### Out of scope for the first version

- Automatically approving, merging, or commenting on a pull request.
- Replacing a full code review or running every repository test.
- Proving that a change is correct.
- Automatically fixing bugs.
- Building a persistent repository-wide code intelligence index.
- Supporting arbitrary hosted Git providers before the local diff workflow is reliable.

## 4. User experience

### Input

- Pull request or unified diff.
- Optional repository metadata such as language, changed-file list, and test commands.
- Optional reviewer focus, for example security, data integrity, or backward compatibility.

### Output

```text
Review order
1. src/payments/refund.ts       High risk
   What changed: Refund validation now accepts a caller-provided amount.
   Why risky: The amount may bypass the server-side balance check.
   Inspect: authorization boundary, negative values, and existing refund tests.

2. src/api/routes.ts             Medium-high risk
   What changed: Added a new endpoint and request mapping.
   Why risky: The route may expose the new behavior without authentication.

3. docs/refunds.md               Low risk
   What changed: Updated examples and wording.
   Why risky: Documentation may no longer match the implementation.
```

The result must include a disclaimer such as: “This is a suggested review order. Human review is required; no approval decision was made.”

## 5. System design

### Stage A: Diff intake and normalization

1. Parse the unified diff into files and hunks.
2. Capture file paths, additions, deletions, language, and surrounding context.
3. Identify metadata such as renames, deleted files, generated files, and test files.
4. Reject or flag malformed input without silently dropping files.

### Stage B: Review-unit planning

Create independent units using the smallest useful boundary:

- one file for isolated changes;
- a group for tightly coupled production and test changes;
- a concern-based unit for cross-cutting changes such as auth, migrations, or API contracts.

The planner should avoid creating so many units that the output becomes noisy. Every unit records the files and diff hunks it covers.

### Stage C: Parallel sub-agent analysis

Each sub-agent receives only the relevant diff plus enough context to reason about it. It returns structured data:

```json
{
  "unit": "payments-refund",
  "files": ["src/payments/refund.ts"],
  "what_changed": "...",
  "risk_factors": ["authorization", "financial state"],
  "why_it_might_be_risky": "...",
  "questions_for_human": ["..."],
  "confidence": "medium",
  "evidence": ["src/payments/refund.ts:42-61"]
}
```

Sub-agents should not make approval claims. They should distinguish observed facts from hypotheses and say when repository context is insufficient.

### Stage D: Merge and ranking

The merge agent combines all unit reports, removes duplicates, and assigns a review priority. A suggested initial rubric is:

- **5 — Critical:** security, authorization, data loss, financial integrity, migrations, or externally visible contract changes.
- **4 — High:** core business logic, concurrency, error handling, state transitions, or broad call-site impact.
- **3 — Medium:** meaningful behavior change with bounded impact.
- **2 — Low:** tests, refactors, or localized maintenance with limited behavior change.
- **1 — Trivial:** formatting, comments, documentation, or mechanical renames.

Risk should be increased for broad blast radius, difficult rollback, missing tests, and low-confidence analysis. Tie-breakers should be deterministic: higher risk first, then lower confidence, then larger behavioral surface, then stable path order.

The merge output must preserve evidence and must not invent findings that were absent from the sub-agent reports.

### Stage E: Human review handoff

Present:

1. A ranked list of review units.
2. The reason for each rank.
3. Files and line ranges to inspect.
4. Open questions and missing context.
5. A clear statement that the human makes the final decision.

## 6. End-to-end implementation steps

1. Define the report schema and the non-approval safety language.
2. Implement diff parsing and file/hunk normalization.
3. Implement review-unit grouping with file coverage validation.
4. Add the sub-agent prompt and structured response validation.
5. Add parallel dispatch with bounded concurrency and failure handling.
6. Implement the merge agent and risk rubric.
7. Add deterministic sorting and evidence preservation.
8. Build a simple CLI or local entry point that accepts a fixed diff and prints the review plan.
9. Create three fixed test diffs, each with one planted bug in a different type of file.
10. Run the ranking evaluation and assert that each buggy file appears in rank 1 or 2.
11. Add regression tests for malformed diffs, missing sub-agent output, duplicate findings, and ties.
12. Document limitations, expected reviewer behavior, and how to add future fixtures.

## 7. Evaluation plan

Use three fixed diffs with comparable sizes and realistic noise. Each fixture contains one intentionally introduced bug and enough non-critical changes to make top-to-bottom reading inefficient.

| Fixture | Planted bug | Expected signal |
|---|---|---|
| A | Authorization check removed from an API route | Security boundary, broad external exposure |
| B | Off-by-one or boundary error in a data transformation | Incorrect behavior at an edge case |
| C | Transaction or retry change that can duplicate a side effect | State integrity and failure-mode risk |

For each fixture:

1. Run the complete pipeline from diff intake through ranking.
2. Locate the file containing the planted bug.
3. Record its 1-based rank in the final review order.
4. Pass only if the rank is `<= 2`.
5. Store the ranked output as an inspectable test artifact so failures can be diagnosed.

### Primary metric

**Top-2 bug recall:** the percentage of fixtures where the planted-bug file appears in the first two review positions.

Target for the initial version: **3/3 fixtures (100%)**.

### Secondary checks

- 100% changed-file coverage.
- No duplicate review units after merge.
- Evidence points to valid file paths and diff ranges.
- Non-approval disclaimer is present.
- A failed or timed-out sub-agent does not cause unrelated files to disappear.

## 8. Failure handling and safeguards

- If a sub-agent fails, mark its unit as unavailable and include it in a fallback section.
- If the merge agent fails, use deterministic rubric sorting over the available unit reports.
- Never treat missing analysis as low risk.
- Keep original file order and raw diff references for traceability.
- Do not expose secrets found in the diff to logs or test artifacts.
- Do not execute arbitrary code from the reviewed repository as part of ranking.
- Clearly label generated risk as a recommendation, not a verdict.

## 9. Definition of done

The first version is complete when:

- A reviewer can supply a diff and receive a ranked, evidence-backed review plan.
- The plan explains what changed and why it might be risky for every review unit.
- The reviewer can trace every item to the original diff.
- The three fixed evaluation diffs pass the top-two ranking test.
- Failure modes and limitations are documented.
- The tool makes no approval, merge, or correctness decision on behalf of the human reviewer.

## 10. Future extensions

- Learn from reviewer reordering without silently changing the safety rubric.
- Add repository-aware dependency and ownership signals.
- Compare rankings against historical escaped defects.
- Support interactive follow-up questions per review unit.
- Add optional integrations that post a review checklist, while keeping approval actions explicitly human-controlled.
