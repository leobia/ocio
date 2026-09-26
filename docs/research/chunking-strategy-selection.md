# Selezione delle strategie di chunking

Verifica delle fonti: 26 settembre 2026. Ambito: corpus normativo e ufficiale di OCIO.

## Conclusione

Ridurre il confronto a due chunker:

1. finestra fissa;
2. strutturale adattivo.

Valutare l'espansione al parent come opzione `on/off` per entrambi. Il contenitore semantico intero può restare una baseline diagnostica, ma non richiede una terza implementazione: è il caso limite dello strutturale in cui l'unità entra nel limite dimensionale.

La letteratura non giustifica l'eliminazione della finestra fissa prima di un benchmark locale. Non fissare inoltre `512/64` come scelta definitiva: dimensione e overlap sono iperparametri, non strategie.

## Evidenza

| Proposta iniziale | Decisione | Motivo |
|---|---|---|
| Contenitore semantico intero | Solo baseline | Preserva il contesto, ma per contenitori lunghi introduce rumore; è già rappresentabile dallo strutturale adattivo. |
| Unità precisa + parent | Riclassificare | Il child è l'unità indicizzata; restituire il parent è una politica di espansione del contesto, combinabile con chunk fissi o strutturali. La letteratura descrive esplicitamente lo *small-to-big retrieval* come recupero su chunk piccoli e ritorno di blocchi maggiori ([Zhong et al., COLING 2025](https://aclanthology.org/2025.coling-main.384/)). |
| Finestra fissa con overlap | Mantenere | Il chunking semantico non produce vantaggi abbastanza consistenti da giustificarne sempre il costo; la finestra fissa resta un controllo semplice e serio ([Qu et al., NAACL 2025](https://aclanthology.org/2025.findings-naacl.114/)). |
| Strutturale adattivo | Mantenere | Sul codice civile tedesco, sezioni e sottosezioni ottengono il recall migliore e costano meno dei metodi complessi ([Prior et al., ASAIL 2026](https://arxiv.org/abs/2605.19806)). Anche NitiBench rileva un vantaggio, seppur piccolo, dei componenti sensibili alla gerarchia nel legal QA ([Akarajaradwong et al., EMNLP 2025](https://aclanthology.org/2025.emnlp-main.1739/)). |

Altri risultati impediscono di dichiarare un vincitore universale:

- unità fini e autocontenute possono battere passaggi più grandi nel retrieval e nel QA, ma l'esperimento riguarda Wikipedia e dense retrieval ([Chen et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-main.845/));
- la dimensione ottimale dei chunk fissi varia con dataset e modello di embedding; lo studio confronta `64–1024` token e non usa overlap ([Bhat et al., 2025](https://arxiv.org/abs/2505.21700));
- in RAGChecker, variare l'overlap ha un effetto minimo sulla generazione, quindi `64` token di overlap non sono un default dimostrato ([Ru et al., NeurIPS 2024](https://openreview.net/forum?id=J9oefdGUuM));
- nei corpus legali con documenti simili, aggiungere contesto globale ai chunk riduce il recupero dal documento sbagliato: il contesto del parent può essere utile, ma ciò non dimostra che vada sempre restituito integralmente ([Reuter et al., NLLP 2025](https://aclanthology.org/2025.nllp-1.3/)).

## Benchmark minimo

```text
chunker:          fixed | structural
parent_expansion: off   | on
```

Per `fixed`, partire con overlap `0` e aggiungere un valore non nullo solo come ablation. Per entrambi, misurare almeno recall delle partizioni attese, precisione del contesto, costo dell'indice e qualità della risposta. Il risultato deve essere letto separatamente per domande puntuali e domande che richiedono più partizioni.

Questa conclusione è una riduzione dello spazio progettuale, non la scelta del vincitore: le fonti usano lingue, corpora, retriever e metriche diversi da OCIO.
