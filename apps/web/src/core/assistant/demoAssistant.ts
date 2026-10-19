import i18n from "@/i18n";
import { COPILOT_DEMO_DELAY_MS } from "@/constants/app.constant";
import { compareCandidates, planLetter } from "@/core/twin/candidateComparison";
import {
  ASSISTANT_MODE,
  ASSISTANT_OUTCOME,
  ASSISTANT_SOURCE,
  ASSISTANT_STATUS,
  EVIDENCE_KIND,
  EVIDENCE_SOURCE,
  TOOL_CAPABILITY,
  type AssistantOutcome,
} from "@/enums/assistant.enum";
import { REVENUE_PERIOD } from "@/enums/commerce.enum";
import { ACTION_TYPE } from "@/enums/simulation.enum";
import { DEMO_NAMES, demoSkuSales } from "@/fixtures/demo/commerce";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { DEMO_SIMULATION_ID } from "@/fixtures/demo/simulation";
import { anomaliesOf, useAnomalyStore } from "@/state/anomaly.store";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import type {
  Assistant,
  AssistantConstraint,
  AssistantEvidence,
  AssistantMessageRequest,
  AssistantProposal,
  AssistantToolCall,
  AssistantTurn,
} from "@/types/assistant.type";
import type { Candidate, SimulationAction } from "@/types/simulation.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { format } from "@/core/utils/format";
import { actionLabel } from "./proposalText";

/**
 * Demo data for `?twin=demo`, never Gemini: the Copilot's replies as a fixed script, the
 * same for the same message on the same state. It reads only what the page already holds
 * (the twin, the open anomalies, the demo sales) and plans only what the demo candidates
 * plan, opening it as a simulation on the memory twin. It never calls apps/api, and it
 * commits nothing: approval stays with the Simulation banner and its guard.
 */

/** A product code as written in a message. */
const SKU_PATTERN = /\bP\d{3,}\b/gi;
/** Instructions aimed at the model or the stores, anywhere in the message. */
const INJECTION = [
  /\bignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules)/i,
  /\b(system prompt|developer message|jailbreak)\b/i,
  /\b(sql|drop\s+table|firestore|bigquery)\b/i,
];
/** An order to change the store, at the start of a sentence. */
const WRITE = /(^|[.!?]\s*)(please\s+)?(set|update|change|delete|remove|write|patch|overwrite|move|restock now)\b/i;
/** An order to approve, at the start of a sentence, or a go-ahead. */
const APPROVE = /(^|[.!?]\s*)(please\s+)?(approve|accept|commit|execute|apply|confirm)\b|\bgo ahead\b|\bdo it\b/i;
const PLAN = /\b(suggest|plan|optimi[sz]e|restock|replenish|layout|improve|fix|safer|recommend|propose)\b/i;
const EXPLAIN = /\b(what|why|how|status|happening|show|explain|tell|stock|sales|trend|low|empty)\b/i;

const INTENT = {
  Explain: "explain",
  Plan: "plan",
  Approve: "approve",
  Write: "write",
  Unknown: "unknown",
} as const;
type Intent = (typeof INTENT)[keyof typeof INTENT];

function intentOf(text: string): Intent {
  if (INJECTION.some((pattern) => pattern.test(text)) || WRITE.test(text)) return INTENT.Write;
  if (APPROVE.test(text)) return INTENT.Approve;
  if (PLAN.test(text)) return INTENT.Plan;
  if (EXPLAIN.test(text)) return INTENT.Explain;
  return INTENT.Unknown;
}

/** "Peanut butter 340 g" is asked about as "peanut butter". */
const NAME_KEYS = Object.entries(DEMO_NAMES).map(([sku, name]) => ({
  sku,
  key: name.replace(/\s+\d[\d.,]*\s*(g|kg|ml|l)\b.*$/i, "").toLowerCase(),
}));

/** The product the message is about: a SKU in it, else a demo name in it, else the selected product. */
function skuOf(text: string): string | null {
  const [code] = text.match(SKU_PATTERN) ?? [];
  if (code) return code.toUpperCase();
  const lower = text.toLowerCase();
  const named = NAME_KEYS.find(({ key }) => lower.includes(key));
  return named?.sku ?? selectedProductId(useUiStore.getState());
}

const nameOf = (sku: string) => DEMO_NAMES[sku] ?? sku;

/** The demo script's words, under `copilot.demo` in the locale files. */
const t = (key: string, values?: Record<string, unknown>) => String(i18n.t(`copilot.demo.${key}` as never, values as never));

type Draft = Pick<AssistantTurn, "status" | "text"> &
  Partial<Pick<AssistantTurn, "outcome_code" | "evidence" | "tool_calls" | "proposal">>;

const read = (tool: string, sku: string | null, ok = true, error_code: string | null = null): AssistantToolCall => ({
  tool,
  capability: TOOL_CAPABILITY.Read,
  ok,
  error_code,
  sku,
  duration_ms: null,
});

const simulate = (tool: string, sku: string | null): AssistantToolCall => ({
  tool,
  capability: TOOL_CAPABILITY.Simulation,
  ok: true,
  error_code: null,
  sku,
  duration_ms: null,
});

const unsupported = (outcome: AssistantOutcome, text: string, extra: Partial<Draft> = {}): Draft => ({
  status: ASSISTANT_STATUS.Unsupported,
  outcome_code: outcome,
  text,
  ...extra,
});

const refused = (outcome: AssistantOutcome, text: string): Draft => ({
  status: ASSISTANT_STATUS.Refused,
  outcome_code: outcome,
  text,
});

const notFound = (sku: string, live: StoreResponse): Draft =>
  unsupported(ASSISTANT_OUTCOME.SkuNotFound, t("notFound", { sku, version: live.context_version }), {
    tool_calls: [read("get_inventory", sku, false, "not_found")],
  });

function inventoryEvidence(product: ProductInventory, live: StoreResponse): AssistantEvidence {
  return {
    id: `inventory:${product.sku}`,
    kind: EVIDENCE_KIND.Inventory,
    label: t("evidence.inventory"),
    detail: t("evidence.inventoryDetail", {
      shelf: product.shelf_quantity,
      backroom: product.backroom_quantity,
      facings: product.facings,
      slot: product.slot_id,
    }),
    source: EVIDENCE_SOURCE.Fixture,
    tool: "get_inventory",
    sku: product.sku,
    as_of: live.context_version,
    confidence: null,
  };
}

/** "What is happening with P003?": its stock, its open alerts, and its demo sales. */
function explain(sku: string, live: StoreResponse): Draft {
  const product = live.products.find((item) => item.sku === sku);
  if (!product) return notFound(sku, live);
  const anomalies = anomaliesOf(useAnomalyStore.getState().anomalies, sku);
  const today = demoSkuSales(REVENUE_PERIOD.Today).find((item) => item.sku === sku);
  const week = demoSkuSales(REVENUE_PERIOD.Week).find((item) => item.sku === sku);

  const evidence: AssistantEvidence[] = [inventoryEvidence(product, live)];
  for (const anomaly of anomalies) {
    evidence.push({
      id: `anomaly:${anomaly.anomaly_id}`,
      kind: EVIDENCE_KIND.Anomaly,
      label: anomaly.title,
      detail: anomaly.description,
      source: EVIDENCE_SOURCE.Fixture,
      tool: null,
      sku,
      as_of: anomaly.detected_at,
      confidence: null,
    });
  }
  if (today && week) {
    evidence.push({
      id: `sales:${sku}`,
      kind: EVIDENCE_KIND.Sales,
      label: t("evidence.sales"),
      detail: t("evidence.salesDetail", {
        today: today.units,
        todayRevenue: format.moneyExact(today.revenue),
        week: week.units,
        weekRevenue: format.moneyExact(week.revenue),
      }),
      source: EVIDENCE_SOURCE.Fixture,
      tool: "get_sales_history",
      sku,
      as_of: null,
      confidence: null,
    });
  }

  const shelf =
    product.shelf_quantity > 0
      ? ""
      : product.backroom_quantity > 0
        ? ` ${t("explain.emptyRefill")}`
        : ` ${t("explain.emptyEverywhere")}`;
  const alerts = anomalies.map((anomaly) => ` ${t("explain.alert", { title: anomaly.title })}`).join("");
  const sales = today && week ? ` ${t("explain.sales", { today: today.units, week: week.units })}` : ` ${t("explain.noSales")}`;
  const next = planFor(sku, live) ? ` ${t("explain.askPlan", { sku })}` : "";
  return {
    status: ASSISTANT_STATUS.Answered,
    text:
      t("explain.stock", {
        name: nameOf(sku),
        sku,
        shelf: product.shelf_quantity,
        backroom: product.backroom_quantity,
        facings: product.facings,
        slot: product.slot_id,
      }) + shelf + alerts + sales + next,
    evidence,
    tool_calls: [read("get_inventory", sku), read("get_sales_history", sku, Boolean(today && week), today && week ? null : "not_found")],
  };
}

/** The demo plan for `sku`: the recommended candidate that changes it, else the first one that does. */
function planFor(sku: string, live: StoreResponse): Candidate | null {
  const { proposals } = compareCandidates(demoCandidates(live));
  const touching = proposals.filter((candidate) => candidate.proposed_actions.some((action) => action.sku === sku));
  return touching.find((candidate) => candidate.recommended) ?? touching[0] ?? null;
}

/** What the plan was checked against, from the twin it was built on. */
function constraintsOf(actions: SimulationAction[], live: StoreResponse): AssistantConstraint[] {
  const checks: AssistantConstraint[] = [];
  for (const action of actions) {
    if (action.type !== ACTION_TYPE.ReplenishShelf) continue;
    const backroom = live.products.find((item) => item.sku === action.sku)?.backroom_quantity ?? 0;
    checks.push({
      label: t("constraint.backroom", { sku: action.sku, quantity: action.quantity, backroom }),
      passed: action.quantity <= backroom,
    });
  }
  const moves = actions.filter((action) => action.type === ACTION_TYPE.MoveProduct).length;
  checks.push(moves ? { label: t("constraint.moves", { count: moves }), passed: false } : { label: t("constraint.noMoves"), passed: true });
  checks.push({ label: t("constraint.context", { version: live.context_version }), passed: true });
  return checks;
}

/**
 * "Suggest a safer restock for P003": the demo plan that changes it. While the demo run is
 * still open, the plan is its candidate, with the KPIs the demo evaluator data holds for it.
 * Otherwise its actions are opened as a new simulation on the memory twin, unscored.
 */
function plan(sku: string, live: StoreResponse, openSimulation: (actions: SimulationAction[]) => string): Draft {
  const product = live.products.find((item) => item.sku === sku);
  if (!product) return notFound(sku, live);
  const candidate = planFor(sku, live);
  if (!candidate) {
    const planned = [
      ...new Set(compareCandidates(demoCandidates(live)).proposals.flatMap((item) => item.proposed_actions.map((action) => action.sku))),
    ].sort();
    return unsupported(ASSISTANT_OUTCOME.NoPlan, t("noPlan", { sku, skus: planned.join(", ") }), {
      tool_calls: [read("get_inventory", sku)],
    });
  }

  const twin = useTwinStore.getState();
  const open = twin.simulation?.simulation_id === DEMO_SIMULATION_ID ? twin.simulation : null;
  const served = open ? compareCandidates(twin.candidates) : null;
  const scored = served?.proposals.find((item) => item.candidate_id === candidate.candidate_id) ?? null;
  // The plan's letter as the candidate panel labels it: its place among the served proposals.
  const proposals = served && scored ? served.proposals : compareCandidates(demoCandidates(live)).proposals;
  const letter = planLetter(proposals.findIndex((item) => item.candidate_id === candidate.candidate_id));
  const actions = scored?.proposed_actions ?? candidate.proposed_actions;

  const simulationId = open && scored ? open.simulation_id : openSimulation(actions);
  const reason = scored ? (scored.rationale ?? scored.provenance) : candidate.provenance;
  const summary = actions.map(actionLabel).join(" · ");
  const proposal: AssistantProposal = {
    simulation_id: simulationId,
    candidate_id: scored ? scored.candidate_id : null,
    decision_id: null,
    base_context_version: open && scored ? open.base_context_version : live.context_version,
    actions,
    summary,
    kpis: scored?.kpis ?? [],
    baseline_kpis: scored ? (served?.baseline?.kpis ?? []) : [],
    evaluator_version: scored?.evaluator_version ?? null,
    constraints: constraintsOf(actions, live),
    guard: null,
  };
  const lead = scored?.recommended ? t("plan.recommended", { plan: letter, sku, reason }) : t("plan.candidate", { plan: letter, sku, reason });
  return {
    status: ASSISTANT_STATUS.Proposed,
    text: `${lead} ${t(scored ? "plan.scored" : "plan.unscored")} ${t("plan.review")}`,
    evidence: [inventoryEvidence(product, live)],
    tool_calls: [
      read("get_inventory", sku),
      read("get_backroom_inventory", sku),
      ...(open && scored
        ? [simulate("calculate_business_impact", null)]
        : [simulate("create_simulation", null), ...actions.map((action) => simulate(action.type, action.sku))]),
    ],
    proposal,
  };
}

function answer(text: string, openSimulation: (actions: SimulationAction[]) => string): Draft {
  const intent = intentOf(text);
  if (intent === INTENT.Write) return refused(ASSISTANT_OUTCOME.LiveWriteForbidden, t("refuseWrite"));
  if (intent === INTENT.Approve) return refused(ASSISTANT_OUTCOME.ApprovalInChat, t("refuseApprove"));
  const sku = skuOf(text);
  if (intent === INTENT.Unknown && !sku) return unsupported(ASSISTANT_OUTCOME.UnknownIntent, t("unknownIntent"));
  if (!sku) return unsupported(ASSISTANT_OUTCOME.NoSku, t("noSku"));
  const live = useTwinStore.getState().live;
  if (!live) return unsupported(ASSISTANT_OUTCOME.UnknownIntent, t("notLoaded"));
  return intent === INTENT.Plan ? plan(sku, live, openSimulation) : explain(sku, live);
}

/**
 * The demo Copilot. `openSimulation` opens actions as a simulation on the memory twin and
 * returns its id. The same `message_id` answers with the same turn, so a resend never runs
 * a message twice; each reply comes after `delayMs`, so the wait shows as it would on Live.
 */
export function createDemoAssistant(
  openSimulation: (actions: SimulationAction[]) => string,
  delayMs = COPILOT_DEMO_DELAY_MS,
): Assistant {
  const replies = new Map<string, Promise<AssistantTurn>>();
  return {
    mode: ASSISTANT_MODE.Demo,
    send(conversationId: string, request: AssistantMessageRequest, correlationId: string) {
      const known = replies.get(request.message_id);
      if (known) return known;
      const reply = new Promise<AssistantTurn>((resolve, reject) => {
        setTimeout(() => {
          try {
            const draft = answer(request.text, openSimulation);
            resolve({
              conversation_id: conversationId,
              message_id: request.message_id,
              reply_id: `reply-${request.message_id}`,
              correlation_id: correlationId,
              run_id: null,
              store_id: request.store_id,
              context_version: useTwinStore.getState().live?.context_version ?? request.context_version,
              source: ASSISTANT_SOURCE.DemoScript,
              model: null,
              outcome_code: null,
              evidence: [],
              tool_calls: [],
              proposal: null,
              created_at: new Date().toISOString(),
              ...draft,
            });
          } catch (error) {
            replies.delete(request.message_id);
            reject(error);
          }
        }, delayMs);
      });
      replies.set(request.message_id, reply);
      return reply;
    },
  };
}
