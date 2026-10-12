# Invoice Tracker: the ONE home of Dat's company invoice app

This folder is the only invoice app (C.D. Grupa Budowlana / C.D. Consulting invoices to Bauceram and the other German clients, ZUS months, KSeF). There is no other copy. The old `workflows/bauceram` folder was deleted 12 Oct 2026 (CEO).

## Where it runs (since 12 Oct 2026)
- Live: the OpenClaw/Sotto VPS (`ssh subtag`, 46.225.128.30), systemd service `invoice-tracker` on 127.0.0.1:8095, behind Caddy.
- Address and login: `~/Marbily claude code/CREDENTIALS.md` ("Invoice Tracker" row). The address is deliberately hard to guess; never post it anywhere public.
- Code on the server: `/opt/invoice-tracker`; keys: `/opt/invoice-tracker/invoice.env` (600).
- Railway is dead for this app (removed 2026). Never deploy there, never open the old railway.app address.

## Where the data is
- Invoices, payments, clients, ZUS months: Google Sheet "MONEY. C.D." (`1xETHFJZO29qJj_UlyTqB29CRyOp7UFi49oEOvmfd084`). Its edit history (Drive revisions) shows every change.
- PDFs: Google Drive folder `1B4nA6s2nprirBDn5w6-_QUjD1VtyclkA`. Previews are built from the sheet, not Drive.
- Chats with the app's AI are kept only in the browser that was used (localStorage), not on the server.

## How to ship a change
1. Edit here, commit, push to GitHub `MaintagCrazy/invoice-tracker-app` (backup only; nothing deploys from GitHub).
2. Run `./deploy.sh`. It copies the committed code to the VPS, installs packages and restarts the service, then checks /health.
3. Open the live address and check the page you changed before saying it works.
