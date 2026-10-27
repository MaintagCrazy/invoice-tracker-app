# Invoice Tracker

The only invoice app for Dat's companies (C.D. Grupa Budowlana / C.D. Consulting: Bauceram and other German clients, ZUS months, KSeF). Backend in `backend/`, UI in `frontend/`.

## Where it runs
- Live on the Sotto VPS (`ssh subtag`): systemd `invoice-tracker`, 127.0.0.1:8095 behind Caddy. Code `/opt/invoice-tracker`, keys `/opt/invoice-tracker/invoice.env`.
- Address and login: `~/Marbily claude code/CREDENTIALS.md` ("Invoice Tracker" row).

## Where the data is
- Invoices, payments, clients, ZUS months: Google Sheet "MONEY. C.D." (`1xETHFJZO29qJj_UlyTqB29CRyOp7UFi49oEOvmfd084`); Drive revisions show every change.
- PDFs: Drive folder `1B4nA6s2nprirBDn5w6-_QUjD1VtyclkA`; previews are built from the sheet.
- AI chats live only in the browser's localStorage.

## Ship a change
1. Edit here, commit, push to GitHub `MaintagCrazy/invoice-tracker-app` (backup only; nothing deploys from it).
2. Run `./deploy.sh` (copies committed code to the VPS, installs, restarts, checks /health).
3. Open the live address and check the changed page.

## Hard rules
1. Never post the live address publicly.
2. Never deploy to Railway; it is gone.
3. There is no other copy of this app.

Old long version: `docs/rules-archive-2026-10-19/CLAUDE.old.md`
- Never make invoices that are not filed, because that is literally illegal.
