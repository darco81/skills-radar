# From the Field - odcinek bonusowy (PL)

**Tytuł roboczy:** "Mój prompt Claude Code zżerał 6 000 tokenów zanim cokolwiek napisałem."

**Format:** LinkedIn post (długi), wersja PL - publikowana jako pierwszy komentarz pod postem EN (zgodnie z regułą bilingual).

**Status:** draft v1 - wymaga voice pass przed publikacją.

---

## Hook

Wczoraj odpaliłem `/doctor` w Claude Code. Zanim wpisałem jakikolwiek znak, mój prompt był na 6 000 tokenów.

To nie jest model myślący. To nie jest kontekst projektu. To są **same opisy skili** - każdy zainstalowany skill ze scope'ów personal, project i plugin, załadowany z góry do system prompta przy starcie sesji.

Mam ~80 skili. Nie dlatego, że jestem zbieraczem - dlatego, że marketplace pluginów Claude Code zachęca, a rozbudowana biblioteka skili jest realnie użyteczna. Koszt jest niewidoczny, dopóki go nie zmierzysz.

## Czego nikt nie naprawił

Pod koniec zeszłego roku Anthropic wypuścił **Tool Search Tool** - narzędzia oznaczone `defer_loading: true` są niewidoczne, dopóki Claude nie wywoła wbudowanego `tool_search_tool`. Ich wewnętrzne liczby: 85% redukcja tokenów, accuracy Opus 4.5 z 79.5% → 88.1% na dużych bibliotekach narzędzi. Krótko potem to samo w Claude Code dla MCP serwerów.

Ale Tool Search jest dla **narzędzi**. Skille to inny mechanizm - pliki w `~/.claude/skills/`, ładowane przez Skill tool, nie przez MCP. Anthropic jeszcze tego nie zrobił. Issues #16160 i #19105 stoją otwarte.

Więc zrobiłem. Nie dlatego, że nikt nie próbował - w sieci jest kilka projektów `mcp-skill-server` - ale dlatego, że **żaden z nich nie rozwiązuje "discovery dilemmy"**.

## Discovery dilemma

Naiwny RAG nad skillami wykłada się na pierwszej przeszkodzie:

> Jeśli agent nie widzi, że skille istnieją, nigdy nie odpyta indeksu. Jeśli nigdy nie odpyta - to lazy loading jest bezsensowny.

Większość projektów społecznościowych shippuje jedno MCP tool "find_relevant_skill" i zakłada, że Claude sam się domyśli żeby je odpytać przy każdym tasku. Nie domyśla się. Bez sygnału na poziomie Tier 1, retrieval w Tier 2 jest niewidoczny.

## Two-Tier Discovery

`skills-radar` rozdziela discovery na dwie warstwy:

**Tier 1 - Mini-index w CLAUDE.md, ~1k tokenów.** Płaska lista `nazwa + 1-zdaniowy opis` per skill, pogrupowane kategoriami. Zawsze widoczne. Tanie. Mówi Claude'owi *co istnieje.*

**Tier 2 - Load on-demand przez MCP.** Dwa narzędzia: `search_skills(query)` dla niedosprecyzowanego intentu, `load_skill(name)` gdy nazwa jest oczywista. Pełny body SKILL.md ściągany tylko wtedy, gdy agent zdecyduje się działać.

Efekt na moim setupie: **6 000 tokenów → 1 900 tokenów dla tych samych 80 skili.** ~68% redukcji. Nie ma znaczenia, czy jutro skaluję do 500 skili - koszt zostaje płaski.

## Zbudowane jak by zrobił Anthropic

Stack zgodny z opublikowanymi best practices Anthropic:
- MCP Python SDK z transportem **Streamable HTTP** (`stateless_http=True, json_response=True`)
- Hybrid retrieval: BM25 + dense embeddings, ważone 70/30
- Index po `description + when_to_use`, nigdy po body - bloat body niszczy similarity scoring
- Threat model od day-one: trust tiers, skanowanie pod kątem prompt injection, strip XML, size cap, walidacja nazw. SKILL.md to dosłownie input system-prompt-injection. Tak go traktujemy.
- Dwa narzędzia, nie siedem. Eat your own dogfood - opis każdego tool to koszt tokenów w kontekście agenta-konsumenta.

## Co dostajesz

- `pip install skills-radar` (po publikacji na PyPI)
- `skills-radar serve --transport stdio` dla lokalnego Claude Code; `--transport http` dla Dockera / produkcji
- Hot reload - wrzucasz SKILL.md, indeksowane <1s
- Opcjonalny local-LLM query rewriter (Ollama) - przepisuje niejednoznaczne queries na bogatsze frazy keyword'owe; domyślnie wyłączony
- Air-gapped friendly - pre-baked Docker image, offline flagi HF Hub
- Multi-client - Claude Code, Cursor, Claude Desktop, custom agenty MCP

Repo: **github.com/dar-kow/skills-radar** (link w pierwszym komentarzu pod EN postem - algorytm tak chce)

## Call to action

Wrzuć swoją liczbę skili w komentarzu. Zgaduję ile masz token bleed.

Jak rozwiązałeś to inaczej - pokazuj. Na dobre pomysły nie ma monopolu, a prior art (`bobmatnyc/mcp-skillset`, `back1ply/agent-skill-loader`, `gotalab/skillport`) ma kawałki które zrobili dobrze i z których uczyłem się sam.

---

## Notatki przed publikacją

- Wrzucić jako pierwszy komentarz pod EN postem (link nie idzie w treści głównej - ranking algorytmu LI)
- W tym komentarzu link do repo + krótka linijka po PL: "Pełny opis po angielsku w poście wyżej. Repo: github.com/dar-kow/skills-radar"
- Drugi komentarz wewnątrz wątku PL (po 30 min): "Pełna architektura w SPEC.md w repo, ~2300 słów, bez waty"
- Voice: peer-level senior engineers PL TI scene, nie juniorów, nie C-level. Brak korpomowy.
