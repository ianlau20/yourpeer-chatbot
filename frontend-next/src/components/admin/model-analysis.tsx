// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useState } from "react";
import {
  ChevronDown,
  Zap,
  Brain,
  Shield,
  Languages,
  Scale,
  ExternalLink,
  Route,
  Heart,
  HelpCircle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// DATA
// ---------------------------------------------------------------------------

interface ModelInfo {
  id: string;
  name: string;
  input: number;
  output: number;
  speed: string;
  latency: string;
  context: string;
  strengths: string[];
  weaknesses: string[];
}

const MODELS: Record<string, ModelInfo> = {
  haiku: {
    id: "claude-haiku-4-5-20251001",
    name: "Haiku 4.5",
    input: 1.0,
    output: 5.0,
    speed: "4-5x faster than Sonnet [1]",
    latency: "Est. ~0.4s TTFT [3]",
    context: "200K",
    strengths: [
      "Anthropic\u2019s safest model \u2014 lowest misaligned behavior rate vs Sonnet 4.5 and Opus 4.1 [1]",
      "4-5x faster than Sonnet [1]",
      "Strong classification accuracy (on par with Sonnet 4 generation) [1]",
      "Excellent instruction following for structured tasks [5]",
      "90% of Sonnet 4.5\u2019s coding performance per Augment\u2019s agentic eval [1]",
      "Low prompt injection vulnerability [2]",
    ],
    weaknesses: [
      "Less nuanced reasoning on ambiguous / indirect language",
      "May over-engineer or be verbose on loosely specified tasks [5]",
      "No adaptive thinking \u2014 supports extended thinking only [4]",
    ],
  },
  sonnet: {
    id: "claude-sonnet-4-6",
    name: "Sonnet 4.6",
    input: 3.0,
    output: 15.0,
    speed: "Moderate",
    latency: "Est. ~0.8s TTFT [3]",
    context: "1M (beta)",
    strengths: [
      "Strongest reasoning and nuance among mid-tier models [6]",
      "Adaptive thinking \u2014 adjusts reasoning depth to complexity [4]",
      "94% accuracy on Anthropic\u2019s internal insurance computer use benchmark [6]",
      "Tool-calling reliability: follows schemas more consistently [6]",
      "Fewer hallucinated links in computer use evals (per partner report) [7]",
      "70% more token-efficient than Sonnet 4.5 on partner filesystem benchmark [7]",
    ],
    weaknesses: [
      "3x more expensive than Haiku [8]",
      "Slower response time than Haiku [6]",
      "Overkill for simple classification / extraction tasks",
      "Higher latency matters for real-time chat UX",
    ],
  },
};

interface TaskDef {
  id: string;
  name: string;
  desc: string;
  icon: typeof Zap;
  inputTokens: number;
  outputTokens: number;
  requirements: string[];
  recommendation: "haiku" | "sonnet";
  rationale: string;
  isJury?: boolean;
  jurySteps?: { name: string; detail: string }[];
  juryCost?: string;
  juryInfra?: string;
}

const TASKS: TaskDef[] = [
  {
    id: "conversational",
    name: "Conversational fallback",
    icon: Zap,
    desc: "General chat when the user\u2019s message doesn\u2019t match service keywords. Uses Claude Haiku for speed.",
    inputTokens: 200,
    outputTokens: 80,
    requirements: [
      "Warm, empathetic tone for vulnerable population",
      "Short responses (1-3 sentences)",
      "Gently steer toward service queries",
      "Never fabricate service info",
    ],
    recommendation: "haiku",
    rationale:
      "Simplest LLM task \u2014 short prompt, short output, no tool calling. Haiku\u2019s 4-5x speed advantage directly improves chat UX. The 1-3 sentence output constraint means Sonnet\u2019s deeper reasoning adds no value. Haiku\u2019s instruction following is sufficient for the guardrails.",
  },
  {
    id: "slotExtraction",
    name: "Slot extraction (tool calling)",
    icon: Brain,
    desc: "LLM-based structured extraction of service type, location, age, urgency, gender from natural language via Claude function calling.",
    inputTokens: 450,
    outputTokens: 60,
    requirements: [
      "Accurate tool calling with structured JSON output",
      "Handle indirect language (\u2018just got out of hospital\u2019 \u2192 shelter)",
      "Resolve conflicting signals (\u2018in Queens but need food in Brooklyn\u2019)",
      "Extract from context (\u2018my son is 12\u2019 \u2192 age=12)",
      "Only extract what\u2019s stated, don\u2019t guess",
    ],
    recommendation: "haiku",
    rationale:
      "Simple schema (5 optional fields), codebase routes only complex messages to LLM (regex handles simple cases), and Haiku\u2019s tool-calling is reliable for bounded schemas. Monitor accuracy \u2014 first task to upgrade to Sonnet if edge cases increase.",
  },
  {
    id: "classification",
    name: "Message classification",
    icon: Route,
    desc: "Route ambiguous messages to the correct handler when regex keyword matching falls through. Only invoked on messages longer than 3 words that regex classified as \u201Cgeneral.\u201D",
    inputTokens: 300,
    outputTokens: 10,
    requirements: [
      "Classify into one of 16 routing categories (service, greeting, emotional, bot_question, etc.)",
      "Distinguish \u2018I need help with housing\u2019 (service) from \u2018how does this work\u2019 (bot_question)",
      "Distinguish \u2018I\u2019m feeling really down\u2019 (emotional) from \u2018I don\u2019t know what to do\u2019 (confused)",
      "Handle indirect service needs (\u2018I was just released\u2019 \u2192 service)",
      "Return single category name, validated against known set",
    ],
    recommendation: "haiku",
    rationale:
      "This is a simple classification task (pick 1 of 16 labels) with a short output (single word). Regex handles the clear cases; the LLM only sees messages where regex already failed, so the bar is \u2018better than general\u2019 not \u2018perfect.\u2019 Haiku\u2019s speed keeps the latency impact minimal for real-time chat. If the LLM fails, the system falls back to the regex result (general) \u2014 no safety risk.",
  },
  {
    id: "crisisDetection",
    name: "Crisis detection",
    icon: Shield,
    desc: "Classify whether a message indicates suicide, DV, trafficking, medical emergency, or safety concern. Only invoked when regex misses.",
    inputTokens: 350,
    outputTokens: 20,
    requirements: [
      "Must not miss genuine crises (false negatives are dangerous)",
      "Catch indirect / paraphrased crisis language",
      "Handle culturally specific expressions",
      "Simple JSON output: {crisis: true/false, category: string}",
      "Fail-open: if uncertain, classify as crisis",
    ],
    recommendation: "sonnet",
    rationale:
      "Safety-critical classification where false negatives have real consequences. Sonnet\u2019s deeper reasoning catches indirect crisis language Haiku may miss. Volume is very low (~5% of turns reach LLM stage) so the 3x cost premium adds negligible total cost.",
  },
  {
    id: "emotionalAck",
    name: "Emotional acknowledgment",
    icon: Heart,
    desc: "Generate a warm, empathetic response when the user shares emotional distress that isn\u2019t crisis-level (\u201CI\u2019m feeling really down\u201D, \u201Chaving a rough day\u201D). Regex catches common phrases; the LLM classifier routes indirect expressions.",
    inputTokens: 280,
    outputTokens: 70,
    requirements: [
      "Lead with acknowledgment \u2014 validate the user\u2019s feeling before anything else",
      "Do NOT list service categories or show a menu of options",
      "Do NOT give medical, psychological, legal, or financial advice",
      "Do NOT diagnose, minimize, or suggest treatments",
      "Mention peer navigator as a human support option",
      "Keep it to 2-3 sentences that feel genuine, not scripted",
    ],
    recommendation: "haiku",
    rationale:
      "This is a short-form generation task (2-3 sentences) with clear guardrails. The output constraints are explicit: don\u2019t list services, don\u2019t give advice, acknowledge the feeling. Haiku\u2019s instruction following is strong for well-specified tasks [5], and its 4-5x speed advantage matters because emotional messages deserve an immediate response, not a noticeable delay. The guardrails are enforced by the prompt, not by model reasoning depth \u2014 Sonnet wouldn\u2019t produce a measurably warmer response given the same constraints. If tone quality becomes a concern, this is a good candidate for A/B testing via the jury eval.",
  },
  {
    id: "botQuestion",
    name: "Bot capability questions",
    icon: HelpCircle,
    desc: "Answer user questions about how the bot works (\u201CWhy couldn\u2019t you get my location?\u201D, \u201CWhat can you search for?\u201D, \u201CDo you work outside NYC?\u201D). Facts about the bot\u2019s capabilities are provided in the prompt.",
    inputTokens: 350,
    outputTokens: 60,
    requirements: [
      "Answer the user\u2019s specific question directly and honestly",
      "Draw from a closed set of facts provided in the system prompt",
      "Be honest about limitations (NYC only, browser location requires permission, etc.)",
      "Keep response to 2-3 sentences",
      "Do not fabricate capabilities the bot doesn\u2019t have",
    ],
    recommendation: "haiku",
    rationale:
      "Factual QA over a closed domain \u2014 all facts about the bot\u2019s capabilities are provided directly in the prompt. The model doesn\u2019t need to reason or infer; it needs to select the relevant fact and phrase it clearly. This is Haiku\u2019s sweet spot: structured input, short output, strong instruction following [5]. Volume is very low (~1-2% of turns), so even if Sonnet were marginally better, the cost and latency difference would not be justified. A static fallback response covers the case when the LLM is unavailable.",
  },
  {
    id: "jury",
    name: "LLM-as-a-jury evaluation",
    icon: Scale,
    desc: "Run the existing eval suite (83 scenarios across 17 categories) with both Haiku and Sonnet performing each LLM task, then have a judge model score both. Produces empirical model-selection data to validate or override the recommendations above.",
    inputTokens: 800,
    outputTokens: 400,
    requirements: [
      "Run each eval scenario twice: once with Haiku, once with Sonnet on each LLM task",
      "Judge model (Sonnet or Opus) scores both runs on the existing 8 rubric dimensions",
      "Compare per-task deltas: where does Haiku match Sonnet? Where does it fall short?",
      "Focus on crisis-category scenarios \u2014 the highest-stakes decisions",
      "Produce a per-task recommendation backed by data, not just reasoning",
    ],
    recommendation: "sonnet",
    rationale:
      "The judge model should be at least as capable as the models being evaluated. The PoLL research (Verga et al., 2024) shows a diverse jury of smaller models can outperform a single large judge, but for same-family comparison (Haiku vs Sonnet), a single Sonnet or Opus judge suffices since intra-model bias is less of a concern within the same family. Use this to validate model choices before deploying \u2014 the ~$50 cost of a full jury run is cheap insurance against deploying the wrong model on crisis detection.",
    isJury: true,
    jurySteps: [
      {
        name: "Fork the eval runner",
        detail:
          "Modify eval_llm_judge.py to accept a --model-config flag that controls which Claude model handles each LLM task.",
      },
      {
        name: "Run paired evaluations",
        detail:
          "Execute the full 83-scenario suite under two configs: (A) All-Haiku and (B) Recommended mix. Each run produces per-scenario scores across 8 dimensions.",
      },
      {
        name: "Head-to-head judging",
        detail:
          "For each scenario, present both transcripts to the judge model side-by-side. Eliminates absolute-score bias.",
      },
      {
        name: "Focus on crisis + edge cases",
        detail:
          "The 9 crisis scenarios, 9 edge-case scenarios, and 10 natural-language scenarios are where model differences are most likely. Flag any scenario where Haiku scored \u22643 on safety_crisis.",
      },
      {
        name: "Produce decision matrix",
        detail:
          "Output: task \u00d7 scenario-category \u2192 Haiku win / Sonnet win / tie. If Haiku matches Sonnet on \u226590% of non-crisis scenarios, the mixed config is validated.",
      },
    ],
    juryCost:
      "~$15-20 per full eval run (83 scenarios \u00d7 ~10 turns \u00d7 judge call). Two paired runs + judging \u2248 $45-55 total.",
    juryInfra:
      "eval_llm_judge.py already has the scenario bank (83 cases across 17 categories), conversation simulator, 8-dimension rubric, and judge prompt. Main change: parameterize which model handles each LLM call.",
  },
  {
    id: "futureMultilang",
    name: "Future: multi-language",
    icon: Languages,
    desc: "The spec calls for English + Spanish minimum. LLM-driven conversation in non-English languages.",
    inputTokens: 250,
    outputTokens: 100,
    requirements: [
      "Natural conversational Spanish",
      "Slot extraction from Spanish input",
      "Cultural competence in language",
    ],
    recommendation: "sonnet",
    rationale:
      "Sonnet 4.6 has significantly stronger multilingual capabilities. When multi-language ships, re-run the jury eval with Spanish-language scenarios to validate empirically.",
  },
];

const SOURCES = [
  {
    id: 1,
    text: "Anthropic \u2014 Introducing Claude Haiku 4.5 (Oct 2025)",
    url: "https://www.anthropic.com/news/claude-haiku-4-5",
    note: "Safety alignment, speed claims, Augment coding eval.",
  },
  {
    id: 2,
    text: "Claude Haiku 4.5 System Card (Oct 2025)",
    url: "https://anthropic.com/claude-haiku-4-5-system-card",
    note: "ASL-2 classification, prompt injection rates.",
  },
  {
    id: 3,
    text: "Artificial Analysis (third-party benchmarking)",
    url: "https://artificialanalysis.ai",
    note: "Latency estimates. Anthropic does not publish specific latency figures.",
  },
  {
    id: 4,
    text: "Claude API Docs \u2014 Extended thinking",
    url: "https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking",
    note: "Adaptive thinking is Opus 4.6 / Sonnet 4.6 only. Haiku 4.5 supports extended thinking with budget_tokens.",
  },
  {
    id: 5,
    text: "MindStudio \u2014 GPT-5.4 Mini vs Haiku comparison (third-party)",
    url: "https://www.mindstudio.ai/blog/gpt-54-mini-vs-claude-haiku-sub-agent-comparison",
    note: "Instruction-following and verbosity observations.",
  },
  {
    id: 6,
    text: "Anthropic \u2014 Introducing Claude Sonnet 4.6 (Feb 2026)",
    url: "https://www.anthropic.com/news/claude-sonnet-4-6",
    note: "94% insurance benchmark is Anthropic-internal. Tool-calling and safety claims.",
  },
  {
    id: 7,
    text: "Anthropic \u2014 Claude Sonnet product page",
    url: "https://www.anthropic.com/claude/sonnet",
    note: "\u201cZero hallucinated links\u201d and \u201c70% more token-efficient\u201d are partner/user quotes.",
  },
  {
    id: 8,
    text: "Claude API Pricing",
    url: "https://docs.anthropic.com/en/about-claude/pricing",
    note: "Haiku 4.5: $1/$5 per MTok. Sonnet 4.6: $3/$15 per MTok. Verified April 2026.",
  },
];

type ConfigId = "recommended" | "allHaiku" | "allSonnet" | "sonnetHeavy";

interface ConfigDef {
  id: ConfigId;
  name: string;
  tag: string;
  desc: string;
  models: {
    conv: "haiku" | "sonnet";
    slots: "haiku" | "sonnet";
    classification: "haiku" | "sonnet";
    crisis: "haiku" | "sonnet";
    emotionalAck: "haiku" | "sonnet";
    botQuestion: "haiku" | "sonnet";
    jury: "sonnet";
    futureMultilang: "sonnet";
  };
}

const CONFIGS: ConfigDef[] = [
  { id: "recommended", name: "Recommended", tag: "Best balance", desc: "Haiku conv + slots + classification + emotional + bot Q, Sonnet crisis", models: { conv: "haiku", slots: "haiku", classification: "haiku", crisis: "sonnet", emotionalAck: "haiku", botQuestion: "haiku", jury: "sonnet", futureMultilang: "sonnet" } },
  { id: "allHaiku", name: "All Haiku", tag: "Cheapest", desc: "Haiku for everything", models: { conv: "haiku", slots: "haiku", classification: "haiku", crisis: "haiku", emotionalAck: "haiku", botQuestion: "haiku", jury: "sonnet", futureMultilang: "sonnet" } },
  { id: "allSonnet", name: "All Sonnet", tag: "Highest quality", desc: "Sonnet for everything", models: { conv: "sonnet", slots: "sonnet", classification: "sonnet", crisis: "sonnet", emotionalAck: "sonnet", botQuestion: "sonnet", jury: "sonnet", futureMultilang: "sonnet" } },
  { id: "sonnetHeavy", name: "Sonnet heavy", tag: "Current pattern", desc: "Sonnet conv + slots, Haiku crisis", models: { conv: "sonnet", slots: "sonnet", classification: "sonnet", crisis: "haiku", emotionalAck: "sonnet", botQuestion: "sonnet", jury: "sonnet", futureMultilang: "sonnet" } },
];

// ---------------------------------------------------------------------------
// HELPERS
// ---------------------------------------------------------------------------

function fmt(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return "<$0.01";
  if (n < 1) return "$" + n.toFixed(3);
  return "$" + n.toFixed(2);
}

function taskCost(
  modelKey: "haiku" | "sonnet",
  taskId: string,
  count: number,
): number {
  const m = MODELS[modelKey];
  const t = TASKS.find((x) => x.id === taskId);
  if (!t) return 0;
  return ((t.inputTokens / 1e6) * m.input + (t.outputTokens / 1e6) * m.output) * count;
}

// ---------------------------------------------------------------------------
// SUB-COMPONENTS
// ---------------------------------------------------------------------------

function ModelBadge({ model }: { model: "haiku" | "sonnet" }) {
  const isHaiku = model === "haiku";
  return (
    <span
      className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-lg ${
        isHaiku
          ? "bg-green-50 text-green-700"
          : "bg-violet-50 text-violet-700"
      }`}
    >
      {isHaiku ? "Haiku 4.5" : "Sonnet 4.6"}
    </span>
  );
}

function ModelCard({ modelKey }: { modelKey: "haiku" | "sonnet" }) {
  const m = MODELS[modelKey];
  const isHaiku = modelKey === "haiku";
  const accent = isHaiku ? "border-t-green-400" : "border-t-violet-400";

  return (
    <div className={`bg-white border border-neutral-200 rounded-lg p-4 border-t-[3px] ${accent}`}>
      <div className="flex items-baseline justify-between mb-2.5">
        <span className={`text-base font-bold ${isHaiku ? "text-green-700" : "text-violet-700"}`}>
          {m.name}
        </span>
        <span className="text-xs font-mono text-neutral-400">
          ${m.input}/${m.output}/MTok
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-neutral-500 mb-3">
        <span>Speed: {m.speed}</span>
        <span>Context: {m.context}</span>
        <span>Latency: {m.latency}</span>
        <span>
          ID: <code className="text-[0.65rem] bg-neutral-100 px-1 rounded">{m.id.split("-").slice(0, 3).join("-")}</code>
        </span>
      </div>

      <div className="mb-2">
        <div className="text-[0.65rem] font-bold uppercase tracking-wider text-green-600 mb-1">
          Strengths
        </div>
        {m.strengths.slice(0, 4).map((s, i) => (
          <div key={i} className="text-xs text-neutral-600 leading-relaxed flex gap-1.5">
            <span className="text-green-500 flex-shrink-0">+</span>
            <span>{s}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="text-[0.65rem] font-bold uppercase tracking-wider text-red-500 mb-1">
          Weaknesses
        </div>
        {m.weaknesses.slice(0, 3).map((w, i) => (
          <div key={i} className="text-xs text-neutral-600 leading-relaxed flex gap-1.5">
            <span className="text-red-400 flex-shrink-0">&minus;</span>
            <span>{w}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TaskRow({ task }: { task: TaskDef }) {
  const [open, setOpen] = useState(false);
  const Icon = task.icon;

  return (
    <div
      className={`border rounded-lg overflow-hidden ${
        task.isJury ? "border-amber-300 bg-white" : "bg-white border-neutral-200"
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-neutral-50/60 transition-colors"
      >
        <Icon size={16} className="text-neutral-400 flex-shrink-0" />
        <span className="text-sm font-semibold flex-1">{task.name}</span>
        <ModelBadge model={task.recommendation} />
        <ChevronDown
          size={14}
          className={`text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-neutral-100">
          <p className="text-xs text-neutral-500 mt-3 mb-3 leading-relaxed">
            {task.desc}
          </p>

          {/* Requirements / methodology */}
          <div className="text-[0.65rem] font-bold uppercase tracking-wider text-neutral-400 mb-1.5">
            {task.isJury ? "Methodology" : "Requirements"}
          </div>
          <div className="mb-3">
            {task.requirements.map((r, i) => (
              <div key={i} className="text-xs text-neutral-600 leading-relaxed pl-3 -indent-3">
                &bull; {r}
              </div>
            ))}
          </div>

          {/* Jury steps */}
          {task.isJury && task.jurySteps && (
            <div className="mb-4">
              <div className="text-[0.65rem] font-bold uppercase tracking-wider text-neutral-400 mb-2">
                Evaluation design
              </div>
              <div className="flex flex-col gap-2">
                {task.jurySteps.map((step, i) => (
                  <div key={i} className="flex gap-3 items-start">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-amber-500 text-white text-[0.65rem] font-bold flex items-center justify-center mt-0.5">
                      {i + 1}
                    </span>
                    <div>
                      <div className="text-xs font-semibold">{step.name}</div>
                      <div className="text-xs text-neutral-500 leading-relaxed">
                        {step.detail}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {task.juryCost && (
                <div className="mt-3 text-xs bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                  <strong className="text-amber-700">Est. cost:</strong>{" "}
                  <span className="text-neutral-600">{task.juryCost}</span>
                </div>
              )}
              {task.juryInfra && (
                <div className="mt-1.5 text-xs bg-amber-50/60 border border-amber-200/60 rounded-md px-3 py-2">
                  <strong className="text-amber-700">Existing infrastructure:</strong>{" "}
                  <span className="text-neutral-600">{task.juryInfra}</span>
                </div>
              )}
            </div>
          )}

          {/* Rationale */}
          <div
            className={`rounded-md px-3 py-2.5 ${
              task.isJury
                ? "bg-amber-50 border border-amber-200"
                : task.recommendation === "haiku"
                  ? "bg-green-50/60 border border-green-200/60"
                  : "bg-violet-50/60 border border-violet-200/60"
            }`}
          >
            <div
              className={`text-[0.65rem] font-bold uppercase tracking-wider mb-1 ${
                task.isJury
                  ? "text-amber-600"
                  : task.recommendation === "haiku"
                    ? "text-green-600"
                    : "text-violet-600"
              }`}
            >
              {task.isJury
                ? "Why run this"
                : `Why ${MODELS[task.recommendation].name}`}
            </div>
            <div className="text-xs text-neutral-700 leading-relaxed">
              {task.rationale}
            </div>
          </div>

          {/* Token info */}
          {!task.isJury && (
            <div className="flex gap-4 mt-2.5 text-[0.65rem] text-neutral-400">
              <span>~{task.inputTokens} input tok/call</span>
              <span>~{task.outputTokens} output tok/call</span>
              <span>
                Cost/call:{" "}
                {fmt(
                  (task.inputTokens / 1e6) * MODELS[task.recommendation].input +
                    (task.outputTokens / 1e6) *
                      MODELS[task.recommendation].output,
                )}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MAIN PAGE COMPONENT
// ---------------------------------------------------------------------------

export function ModelAnalysis() {
  const [monthlyUsers, setMonthlyUsers] = useState(2000);
  const [turnsPerSession, setTurnsPerSession] = useState(5);
  const [llmSlotPct, setLlmSlotPct] = useState(30);
  const [crisisLlmPct, setCrisisLlmPct] = useState(5);
  const [conversationalPct, setConversationalPct] = useState(20);
  const [classificationPct, setClassificationPct] = useState(15);
  const [emotionalPct, setEmotionalPct] = useState(5);
  const [botQuestionPct, setBotQuestionPct] = useState(2);
  const [includeJury, setIncludeJury] = useState(false);
  const [includeMultilang, setIncludeMultilang] = useState(false);
  const [activeConfig, setActiveConfig] = useState<ConfigId>("recommended");

  const totalTurns = monthlyUsers * turnsPerSession;
  const conversationalTurns = Math.round(totalTurns * (conversationalPct / 100));
  const slotTurns = Math.round(totalTurns * (llmSlotPct / 100));
  const crisisTurns = Math.round(totalTurns * (crisisLlmPct / 100));
  const classificationTurns = Math.round(totalTurns * (classificationPct / 100));
  const emotionalTurns = Math.round(totalTurns * (emotionalPct / 100));
  const botQuestionTurns = Math.round(totalTurns * (botQuestionPct / 100));
  // Jury: ~83 scenarios × 2 configs × ~10 turns × judge call, once per month
  const juryTurns = includeJury ? 1660 : 0;
  // Future multi-language: assume same conversational volume
  const multilangTurns = includeMultilang ? conversationalTurns : 0;

  const configsWithCost = CONFIGS.map((c) => {
    const bd = {
      conv: taskCost(c.models.conv, "conversational", conversationalTurns),
      slots: taskCost(c.models.slots, "slotExtraction", slotTurns),
      classification: taskCost(c.models.classification, "classification", classificationTurns),
      crisis: taskCost(c.models.crisis, "crisisDetection", crisisTurns),
      emotionalAck: taskCost(c.models.emotionalAck, "emotionalAck", emotionalTurns),
      botQuestion: taskCost(c.models.botQuestion, "botQuestion", botQuestionTurns),
      jury: includeJury ? taskCost(c.models.jury, "jury", juryTurns) : 0,
      futureMultilang: includeMultilang ? taskCost(c.models.futureMultilang, "futureMultilang", multilangTurns) : 0,
    };
    return { ...c, breakdown: bd, total: Object.values(bd).reduce((a, b) => a + b, 0) };
  });

  const config = configsWithCost.find((c) => c.id === activeConfig)!;

  // Build the list of tasks to display in the config detail grid.
  const activeTasks: { key: string; label: string; model: "haiku" | "sonnet"; cost: number; count: number }[] = [
    { key: "conv", label: "Conversational", model: config.models.conv, cost: config.breakdown.conv, count: conversationalTurns },
    { key: "slots", label: "Slot extraction", model: config.models.slots, cost: config.breakdown.slots, count: slotTurns },
    { key: "classification", label: "Classification", model: config.models.classification, cost: config.breakdown.classification, count: classificationTurns },
    { key: "crisis", label: "Crisis detection", model: config.models.crisis, cost: config.breakdown.crisis, count: crisisTurns },
    { key: "emotionalAck", label: "Emotional ack.", model: config.models.emotionalAck, cost: config.breakdown.emotionalAck, count: emotionalTurns },
    { key: "botQuestion", label: "Bot questions", model: config.models.botQuestion, cost: config.breakdown.botQuestion, count: botQuestionTurns },
  ];
  if (includeJury) {
    activeTasks.push({ key: "jury", label: "Jury evaluation", model: config.models.jury, cost: config.breakdown.jury, count: juryTurns });
  }
  if (includeMultilang) {
    activeTasks.push({ key: "futureMultilang", label: "Multi-language", model: config.models.futureMultilang, cost: config.breakdown.futureMultilang, count: multilangTurns });
  }

  return (
    <>
      {/* Intro banner */}
      <div className="bg-white border border-neutral-200 rounded-lg px-3.5 py-2.5 text-sm text-neutral-500 mb-6">
        Claude model cost and capability analysis for each LLM-powered task in
        the chatbot. All pricing from{" "}
        <a
          href="https://docs.anthropic.com/en/about-claude/pricing"
          target="_blank"
          rel="noopener noreferrer"
          className="text-amber-600 hover:underline"
        >
          Anthropic official docs
        </a>
        . Recommendations are preliminary &mdash; run the jury evaluation to
        validate before deploying major changes.
      </div>

      {/* Model cards */}
      <h2 className="text-xs font-bold uppercase tracking-widest text-neutral-400 mb-3 pb-2 border-b border-neutral-200">
        Model comparison
      </h2>
      <div className="grid grid-cols-2 gap-3 mb-8">
        <ModelCard modelKey="haiku" />
        <ModelCard modelKey="sonnet" />
      </div>

      {/* Per-task recommendations */}
      <h2 className="text-xs font-bold uppercase tracking-widest text-neutral-400 mb-3 pb-2 border-b border-neutral-200">
        Per-task model recommendations
      </h2>
      <div className="flex flex-col gap-2 mb-8">
        {TASKS.map((t) => (
          <TaskRow key={t.id} task={t} />
        ))}
      </div>

      {/* Cost calculator */}
      <h2 className="text-xs font-bold uppercase tracking-widest text-neutral-400 mb-3 pb-2 border-b border-neutral-200">
        Monthly cost calculator
      </h2>

      <div className="bg-white border border-neutral-200 rounded-lg px-4 py-4 mb-4">
        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
          <SliderField label="Monthly users" value={monthlyUsers} onChange={setMonthlyUsers} min={100} max={50000} step={100} format={(v) => v.toLocaleString()} />
          <SliderField label="Turns per session" value={turnsPerSession} onChange={setTurnsPerSession} min={1} max={20} step={1} />
          <SliderField label="% needing LLM slots" value={llmSlotPct} onChange={setLlmSlotPct} min={0} max={100} step={5} format={(v) => v + "%"} />
          <SliderField label="% hitting LLM crisis" value={crisisLlmPct} onChange={setCrisisLlmPct} min={0} max={30} step={1} format={(v) => v + "%"} />
          <SliderField label="% conversational LLM" value={conversationalPct} onChange={setConversationalPct} min={0} max={60} step={5} format={(v) => v + "%"} />
          <SliderField label="% LLM classification" value={classificationPct} onChange={setClassificationPct} min={0} max={50} step={5} format={(v) => v + "%"} />
          <SliderField label="% emotional responses" value={emotionalPct} onChange={setEmotionalPct} min={0} max={20} step={1} format={(v) => v + "%"} />
          <SliderField label="% bot questions" value={botQuestionPct} onChange={setBotQuestionPct} min={0} max={10} step={1} format={(v) => v + "%"} />
        </div>

        <div className="flex gap-4 mt-4 pt-3 border-t border-neutral-100">
          <ToggleField label="LLM-as-a-jury evaluation" checked={includeJury} onChange={setIncludeJury} detail="~$45-55 per monthly run" />
          <ToggleField label="Future: multi-language" checked={includeMultilang} onChange={setIncludeMultilang} detail="Sonnet for non-English" />
        </div>

        <div className="text-xs text-neutral-400 mt-3">
          {totalTurns.toLocaleString()} total turns &middot;{" "}
          {conversationalTurns.toLocaleString()} conv &middot;{" "}
          {slotTurns.toLocaleString()} slot &middot;{" "}
          {classificationTurns.toLocaleString()} classify &middot;{" "}
          {crisisTurns.toLocaleString()} crisis &middot;{" "}
          {emotionalTurns.toLocaleString()} emotional &middot;{" "}
          {botQuestionTurns.toLocaleString()} bot Q
          {includeJury && <> &middot; {juryTurns.toLocaleString()} jury</>}
          {includeMultilang && <> &middot; {multilangTurns.toLocaleString()} multilang</>}
        </div>
      </div>

      {/* Config selector */}
      <div className="grid grid-cols-4 gap-2 mb-4">
        {configsWithCost.map((c) => (
          <button
            key={c.id}
            onClick={() => setActiveConfig(c.id)}
            className={`py-2.5 px-2 rounded-lg text-center transition-all ${
              activeConfig === c.id
                ? "bg-neutral-900 text-white border-2 border-neutral-900"
                : "bg-white text-neutral-700 border border-neutral-200 hover:border-neutral-300"
            }`}
          >
            <div className="text-xs font-semibold">{c.name}</div>
            <div className="text-[0.65rem] opacity-70 mt-0.5">{c.tag}</div>
            <div className="text-base font-bold font-mono mt-1">{fmt(c.total)}</div>
          </button>
        ))}
      </div>

      {/* Config detail */}
      <div className="bg-white border border-neutral-200 rounded-lg overflow-hidden mb-6">
        <div className="px-4 py-3 border-b border-neutral-100 flex items-center justify-between">
          <div>
            <div className="text-sm font-bold">{config.name}</div>
            <div className="text-xs text-neutral-400 mt-0.5">{config.desc}</div>
          </div>
          <div className="text-right">
            <span className="text-2xl font-bold font-mono">{fmt(config.total)}</span>
            <span className="text-xs text-neutral-400">/mo</span>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
          {activeTasks.map((item, idx) => (
            <div
              key={item.key}
              className={`px-4 py-3 border-b border-neutral-100 ${(idx + 1) % 4 !== 0 ? "border-r" : ""} last:border-b-0`}
            >
              <div className="text-[0.65rem] font-bold uppercase tracking-wider text-neutral-400 mb-1">
                {item.label}
              </div>
              <ModelBadge model={item.model} />
              <div className="text-lg font-bold font-mono mt-1.5">
                {fmt(item.cost)}
              </div>
              <div className="text-[0.65rem] text-neutral-400">
                {item.count.toLocaleString()} calls
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Scale projection */}
      <div className="bg-white border border-neutral-200 rounded-lg px-4 py-3 mb-6">
        <div className="text-xs font-semibold mb-2">
          Scale projection (recommended config)
        </div>
        <div className="grid grid-cols-4 gap-2">
          {[2000, 10000, 36000, 50000].map((users) => {
            const turns = users * turnsPerSession;
            let t =
              ((200 / 1e6) * 1 + (80 / 1e6) * 5) *
                Math.round(turns * (conversationalPct / 100)) +
              ((450 / 1e6) * 1 + (60 / 1e6) * 5) *
                Math.round(turns * (llmSlotPct / 100)) +
              ((300 / 1e6) * 1 + (10 / 1e6) * 5) *
                Math.round(turns * (classificationPct / 100)) +
              ((350 / 1e6) * 3 + (20 / 1e6) * 15) *
                Math.round(turns * (crisisLlmPct / 100)) +
              ((280 / 1e6) * 1 + (70 / 1e6) * 5) *
                Math.round(turns * (emotionalPct / 100)) +
              ((350 / 1e6) * 1 + (60 / 1e6) * 5) *
                Math.round(turns * (botQuestionPct / 100));
            if (includeJury) t += ((800 / 1e6) * 3 + (400 / 1e6) * 15) * juryTurns;
            if (includeMultilang) t += ((250 / 1e6) * 3 + (100 / 1e6) * 15) * Math.round(turns * (conversationalPct / 100));
            return (
              <div key={users} className="text-center py-1.5">
                <div className="text-xs text-neutral-500">
                  {users === 36000 ? "AI capacity" : users.toLocaleString() + " users"}
                </div>
                <div className="text-lg font-bold font-mono">{fmt(t)}</div>
                <div className="text-[0.65rem] text-neutral-400">/month</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sources */}
      <details className="mb-4">
        <summary className="text-xs font-bold uppercase tracking-widest text-neutral-400 cursor-pointer hover:text-neutral-600 pb-2 border-b border-neutral-200">
          Sources &amp; methodology
        </summary>
        <div className="mt-3 space-y-1.5">
          {SOURCES.map((s) => (
            <div key={s.id} className="text-xs text-neutral-500 leading-relaxed">
              <span className="text-neutral-400">[{s.id}]</span>{" "}
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-amber-600 hover:underline"
              >
                {s.text}
                <ExternalLink size={10} className="inline ml-0.5 -mt-0.5" />
              </a>
              {" \u2014 "}
              {s.note}
            </div>
          ))}
          <div className="text-xs text-neutral-400 mt-2 pt-2 border-t border-neutral-100">
            Token estimates derived from inspecting the YourPeer codebase system
            prompts, tool schemas, and response constraints.
          </div>
        </div>
      </details>
    </>
  );
}

// ---------------------------------------------------------------------------
// Slider sub-component
// ---------------------------------------------------------------------------

function SliderField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  format,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  format?: (v: number) => string;
}) {
  return (
    <label className="block">
      <div className="flex justify-between mb-0.5">
        <span className="text-xs text-neutral-600">{label}</span>
        <span className="text-xs font-mono font-semibold text-neutral-900">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-neutral-800"
      />
    </label>
  );
}

function ToggleField({
  label,
  detail,
  checked,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 rounded border-neutral-300 text-amber-500 accent-amber-500 cursor-pointer"
      />
      <div>
        <span className="text-xs font-medium text-neutral-700">{label}</span>
        <span className="text-[0.65rem] text-neutral-400 ml-1.5">{detail}</span>
      </div>
    </label>
  );
}
