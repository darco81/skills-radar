# PyPI Trusted Publishing - setup krok po kroku (PL)

> 10 minut UI clicks. Po jednorazowym setupie każdy `git push --tags` automatycznie publikuje nową wersję na PyPI bez kopiowania tokenów. Bezpieczniej i wygodniej niż klasyczne API tokeny.

---

## Co to jest i dlaczego tak

**Trusted Publishing** to oficjalny standard PyPI od 2023. Zamiast generować długoterminowy token API i wklejać go do GitHub Secrets (gdzie może wyciec), PyPI ufa konkretnemu workflow w konkretnym repo na konkretnej branchy / w konkretnym environment. OAuth pod spodem - krótki token wystawiony tylko na czas tego jednego buildu.

**Twój stan dzisiaj:**
- Repo `dar-kow/skills-radar` jest publiczne ✅
- Workflow `.github/workflows/publish.yml` jest gotowy i czeka na tagi ✅
- 8 tagów już są na zdalnym repo ✅
- **PyPI nie wie jeszcze że ma temu repo zaufać** - to jest dokładnie ten setup poniżej

---

## Krok 1: pypi.org - Add Pending Publisher

### 1a. Załóż konto na PyPI (jeśli nie masz)

→ https://pypi.org/account/register/

Zarejestruj się normalnym mailem (najlepiej `d.kowalski@sdet.it` - żeby pasowało do `pyproject.toml`). PyPI wymusi **2FA** (TOTP albo security key) - włącz to od razu, dosłownie 2 minuty z aplikacją typu Authy / 1Password.

### 1b. Wejdź w Publishing

Zalogowany → kliknij swój **avatar w prawym górnym** → **"Your account"** → w lewym menu zjedź na dół do **"Publishing"**.

URL: https://pypi.org/manage/account/publishing/

### 1c. Add Pending Publisher

Bo paczki `skills-radar` jeszcze nie ma na PyPI, użyjemy formularza **"Add a new pending publisher"** (sekcja na środku/dole strony).

Wypełnij **dokładnie tak**:

| Pole | Wartość |
|---|---|
| **PyPI Project Name** | `skills-radar` |
| **Owner** | `darco81` ⚠️ canonical GitHub username (NOT vanity `dar-kow`) |
| **Repository name** | `skills-radar` |
| **Workflow name** | `publish.yml` |
| **Environment name** | `pypi` |

Kliknij **"Add"**.

> ⚠️ Środowisko `pypi` (nie `Pypi`, nie `PyPI`) - **case-sensitive**. Musi pasować do tego co dasz w GitHub w Kroku 2.

Powinieneś zobaczyć: **"Pending publisher added"**.

---

## Krok 2: GitHub repo → Settings → Environments → New environment "pypi"

### 2a. Wejdź w Settings repo

→ https://github.com/dar-kow/skills-radar/settings/environments

(Lub: Twoje repo `dar-kow/skills-radar` → zakładka **Settings** (nie Issues/PRs/etc., **Settings** na samym końcu) → w lewym menu **"Environments"**.)

### 2b. Nowe środowisko

Kliknij **"New environment"** (zielony button po prawej u góry listy).

W polu nazwy wpisz dokładnie: **`pypi`** (małe litery, jak w Kroku 1c).

Kliknij **"Configure environment"**.

### 2c. (opcjonalnie) Zabezpieczenia środowiska

Na ekranie configure environment masz opcjonalne pola:

- **Required reviewers** - możesz zostawić puste (jesteś solo developerem)
- **Wait timer** - 0 (default, OK)
- **Deployment branches and tags** - kliknij dropdown → **"Selected branches and tags"** → kliknij **"Add deployment branch or tag rule"** → wybierz **"Tag"** z dropdownu → wpisz wzorzec `v*` → **"Add rule"**.
  - To zabezpiecza, że tylko push tagów `v*` może uruchomić publish (a nie np. ktoś z PR-em na maina).

Kliknij **"Save protection rules"**.

---

## Krok 3: Trigger pierwszy publish

Tag `v0.4.0a0` JEST już na remote, ale został pushnięty **przed** setupem PyPI - workflow `publish.yml` wtedy odpalił się z błędem (bo PyPI o repo nie wiedział). Trzeba go re-runąć ręcznie albo pushnąć nowy tag.

### Opcja A - re-run failed workflow (szybsza)

→ https://github.com/dar-kow/skills-radar/actions/workflows/publish.yml

Znajdź failed run dla v0.4.0a0 → otwórz → **"Re-run all jobs"** (góra po prawej).

### Opcja B - pushnij minor patch tag (czystsza)

W terminalu:

```bash
cd ~/dev/dar-kow/skills-radar
git tag -a v0.4.0a1 -m "v0.4.0a1 - first PyPI release with Trusted Publishing"
git push --tags
```

To uruchomi fresh workflow run dla nowego tagu.

### Verify

Po ~3-5 min:

1. → https://github.com/dar-kow/skills-radar/actions - workflow `Publish to PyPI` powinien być **zielony ✓**
2. → https://pypi.org/project/skills-radar/ - paczka powinna być widoczna z najnowszą wersją

Z czystej VM / venv:

```bash
pip install skills-radar
skills-radar version
# → 0.4.0a0  (lub 0.4.0a1)
```

---

## Troubleshooting

### "Pending publisher" zniknął i nie ma jeszcze paczki
PyPI usuwa pending publisher po **30 dniach** jeśli żaden publish się nie wydarzył. Po prostu wróć do Kroku 1c i dodaj go ponownie.

### Workflow `publish.yml` failed z błędem "could not get OIDC token"
GitHub Settings → Actions → General → Workflow permissions → upewnij się że **"Read and write permissions"** jest zaznaczone (a nie "Read repository contents"). Plus **"Allow GitHub Actions to create and approve pull requests"** odhaczone (security best practice - nie potrzebujemy).

### Workflow failed z "trusted publisher not configured"
Sprawdź `pypi.org → Account → Publishing` - pending publisher powinien być widoczny z dokładnymi nazwami **owner/repo/workflow/environment**. Jakikolwiek case mismatch (`Pypi` vs `pypi`) blokuje weryfikację.

### Workflow failed z "version already exists"
Tag dwa razy nie zadziała - PyPI nie pozwala overwrite. Usuń tag lokalnie i remotely, zrób bump (np. `v0.4.0a0` → `v0.4.0a1`), pushnij ponownie:

```bash
git tag -d v0.4.0a0
git push origin :refs/tags/v0.4.0a0
git tag -a v0.4.0a1 -m "..."
git push --tags
```

### W ogóle nie widzę środowiska `pypi` przy run-ie workflow
Workflow musi mieć w pliku `environment: pypi` w jobie publish (`.github/workflows/publish.yml` linia ~14). U nas to JEST - sprawdź pliku, czy nikt tego nie zmienił. Jeśli plik OK a środowiska brak, GitHub UI: Settings → Environments → upewnij się że nazwa to dokładnie `pypi`, nie `Pypi`.

---

## Po pierwszym pushu

Każdy kolejny `git tag -a vX.Y.Z -m "..." && git push --tags` automatycznie:
1. Buduje paczkę przez `python -m build`
2. Pushuje do PyPI z OIDC token (krótkoterminowy, generowany on-the-fly)
3. Tworzy GitHub Release z auto-generowanymi notatkami (z commitów między tagami)

Zero kopiowania tokenów. Zero ręcznej publikacji. Zero `twine upload`.

---

## Quick reference dla CD / nowego maintainera

Gdyby ktokolwiek inny chciał kontynuować ten setup (np. Claude Desktop wzieł rolę maintainera publish flow), wystarczą **3 strony URL**:

1. https://pypi.org/manage/account/publishing/ - sprawdzić że pending publisher istnieje
2. https://github.com/dar-kow/skills-radar/settings/environments - sprawdzić środowisko `pypi`
3. https://github.com/dar-kow/skills-radar/actions/workflows/publish.yml - re-run / monitor publish

---

## TL;DR pętla na produkcji

Gdy chcesz wypuścić kolejną wersję:

```bash
# 1. Bump version
sed -i '' 's/__version__ = ".*"/__version__ = "0.4.1"/' src/skills_radar/__init__.py
sed -i '' 's/^version = ".*"$/version = "0.4.1"/' pyproject.toml

# 2. Update CHANGELOG (sekcja [v0.4.1])

# 3. Commit + tag + push
git add -A
git commit -m "chore: bump to v0.4.1"
git tag -a v0.4.1 -m "v0.4.1 - short release notes"
git push && git push --tags

# 4. Wait ~3-5 min - auto publish
```

Tyle.
