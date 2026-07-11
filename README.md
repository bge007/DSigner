# DSigner

A digital signing application for PDF documents. Open PDFs in tabs, find the
right spot with text search, place the signature box by clicking or dragging
on the page, and sign with a certificate from the **Windows Certificate
Store** — producing a real cryptographic (PAdES) signature that Adobe Reader
validates.

## Features

- **Tabbed viewer** — open multiple PDFs at once; tabs are closable and reorderable
- **Session restore** — reopens your files, pages, zoom and signature placement on next launch
- **Text search** — find matches across all pages with highlights and next/previous navigation
- **Page controls** — page jump, previous/next, zoom in/out, fit width, fit page
- **Interactive placement** — click the page to place the signature box, drag to fine-tune
- **Real digital signatures** — pick a certificate from the Windows store
  (Current User → Personal); signing happens inside Windows CNG, so
  non-exportable keys, smartcards and USB-token DSCs all work, with the
  provider's own PIN prompt when required
- **Visible signature stamp** — signer name, organization, date, reason and
  location drawn at the chosen position, with the DSigner logo as a light
  background watermark
- **Signature inspector** — click any signature on the page to review it:
  integrity check (intact / modified), certificate subject, issuer, serial,
  validity, SHA-256 fingerprint, key type and the public key as copyable PEM

## Project Structure

```
DSigner/
├── main.py                # Entry point, theme, session bootstrap
├── requirements.txt
├── core/
│   ├── wincert.py         # Windows cert store enumeration + CNG signing (ctypes)
│   ├── certsigner.py      # PAdES signing via pyhanko, keys stay in Windows
│   ├── session.py         # Save/restore open-files session
│   └── logging_setup.py   # error.log configuration
└── ui/
    ├── main_window.py     # Tabs, toolbar, side panel, signing flow
    ├── document_tab.py    # Per-document search bar + viewer + placement state
    ├── pdf_viewer.py      # PyMuPDF-based viewer with overlays
    └── cert_dialog.py     # Windows certificate picker
```

## Installation

```powershell
cd DSigner
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Dependencies: **PyQt5** (UI), **PyMuPDF** (rendering & search),
**pyhanko** (PDF signature container), **cryptography** (certificate parsing).
No poppler or other external binaries required.

## Usage

1. **Open PDF(s)** (`Ctrl+O`) — multi-select works; each file opens in a tab
2. **Search** (`Ctrl+F`) — type and press Enter; Enter again / ▲▼ to move between matches
3. **Place the signature** — click anywhere on the page to move the box there,
   drag it to fine-tune, or use the X/Y/W/H fields; the box stays per-document
4. **Choose certificate** — pick from your Windows store; the selection is
   reused for every signature this session
5. **Sign & Save** (`Ctrl+S`) — the signature is applied to the page currently
   shown, saved as `<name>_signed.pdf` by default

Closing the app saves the session; the next launch reopens the same documents.

## How signing works

DSigner builds a standard PDF signature (CMS/PAdES) with pyhanko. The digest
is computed over the prepared PDF, then handed to Windows CNG
(`NCryptSignHash`) for the private-key operation — the key never leaves the
Windows key store or hardware token. The signing certificate is embedded so
validators can verify it.

Whether a validator shows the signature as *trusted* depends on the
certificate's chain: certificates issued by a licensed CA validate cleanly;
self-signed test certificates show as valid-but-untrusted unless the
certificate is added as a trust anchor.

## Portable executable

Build a single-file `DSigner.exe` that runs on other Windows machines with
no Python installation:

```powershell
.\build_exe.bat        # output: dist\DSigner.exe
```

Copy `dist\DSigner.exe` anywhere (USB stick, another PC) and run it.
Notes:

- First launch takes a few seconds — the single file unpacks itself to a
  temp folder.
- Session and error log live in `%LOCALAPPDATA%\DSigner\` on each machine.
- Signing certificates come from *that machine's* Windows store — take
  your certificate (or USB token) with you, or create one in-app.
- Windows SmartScreen may warn on unsigned executables; choose
  "More info → Run anyway", or sign the exe with a code-signing cert.

## Session & logs

- Session file: `%LOCALAPPDATA%\DSigner\session.json`
- Error log: `error.log` in the project folder (full tracebacks)

## Troubleshooting

- **"Cannot access the private key"** — the certificate has no private key on
  this machine, or the token is not connected.
- **Legacy CryptoAPI key error** — very old certificates stored with a legacy
  provider are not supported; re-import the certificate into a CNG provider.
- **Nothing in the certificate list** — only certificates *with a private
  key* in Current User → Personal are shown (`certmgr.msc` to inspect).

## License

MIT License
