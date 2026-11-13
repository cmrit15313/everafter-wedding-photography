# EverAfter Studio — Wedding Photo Finder

A starter wedding photography website with a premium portfolio, photographer dashboard, event-specific QR codes, browser-based face indexing, and selfie-to-gallery matching.

## Requirements
- Python 3.10+
- Internet connection in the browser for the face-api.js library and model files
- HTTPS when deployed (camera access requires HTTPS; localhost is allowed)

## Run locally
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```
Set environment variables before starting:
```bash
# Windows PowerShell
$env:ADMIN_PASSWORD="your-strong-password"
$env:SECRET_KEY="a-long-random-secret"
# macOS/Linux
export ADMIN_PASSWORD="your-strong-password"
export SECRET_KEY="a-long-random-secret"
```
Then:
```bash
python app.py
```
Open http://127.0.0.1:5000 and choose Photographer login. The default password is `change-me` only if you have not set `ADMIN_PASSWORD`.

## Create a wedding
1. Sign in at `/admin`.
2. Create a wedding event.
3. Upload the event photographs.
4. On the event management page, click **Index photos on this device** and keep the tab open until complete.
5. Print the event QR code. Guests scan it, take/upload a selfie, and see matching photographs.

## How face matching works
The browser uses face-api.js (SSD face detection, 68-point landmarks and 128-dimensional face descriptors). During indexing, descriptors are saved to SQLite. During guest search, the selfie descriptor is generated locally in the guest's browser and compared against saved descriptors. The selfie image itself is not uploaded. The initial distance threshold is 0.48 and may need tuning for your camera conditions and dataset.

## Important before a real wedding
This is a working MVP/prototype, not a production-secure biometric service.
- Replace the sample branding, email address and stock hero image.
- Use HTTPS and set a strong `ADMIN_PASSWORD`, `SECRET_KEY`, and `SITE_URL`.
- Add proper admin authentication, rate limiting, backups, access controls, monitoring and secure cloud object storage before public deployment.
- Ask guests for clear consent before face matching. Provide a non-biometric alternative (manual gallery browsing), a deletion contact, and a clear retention period. Follow applicable privacy/data-protection laws.
- Do not put sensitive/private weddings on a public URL without adding access controls or expiring/private gallery links.
- This MVP stores face descriptors on the server. Although the selfie stays in the browser, face descriptors are biometric data and must be protected and deleted when no longer needed.
- Large uploads may require increasing server request limits and using background indexing / cloud storage.
- Browser face models are fetched from a third-party CDN. For production, self-host and pin audited model assets.
- QR code generation uses qrcodejs; face matching uses face-api.js loaded from jsDelivr.

## Current MVP limitations
- No customer checkout, favorites, bulk ZIP download, multi-photographer accounts, or automatic cloud deployment.
- Event galleries are accessible to anyone with the event URL/QR. Add a PIN or signed guest link if you need restricted access.
- Local SQLite and `uploads/` are suitable for a demo or small test, not multi-server production hosting.
