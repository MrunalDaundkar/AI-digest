# AI Digest

A free, automatic daily AI news digest. It collects technical news (TLDR, lab blogs, arXiv, Hugging Face trending models and papers) and business and market news, ranks it, writes short summaries with an LLM, and publishes a website that works on laptop and phone.

Every morning: GitHub Actions runs `pipeline/digest.py` → writes `docs/data/DATE.json` → GitHub Pages serves `docs/`. No server, no database, $0.

## Setup (about 20 minutes, once)

1. **GitHub account and repo.** Sign up at github.com, click New repository, name it `ai-digest`, choose **Public** (unlimited free Actions minutes).
2. **Upload the files.** Unzip this project. On the repo page click *Add file → Upload files* and drag in everything, including the hidden `.github` folder (if your system hides it, use git instead):
   ```
   cd ai-digest
   git init && git add . && git commit -m "first commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/ai-digest.git
   git push -u origin main
   ```
3. **Get a free Gemini key.** Go to aistudio.google.com, sign in, click *Get API key*, create one, copy it.
4. **Save the key as a secret.** Repo → *Settings → Secrets and variables → Actions → New repository secret*. Name: `GEMINI_API_KEY`. Value: your key. Never paste keys into code or chat.
5. **Allow the bot to save results.** Repo → *Settings → Actions → General → Workflow permissions → Read and write permissions → Save*.
6. **Run it once.** Repo → *Actions* tab → *Daily AI digest* → *Run workflow*. Open the run and the "Build digest" step. Lines starting `ok` are good; `FAIL` lines are feeds that need fixing (see below). It should end with `done: …`.
7. **Turn on the website.** Repo → *Settings → Pages* → Source: *Deploy from a branch* → Branch `main`, folder `/docs` → Save. After a minute your site is at `https://YOUR_USERNAME.github.io/ai-digest/`.

From now on it refreshes itself every 3 hours (change the `cron` line in `.github/workflows/digest.yml`). An open page checks for new data every 10 minutes and whenever you return to the tab.

## Use it

- **Laptop:** open the URL. In Chrome or Edge, click the install icon in the address bar to get it as an app window.
- **Android:** open the URL in Chrome → menu → *Install app*.
- **iPhone:** open the URL in Safari → Share → *Add to Home Screen*.
- Tabs: *Technical*, *Trending models*, *Business & market*. Each item has a short summary. Tap **Explore more** for extra detail, and the title opens the original article. The dropdown at the top shows earlier days (last 30 are kept).

## Customize (edit `config.yaml` on GitHub, no coding)

- Add or remove feeds in `sources`. Raise `weight` for sources you trust most.
- Add your interests to `keywords`. Items that match rank higher.
- Change how many items appear in `counts`.

## Upgrade the LLM to Claude later

The LLM is one swappable function. To switch:
1. Create a key at console.anthropic.com and add it as the repo secret `ANTHROPIC_API_KEY`.
2. Repo → *Settings → Secrets and variables → Actions → Variables tab* → New variable `LLM_PROVIDER` = `claude`.
3. Optional: variable `LLM_MODEL` to pick a model (default `claude-haiku-5-5`). Set `LLM_PROVIDER` = `none` to use plain article snippets with no LLM.

The same `LLM_MODEL` variable lets you change the Gemini model if Google renames or retires the default (`gemini-2.5-flash-lite`). Check the model list in AI Studio.

## Run it on your own computer (optional test)

```
pip install -r requirements.txt
export GEMINI_API_KEY=your_key      # Windows PowerShell: $env:GEMINI_API_KEY="your_key"
python pipeline/digest.py
python -m http.server -d docs 8000  # open http://localhost:8000
```

## Troubleshooting

- **A source shows FAIL:** the feed URL changed or the site blocks bots. Fix the URL in `config.yaml` or delete the line.
- **Summaries look like raw snippets:** the LLM call failed. Check the log for `LLM failed`. Usual causes: missing secret, wrong model name, or free-tier limits (it retries, and falls back to snippets).
- **Site shows "No digest yet":** the workflow has not succeeded yet, or Pages is not enabled.
- **Daily runs stopped:** GitHub pauses schedules in repos with no activity for 60 days. Open *Actions* and click *Enable workflow*, or run it once by hand.
- **Phone shows an old version:** close and reopen the app. It always tries the network first.

## Features of the final version

- **Dark and light theme** (dark by default, button top right, remembered on each device).
- **Listen mode:** the *Listen* button reads the current tab aloud, story by story. A player bar offers previous, pause, next and speed. Each story also has its own *Listen* button. It uses your browser's built-in voices, so it is free and needs no key. It works best in Chrome, Edge and Safari.
- **Live updates:** the green dot shows how fresh the data is. The page refreshes itself, with no reload needed.
- **Trending topics chart:** bars show which themes dominate today's news. Click a bar to filter, click again to clear.
- **Search, Save (star) and Archive:** saved stories stay in your browser. The archive covers the last 30 days.
- **"N sources" badge:** a story covered by several outlets is probably important.

## Make it yours (portfolio and clients)

- **Branding:** edit `BRAND` at the top of the script in `docs/index.html` (title and tagline). Colours are the variables at the top of the CSS. Replace `docs/icon.svg` and the two PNG icons with your own logo.
- **Topics chart:** edit the `TOPICS` list in the same script.
- **Own domain:** *Settings → Pages → Custom domain*.
- **For a client:** give them their own GitHub repo and API keys so billing and data stay with them. Check the Terms of each news source and your LLM provider's free-tier terms for commercial use; for client work use a paid API key. The site shows short summaries and links, never full articles.
