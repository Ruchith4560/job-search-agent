# AI Resume & Job Application Agent

A semi-automatic AI agent that turns your GitHub and LinkedIn data into a validated master profile, generates tailored resumes, searches legal job feeds, scores match fitness, and pre-fills applications under explicit human review and approval.

---

## Architecture & Phased Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| **Phase 1** | Project scaffold, GitHub ingestion (`data/raw/github.json`), Claude client wrapper | **Completed** |
| **Phase 2** | LinkedIn export parser and master profile merge (`master_profile.json`) | Up next |
| **Phase 3** | ATS-friendly Resume generator (PDF & DOCX) with verification pass | Planned |
| **Phase 4** | Job discovery fetchers (Greenhouse, Lever, Remotive, etc.) & hard filters | Planned |
| **Phase 5** | Vector embedding shortlisting & Claude match scoring | Planned |
| **Phase 6** | Tailored resumes & cover letters per job | Planned |
| **Phase 7** | Playwright application pre-fill with strict Human-in-the-Loop approval gate | Planned |
| **Phase 8** | SQLite tracker, CLI polish, and scheduled digests | Planned |

---

## Setup & Installation

### 1. Requirements
- Python 3.11+
- Virtual environment

### 2. Environment Setup
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install core dependencies
pip install pydantic pyyaml typer rich PyGithub anthropic pytest pytest-mock python-dotenv requests
```

### 3. Configuration
1. Copy the template `.env.example` to `.env`:
   ```powershell
   cp .env.example .env
   ```
2. Add your API credentials in `.env`:
   - `ANTHROPIC_API_KEY`: Anthropic API key for Claude completions.
   - `GITHUB_TOKEN`: (Optional) GitHub Personal Access Token to avoid the 60 requests/hour unauthenticated rate limit.
3. Adjust preferences in `config.yaml` (target roles, experience level, locations, GitHub username).

---

## Usage: Phase 1 CLI

### Ingest GitHub Public Repositories
Fetch repos, languages, stars, topics, last activity, and README summaries into `data/raw/github.json`:

```powershell
# Ingest with default configured username (from config.yaml)
python main.py ingest-github

# Ingest specific GitHub username with a repo limit
python main.py ingest-github --username your_github_handle --limit 10

# Ingest with Claude LLM-generated README summaries
python main.py ingest-github --username your_github_handle --summarize-llm
```

---

## Running Tests
Run the comprehensive pytest suite:
```powershell
.\.venv\Scripts\pytest -v tests/
```
