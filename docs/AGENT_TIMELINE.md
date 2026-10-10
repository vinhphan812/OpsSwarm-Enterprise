# Agent Activity Timeline

The Agent Activity Timeline provides a real-time, 9-stage visualization of the autonomous path taken by an agent to solve a given task. 

## The 9-Stage Timeline
The timeline consists of the following sequential stages:
1. **Trigger**: The initial event initiation.
2. **Evidence**: Gathering and analyzing necessary information.
3. **Diagnosis**: Interpreting findings.
4. **Alternatives**: Generating potential solutions.
5. **Selected Plan**: Choosing the optimal path.
6. **Simulation**: Verifying the plan before execution.
7. **Guard**: Safety and constraint checks.
8. **Action**: Executing the plan.
9. **Verification**: Confirming the outcome.

## Architecture
The timeline utilizes a mock store as the MVP data source, but implements the `IAgentEventStore` interface. This allows for seamless swapping with a real, live event stream in future iterations.

## Schema Reference
- `AgentEvent`: The top-level container for timeline data. Includes metadata like `contextVersion`, `correlationId`, and `eventId`.
- `AgentStage`: Defines individual timeline stages. Explicit fields capture state, duration, output summary, and, for failed stages, an explicit `failureReason`.

## Provenance and Constraints
- **Deterministic**: All quantitative values and summaries must be derived from deterministic code.
- **No Credentials**: Storing credentials in the timeline UI is strictly forbidden.
- **No Hidden CoT**: The timeline explicitly displays the stages of the agent's path; no "black-box" Chain-of-Thought (CoT) processes are hidden from the user.
- **Failures**: Failed stages display explicitly with the associated `failureReason`.
