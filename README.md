# commit-to-control

Map git commits to NIST 800-171 controls. Every pull request shows which compliance controls the change addresses.

The tool embeds your commit diff, searches a pgvector table of all 110 NIST 800-171 Rev 2 security requirements, then uses an LLM judge to filter false positives. Vector similarity alone gets it wrong 70-80% of the time because compliance controls share vocabulary — "access control" appears in a dozen controls. The judge understands the difference between SC-28 (encryption at rest) and SC-8 (encryption in transit) even when the embedding space doesn't.

## How it works

```
commit diff
  → embed → vector search → top K candidate controls
  → LLM judge: "does this control actually apply to this change?"
  → filtered results (only 20-30% of candidates survive)
  → PR comment with ✓ RELEVANT / ✗ REJECT for each control
```

## Quickstart (CLI)

```bash
# Install core + your provider
pip install -r requirements.in -r requirements-openai.in

# Point at your pgvector database
export COMMIT2CONTROL_DB="postgresql://user:pass@localhost:5432/mydb"

# Seed the 110 NIST controls (one-time)
./commit-to-control --seed

# Map a commit
./commit-to-control HEAD
./commit-to-control abc1234
```

## Providers

Works with any AI provider. Two built-in code paths, no framework dependencies.

### OpenAI (default)

```bash
export OPENAI_API_KEY="sk-..."
./commit-to-control HEAD
```

### Ollama (self-hosted, free)

```bash
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"
export EMBED_MODEL="nomic-embed-text"
export JUDGE_MODEL="llama3.2"
./commit-to-control HEAD
```

### AWS Bedrock

```bash
export AWS_REGION="us-east-1"
./commit-to-control --provider bedrock HEAD
```

## GitHub Action

Add to any repo. Every PR gets a comment showing which NIST 800-171 controls the changes address.

```yaml
name: NIST Control Mapping
on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write

jobs:
  control-mapping:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: fizz/commit-to-control@v1
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        with:
          database-url: ${{ secrets.COMMIT2CONTROL_DB }}
```

For Bedrock with OIDC (no stored credentials):

```yaml
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - uses: fizz/commit-to-control@v1
        env:
          AWS_REGION: ${{ vars.AWS_REGION }}
        with:
          provider: bedrock
          database-url: ${{ secrets.COMMIT2CONTROL_DB }}
```

See [.github/workflows/example.yml](.github/workflows/example.yml) for all three provider options.

## Prerequisites

A PostgreSQL database with the pgvector extension. Any managed Postgres that supports pgvector works — RDS, Supabase, Neon, or a local Docker container:

```bash
docker run -d --name pgvector -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres \
  pgvector/pgvector:pg16

export COMMIT2CONTROL_DB="postgresql://postgres:postgres@localhost:5432/postgres"
make setup-db  # enables pgvector extension
make seed      # embeds all 110 controls
```

## Makefile targets

| Target | What it does |
|--------|-------------|
| `make controls` | Download NIST XLSX and generate `controls.json` |
| `make setup-db` | Enable pgvector extension on the database |
| `make seed` | Generate controls + enable pgvector + seed embeddings |
| `make clean` | Remove generated files |

## Controls

All 110 NIST SP 800-171 Rev 2 security requirements with CMMC Level 1/Level 2 mapping. Sourced from the [official NIST XLSX](https://csrc.nist.gov/pubs/sp/800/171/r2/upd1/final) (public domain, US government work). The Makefile regenerates `controls.json` from the NIST source so you can verify nothing was modified.

## Why a judge?

Vector similarity search over compliance controls returns plausible but wrong matches most of the time. A commit that adds KMS encryption to S3 buckets matches SC.L2-3.13.16 (encryption at rest) correctly, but also matches SC.L2-3.13.8 (encryption in transit) and AU.L2-3.3.8 (protection of audit information) because all three controls talk about protecting data. The embeddings are close. The controls are different.

The judge is a second LLM call — cheap (classification, not generation) and fast (small payload). It asks: does this control specifically address what the commit changed? Not "is this semantically related" but "would citing this control in an assessment be accurate." That question requires domain reasoning the embedding model doesn't have.

## License

Apache 2.0
