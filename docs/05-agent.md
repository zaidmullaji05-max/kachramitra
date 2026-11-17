# 05 — The chat agent (tools + RAG + guardrails)

## 1. What replaced the single-shot chatbot

In step 4 `/chat` was one LLM call with the scan as context. Step 5 turns it into a
**bounded tool-calling agent**:

```
message ──► system prompt (rules + language + scan context)
          ──► LLM picks tools (0..n)
          ──► each tool runs with a 10 s timeout, inside a 4-hop budget
          ──► post-filter (banned advice, length, citations)
          ──► answer + warnings + facilities + sources + tool_trace
```

If there is no API key, or the provider times out, or the loop runs out of hops without
text, the deterministic rule card answers instead. **The user always gets an answer.**

| File | Role |
|---|---|
| `backend/app/knowledge.py` | BM25 index over `backend/knowledge/*.md` |
| `backend/app/tools.py` | four tools + JSON schemas for the LLM |
| `backend/app/agent.py` | the loop, session memory, post-filter, fallback |
| `backend/app/chat.py` | prompt, rule cards, item card (reused by the agent) |
| `backend/app/safety.py` | hazard warnings and PII redaction, injected server-side |

## 2. The four tools

| Tool | Input | Returns | Used for |
|---|---|---|---|
| `search_rules` | `query`, `k` | numbered excerpts + title + URL + score | any rule/bin/composting question |
| `get_item_guide` | `item` | category, bin, steps, do-not, hazards, rules | disposal steps for a specific item |
| `find_facilities` | `category`, `lat`, `lng`, `radius_m` | 5 nearest points with address/hours/distance | "where do I drop this" |
| `classify_image` | `image_base64`, `hint` | item, category, confidence, top-k | the user attached a photo |

Every tool returns `{"summary": "..."}` as well, which is what shows up in
`tool_trace`. Errors become `{"error": "..."}` instead of exceptions, so a failed tool
does not 500 the conversation — the model can retry or the agent falls back.

The schemas are plain OpenAI function-calling JSON (see `TOOL_SCHEMAS`). Groq and Gemini
both accept them through their OpenAI-compatible endpoints, so no provider-specific code.

## 3. Retrieval: why BM25, not a vector DB

The corpus is **6 markdown files / 40 chunks / ~15 KB**. A vector database would add an
embedding model, a network hop, a cost line, and an index to rebuild for no measurable
quality gain at this size.

`knowledge.py` implements BM25 by hand (~120 lines):

- chunks split on `##` headings, front-matter parsed for `title` / `source`
- Unicode-aware tokenizer that keeps Devanagari and does cheap singularisation
- `k1 = 1.5`, `b = 0.75`, min score 0.35, max 5 results
- `lru_cache` on the index; the whole thing loads in milliseconds

Measured on the shipped corpus:

```
{'docs': 6, 'chunks': 40, 'terms': 890, 'avg_tokens': 57.4}

broken tube light mercury      -> Practical guide | Common items
                                 E-Waste 2022 | Practical guidance
battery swollen                -> Battery 2022 | What if a battery is swollen or burning
single use plastic sachet      -> Plastic Rules | Multi-layer packaging (MLP)
used syringe needle            -> Bio-Medical 2016 | Household sharps
which bin for vegetable peels  -> Practical guide | The three-bin setup
```

When the corpus grows past a few hundred chunks, replace `KnowledgeBase.search()` with
embeddings + pgvector. The tool interface does not change.

## 4. The loop, precisely

```python
for hop in range(1, MAX_HOPS + 1):          # 4
    reply = await wait_for(provider.complete(messages, tools=TOOL_SCHEMAS), llm_timeout_s)
    if not reply.tool_calls:
        text = reply.text
        break
    for call in reply.tool_calls:
        result = await wait_for(run_tool(call.name, args), TOOL_TIMEOUT_S)   # 10 s
        messages.append(tool_result_message(call, result))
```

Details that matter:

- **`image_base64` injection.** If the model calls `classify_image` without bytes, the
  agent fills them from the request. Small models forget arguments; this makes the
  attachment path reliable.
- **Turn budget.** After 4 hops the loop stops calling tools even if the model asks,
  then uses whatever text it has. This bounds latency and cost.
- **Tool output truncation.** JSON is capped at 6 000 chars before it goes back into the
  context, so one verbose tool cannot blow the window.
- **Session memory.** Last 6 user/assistant turns in an in-process dict, 30-minute TTL,
  500-session cap. Tool messages are **not** replayed; they are already reflected in the
  answer, and replaying them would grow the context every turn.
- **Reset.** `POST /chat/reset?session_id=...` drops the session. The UI calls it on
  "New chat".

## 5. Guardrails (defence in depth)

| Layer | Where | What it stops |
|---|---|---|
| Refusal pre-filter | `safety.refusal_reason` | medical/legal advice, explosives |
| Prompt rules | `SYSTEM_PROMPT` | burning, drains, informal e-waste dealers, invented facilities |
| Hard-coded hazards | `safety.warnings_for` | battery/mercury/sharps text the LLM cannot paraphrase away |
| Post-filter | `agent._post_filter` | "burn it", "flush it", "give it to the scrap dealer", "bury it" |
| Citation check | `agent.run` | rule claims with no retrieved source get a KB lookup attached |
| Length cap | `agent._respond` | 2 400 chars, so a runaway answer cannot fill the phone |
| PII redaction | `safety.redact` | phone numbers / emails before feedback is stored |

Hazard warnings are **added on the server after** the model speaks, from the item's flags.
A hallucinating LLM cannot remove them. This is the single most important safety decision
in the project.

## 6. Failure matrix

| Situation | Behaviour | `tool_trace` |
|---|---|---|
| `LLM_PROVIDER=fake` (default, no key) | rule card; image still classified | `classify_image: …`, `rules` |
| Provider 429 / timeout | rule card | `llm_failed`, `rules` |
| Loop exceeds 4 hops | best available text, else rule card | `max_hops`, maybe `rules` |
| Model says "burn it" | answer replaced by rule card | `blocked:burn it`, `rules` |
| Tool raises | tool result is an error dict; loop continues | `search_rules: search_rules failed` |
| No location | `find_facilities` returns an error; model asks for location | `find_facilities: facility search needs lat/lng` |
| Out-of-scope request | fixed refusal, no LLM call | `refused` |

## 7. Cost and latency (free tier reality)

| Path | Calls | Typical latency | Cost |
|---|---|---|---|
| no key (rule cards) | 0 | < 50 ms + ONNX inference | ₹0 |
| Groq `llama-3.3-70b-versatile` | 1–3 | 1–4 s | free tier, rate-limited |
| Gemini 2.5 Flash | 1–3 | 2–6 s | free tier |

Rate limiting is 30 req/min/IP in `main.py`. With one key and a classroom demo, that is
plenty; a public launch needs per-device quotas and a queue.

## 8. How to evaluate the agent (not just vibe-check it)

Keep a small file of gold questions and expected facts, then assert on the answer:

```python
CASES = [
    ("Where does a broken CFL go?", ["e-waste", "mercury"]),
    ("Can I put a battery in the dry bin?", ["no", "collection"]),
    ("Is a chips packet recyclable?", ["not recyclable", "multi-layer"]),
]
```

Run with the real provider once per prompt change, and with the fake provider in CI. Track:
tool selection accuracy, citation rate, refusal correctness, and latency. Do **not** tune
the prompt against 3 questions and call it done.

## 9. Extending it

- **New rule document:** drop a `.md` with front-matter in `backend/knowledge/`; no code
  change. The index rebuilds on restart.
- **New tool:** write an async function, add its schema, add it to `REGISTRY`. Keep the
  return shape `{..., "summary": str}`.
- **Persistent memory:** swap `SessionStore` for Redis/Postgres keyed by `session_id`.
  The agent only calls `get`, `remember`, `reset`.
- **Streaming:** the loop is already async; stream the final `provider.complete` text to
  the UI with SSE when you need token-by-token output.
