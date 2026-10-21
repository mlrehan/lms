# Enterprise Multi-Agent AI System: Production Deployment & Runbook

This guide details the exact operational steps to deploy and verify the Multi-Agent AI System on the production server (`158.220.92.194`).

---

## 1. Prerequisites & Environment Setup

Connect to the production server via SSH:
```bash
ssh root@158.220.92.194
cd /var/www/lait/LMS
```

Verify that the `.env` file on production contains your OpenAI API credentials:
```bash
grep -E "OPENAI_|AI_" .env || cat << 'EOF' >> .env

# -----------------------------------------------------------------------------
# ENTERPRISE MULTI-AGENT AI ECOSYSTEM
# -----------------------------------------------------------------------------
OPENAI_API_KEY=your_production_openai_api_key_here
OPENAI_MODEL=gpt-4o
OPENAI_INTENT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_TRANSCRIPTION_MODEL=whisper-1
AI_CONFIRMATION_TICKET_TTL_SECONDS=900
AI_MAX_TOOL_CALL_TURNS=4
AI_RATE_LIMIT_CALLS_PER_MINUTE=60
EOF
```

---

## 2. Zero-Downtime Deployment Sequence

Execute the following standard deployment sequence:

```bash
# 1. Check current state and create safety checkpoint branch
git status
git branch backup-before-ai-deployment-$(date +%Y%m%d-%H%M%S)

# 2. Pull latest commits from master
git config pull.rebase false
git pull --no-rebase origin master

# 3. Rebuild Docker container images with new dependencies (openai, etc.)
docker compose build backend frontend

# 4. Apply Database Migrations (including pgvector and AI tables)
docker compose run --rm backend alembic upgrade head

# 5. Bring up services with zero downtime
docker compose up -d --no-deps backend frontend webhooks-worker

# 6. Verify running status of all containers
docker compose ps
```

---

## 3. Operational Verification & Smoke Testing

### Backend Health & AI Endpoints
```bash
# Check backend health
curl -f http://127.0.0.1:8000/livez
curl -f http://127.0.0.1:8000/readyz

# Check recent backend logs
docker compose logs --tail=50 backend
```

### PostgreSQL Extension & AI Tables
```bash
# Verify vector extension and new AI tables
docker compose exec -T db psql -U postgres -d lms -c "\dt resource_embeddings"
docker compose exec -T db psql -U postgres -d lms -c "\dt ai_conversation_messages"
```

### Frontend UI Verification
1. Open the LMS production URL in your browser and sign in.
2. In the topbar header, observe the **AI Assistant** icon button (`Sparkles`).
3. Press `Ctrl + J` (or `Cmd + J` on macOS) to toggle the slide-over AI Drawer.
4. Test prompts across roles:
   - **Tutor**: *"Draft a 5-question quiz on Python lists for my course"*
   - **Student**: *"What is my schedule for this week?"*
   - **Voice Input**: Click the microphone icon to test Whisper voice transcription.
   - **Action Confirmation**: Click *"Publish Live"* on an assessment draft card to verify the two-phase approval modal.

---

## 4. Rollback Procedure (Emergency Only)

If any unforeseen issue occurs in production:
```bash
# Revert database migration
docker compose exec backend alembic downgrade 91a150439935

# Check out the safety backup branch
git checkout backup-before-ai-deployment-<TIMESTAMP>

# Rebuild and restart containers
docker compose build backend frontend
docker compose up -d --no-deps backend frontend webhooks-worker
```
