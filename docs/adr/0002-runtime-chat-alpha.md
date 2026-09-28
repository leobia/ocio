# 0002 — Runtime chat dell'alpha

## Stato

Accettata il 28 settembre 2026.

## Decisione

La chat usa una composizione Python esplicita e configurata server-side in
`config/chat-runtime-v1.yaml`.

- `local`: `gpt-6-luna` per rewrite, sufficiency e risposta; retrieval
  `text-embedding-3-large` senza reranker.
- `alpha`: `gpt-6-luna` per rewrite, sufficiency e risposta grounded, poi
  `rerank-v4.0-pro` sui 20 candidati dense e 10 evidenze finali.
- Non c'è escalation automatica: `alpha-escalated` replica la pipeline alpha con
  `gpt-6-sol` in generazione, per misurare separatamente l'eventuale beneficio.

L'evaluation del 28 settembre 2026 sui 20 casi esistenti ha ottenuto 18/20 per
entrambi i profili. Luna ha avuto latenza media 6,62 s contro 7,51 s di Sol; i
fallimenti sono gli stessi (`silver-0013` e `silver-0016`). Sol non viene quindi
promosso nel profilo alpha: non ha mostrato un miglioramento che ne giustifichi
costo e latenza maggiori.

Il retrieval riprende il benchmark esistente: dense-large ha ottenuto
Evidence Recall@10 pari a 1,0; Cohere ha portato MRR@10 da 0,773 a 1,0 sui 18
casi rispondibili. I modelli LLM seguono i ruoli indicati dalla
[documentazione OpenAI](https://developers.openai.com/api/docs/guides/model-selection):
modello efficiente per compiti stretti e modello bilanciato quando conta la
qualità della risposta. La promozione resta subordinata all'evaluation OCIO.

Le chiavi restano nell'ambiente server. OpenAI riceve solo domanda, contesto
limitato ed evidenze necessarie con `store=false`; l'alpha usa esclusivamente
casi fittizi o redatti, coerentemente con la ricerca privacy del progetto.
Timeout e retry sono comuni alle chiamate OpenAI; Cohere usa lo stesso timeout.
Un `429` esauriti i retry fallisce in modo sicuro: non aggiungiamo un rate limiter
locale prima di autenticazione e deploy (#21). Senza profilo esplicito la chat
resta indisponibile con errore 503 sicuro.
