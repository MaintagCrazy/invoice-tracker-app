# Invoice Tracker App

AI-powered invoice creation and tracking system for C.D. Grupa Budowlana.

## Features

- **AI Chat Interface**: Create invoices using natural language
- **PDF Generation**: Professional invoice PDFs using WeasyPrint
- **Email Sending**: Automated email with Gmail API
- **Multi-language**: German/Polish/English email templates
- **Dashboard**: Track invoices by status and client

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI (Python 3.11) |
| Frontend | HTML + TailwindCSS + Vanilla JS |
| AI | OpenRouter + Gemini 2.0 Flash |
| PDF | WeasyPrint |
| Email | Gmail API OAuth2 |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Hosting | Railway |

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export OPENROUTER_API_KEY=sk-or-v1-...
export GMAIL_TOKEN_B64=...  # Base64 encoded token

# Run server
cd backend
uvicorn main:app --reload
```

Visit http://localhost:8000

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key for AI |
| `GMAIL_TOKEN_B64` | Base64 encoded Gmail OAuth token |
| `GMAIL_CREDENTIALS_B64` | Base64 encoded Gmail credentials |
| `DATABASE_URL` | PostgreSQL connection string (Railway provides) |
| `API_KEY` | Optional API key for authentication |

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/invoices` | GET | List invoices |
| `/api/invoices` | POST | Create invoice |
| `/api/invoices/{id}/preview` | GET | PDF preview |
| `/api/invoices/{id}/send` | POST | Send via email |
| `/api/chat` | POST | AI conversation |
| `/api/clients` | GET/POST | Client management |

## Email Configuration

### Tax Accountants (always receive all invoices)
- edyta.karczewska@kdik.pl
- iwona.haliburda@kdik.pl

### Language Detection
- `.de` domain → German
- `.ch` domain → German (Swiss)
- `.pl` domain → Polish
- `.com` domain → English

## Invoice Number Format

`XX/MM/YYYY`
- XX = Sequential number within the month (01, 02, 03...)
- MM = Current month (01-12)
- YYYY = Current year

## Deployment to Railway

1. Push to GitHub
2. Connect Railway to repo
3. Add environment variables
4. Deploy

Railway auto-detects Python and uses nixpacks for system dependencies (WeasyPrint requires cairo, pango, etc.)
