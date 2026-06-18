// Cross-Cutting Services — the modelling, data, reporting, and delivery backbone
// that every other group depends on. These agents are domain-spanning enablers
// rather than a transactional flow, so this view is an informational capability
// board (no live job runner): it lists what the group can do and the agents that
// deliver it. Execution routes through the requesting group's own approval gates.

import { GROUPS_BY_ID, humanizeAgent, isGateAgent } from '../../lib/catalog'

const GROUP = GROUPS_BY_ID['cross-cutting']

export function CrossCuttingPage() {
  return (
    <div className="cross-cutting-page">
      <header>
        <h1>{GROUP.title}</h1>
      </header>

      <section aria-label="What this group does">
        <h2>What it does</h2>
        <p className="section-desc">
          The capabilities this shared-services group offers every other finance group — modelling,
          data, reporting, ESG, and delivery. This is reference only; there is no input to enter
          here, and consequential output is consumed and approved by the requesting group.
        </p>
        <ul>
          {GROUP.capabilities.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </section>

      <section aria-label="Agents">
        <h2>Agents</h2>
        <p className="section-desc">
          The subagents that deliver these shared services; ones tagged &quot;gate&quot; enforce a
          mandatory check (e.g. data or ESG controls) before their output can be used downstream.
          Informational only — no input to enter here.
        </p>
        <ul>
          {GROUP.agents.map((a) => (
            <li key={a}>
              {humanizeAgent(a)}
              {isGateAgent(a) && <span className="tag"> gate</span>}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="How it runs">
        <h2>How it runs</h2>
        <p className="section-desc">
          How this group fits the platform: it has no live job runner or approval queue of its own,
          so there is nothing to run or enter here — execution and human approval happen in the
          group that requested the work.
        </p>
        <p>
          Cross-cutting services are shared enablers: they supply models, dashboards, curated data,
          ESG disclosures, and programme &amp; vendor delivery to every other group. They don&apos;t
          post, pay, trade, or file on their own — any consequential output is consumed by the
          requesting group and runs through that group&apos;s human-approval gates.
        </p>
      </section>
    </div>
  )
}
