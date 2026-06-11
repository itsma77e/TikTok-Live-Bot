# TikTok Speech Bot

Un assistente vocale per le tue dirette **TikTok**: legge la chat, risponde con
l'AI ai comandi `/bot`, e **parla ad alta voce** la risposta dal PC. Ringrazia
follower e regali, ricorda cosa è stato detto nelle live passate e può cercare
sul web. Tutto si controlla da una **dashboard web** locale — niente da editare
a mano.

> ⚠️ Usa la libreria non ufficiale [TikTokLive](https://github.com/isaackogan/TikTokLive)
> per leggere la chat. Non è affiliata a TikTok: usala a tuo rischio.

---

## Cosa fa

- **Risposte AI in chat** — quando uno spettatore scrive `/bot <domanda>`, il bot
  genera una risposta e la pronuncia ad alta voce.
- **Voce (TTS)** — voci cloud gratuite (Microsoft Edge) o locali offline
  (Supertonic, gira su CPU).
- **Ringraziamenti automatici** — saluta i nuovi follower e ringrazia chi manda
  regali (attivabili/disattivabili dalla UI).
- **Memoria a lungo termine** — ricorda cosa è stato detto nelle live (anche di
  giorni prima) e lo richiama quando serve.
- **Ricerca web** — opzionale, tramite Tavily.
- **Dashboard** — due schede: **Chat** (connessione + feed live) e
  **Impostazioni** (modello AI, chiavi, system prompt, voce, ringraziamenti,
  visualizzatore della memoria).

## Modelli AI

Scegli il modello dalla dashboard; il provider è gestito sotto il cofano.

| Modello | Dove gira | Note |
|---|---|---|
| **GPT-4o mini** (consigliato) | cloud OpenAI | Facile, affidabile, costa centesimi. Serve una API key. |
| **Llama 3.1 8B / Qwen 2.5 7B / Gemma 3 4B** | locale via [Ollama](https://ollama.com) | Gratis e privato, ma serve un PC discreto. I modelli piccoli usano i tool (ricerca/memoria) in modo meno affidabile. |

Per i modelli locali: installa [Ollama](https://ollama.com) e scarica il modello
una volta, es:

```bash
ollama pull llama3.1:8b
```

> La **memoria** usa sempre gli embedding di OpenAI: per averla serve la chiave
> OpenAI anche quando il modello di chat è locale. Senza chiave, la memoria è
> semplicemente disattivata.

## Requisiti

- Python 3.10+
- (Opzionale) [Ollama](https://ollama.com) per i modelli locali
- Una chiave [OpenAI](https://platform.openai.com/api-keys) per il modello cloud
  e/o la memoria
- (Opzionale) una chiave [Tavily](https://app.tavily.com) per la ricerca web

## Installazione

```bash
git clone <url-del-repo>
cd tiktok-speech-bot

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Le chiavi API puoi inserirle **direttamente dalla dashboard** (scheda
Impostazioni). In alternativa, copia `.env.example` in `.env` e compilale lì:

```bash
cp .env.example .env
```

## Avvio

```bash
python main.py
```

Apri **http://localhost:8000** nel browser.

1. Scheda **Impostazioni**: scegli il modello, incolla la chiave OpenAI (e Tavily
   se vuoi la ricerca web), regola system prompt / voce / ringraziamenti, salva.
2. Scheda **Chat**: scrivi lo username TikTok della tua live e premi **Connetti**.
3. In live, chiunque scriva `/bot <domanda>` riceve una risposta letta ad alta
   voce dal tuo PC.

I settaggi vengono salvati su disco (`data/settings.json`, locale) e
sopravvivono al riavvio.

## Privacy / dati

- Chiavi API e settaggi restano **solo sul tuo PC** (cartella `data/`, ignorata
  da git).
- La memoria della chat è salvata localmente in `data/memory/`. La puoi
  consultare e svuotare dalla dashboard.

## Licenza

[PolyForm Noncommercial 1.0.0](LICENSE.md) — uso libero per scopi **non
commerciali**. Non è permesso vendere il software o offrirlo come servizio a
pagamento.
