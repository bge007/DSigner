# DSigner — Master Prompt (7 Steps)

A sequence of prompts that rebuilds this project from an empty folder.
Feed them to an AI coding agent (or follow them yourself) one at a time —
each step produces a working, testable application and the next step builds
on it. Verify the acceptance criteria before moving on.

**Target stack:** Python 3.13, PyQt5 (UI), PyMuPDF (rendering & search),
pyhanko (PAdES signature container), Windows CNG via ctypes (private-key
operations), cryptography (certificate parsing).

---

## Step 1 — Project scaffold and interactive PDF viewer

> Create a Python desktop application called **DSigner** for digitally
> signing PDF documents, with a PyQt5 GUI. Set up a clean project layout
> (`main.py`, `ui/`, `core/`, `requirements.txt`, venv) with a modern light
> theme via a Qt stylesheet. Build a PDF viewer that renders pages as
> images and lets the user place a **signature box** interactively: click
> anywhere on the page to move the box there, drag it to fine-tune, with a
> live dashed-outline preview showing the signer name. Keep all viewer
> geometry in PDF points measured from the page's top-left corner, and
> convert to PDF's bottom-left origin only at signing time (72 pt = 1 inch;
> render at 150 DPI, so pixels = points × 150/72). Add X/Y/width/height
> spinboxes that stay bidirectionally in sync with the box on the page.
> Configure application-wide logging of full tracebacks to `error.log`,
> including a `sys.excepthook` for unhandled exceptions.

**Accept when:** a PDF opens and displays; clicking/dragging moves the box
and updates the spinboxes; editing spinboxes moves the box; the box cannot
leave the page; errors land in `error.log`.

---

## Step 2 — Rendering engine, page controls, and text search

> Use **PyMuPDF** as the rendering engine (no external binaries like
> poppler). Render pages lazily with an LRU cache (~8 pages) so large
> documents open instantly. Add page-view controls: previous/next buttons,
> a jump-to-page spinbox with "/ N" total, zoom in/out with percentage
> label, **Fit width** and **Fit page**; support **Ctrl+Scroll** zooming
> anchored at the cursor position, plus **Ctrl +/−** and **Ctrl+0**
> (fit width) shortcuts, clamped to 25%–300%. Add **text search**: a search box
> (Ctrl+F) that finds every match across all pages using PyMuPDF's
> `search_for` rectangles; highlight all matches on the visible page in
> yellow with the current match emphasized in orange; Enter/▼ and ▲ cycle
> through matches with an "n / total" counter, jumping pages and scrolling
> the match into view.

**Accept when:** a 100+ page PDF opens instantly; search finds matches on
other pages, jumps to them, and highlights them; zoom/fit controls work at
any page.

---

## Step 3 — Tabbed multi-document interface with session restore

> Turn the viewer into a **tabbed interface**: the open dialog multi-selects,
> each file opens in its own closable/reorderable tab (Ctrl+W closes,
> opening an already-open file just activates its tab). Each tab keeps its
> own search state and its own signature-box placement; switching tabs
> swaps the placement values shown in the side panel. Persist the
> **session** to `%LOCALAPPDATA%\DSigner\session.json` on exit — open file
> paths, current page, zoom, and signature placement per file, plus the
> active tab — and restore all of it automatically on the next launch,
> silently skipping files that no longer exist.

**Accept when:** several PDFs are open at once with independent placement;
closing and relaunching the app reopens the same tabs at the same pages,
zooms, and placements.

---

## Step 4 — Windows Certificate Store access and CNG signing

> Write a dependency-free module (`core/wincert.py`) that talks to Windows
> **crypt32/ncrypt via ctypes**: enumerate certificates in the CurrentUser
> "MY" store that have a private key (check `CERT_KEY_PROV_INFO_PROP_ID`),
> exposing subject CN, issuer CN, validity dates, SHA1 thumbprint, and a
> duplicated `CERT_CONTEXT` handle. Implement `sign_digest(cert, digest,
> algorithm)` using `CryptAcquireCertificatePrivateKey` (prefer NCrypt) and
> `NCryptSignHash` with PKCS#1 v1.5 padding — the private key must never
> leave Windows, so non-exportable keys, smartcards, and USB-token DSCs
> work, with the provider's own PIN prompt. Build a certificate-picker
> dialog listing subject/issuer/expiry (expired ones flagged in red). Test
> by creating a self-signed certificate with PowerShell
> `New-SelfSignedCertificate` and verifying the raw signature against the
> certificate's public key with the `cryptography` library.

**Accept when:** the dialog lists real store certificates; a digest signed
via CNG verifies with `public_key().verify(...)`.

---

## Step 5 — Real PAdES signatures with a detailed visible stamp

> Integrate **pyhanko**: subclass `pyhanko.sign.signers.Signer`, delegating
> `async_sign_raw` to the CNG `sign_digest` from Step 4 (return a zero
> buffer of key-size length for `dry_run`). Sign the page currently shown,
> converting the box from top-left to bottom-left coordinates using the
> actual page height. The visible stamp (`TextStampStyle`) must show:
> "Digitally signed by {CN}", organization and email when present in the
> certificate, date with timezone offset, reason, location, and the issuing
> CA — and the signature metadata must carry the claimed name, reason, and
> location so PDF readers show them in their signature panel. Default the
> output filename to `<name>_signed_YYYYMMDD_HHMMSS.pdf` and refuse to
> overwrite the open input file. Validate end-to-end with pyhanko's
> `validate_pdf_signature` using the signing certificate as trust root:
> the result must be intact, valid, and trusted.

**Accept when:** the signed PDF shows the stamp with all details at the
chosen position on the chosen page, Adobe's signature panel shows
name/reason/location/time, and pyhanko validation reports
intact/valid/trusted.

---

## Step 6 — Digital Signature mode, signature inspector, and cert creation

> Polish the signing UX. Add a checkable **"Digital Signature"** toolbar
> button: the signing pane (certificate, reason/location, placement,
> Sign & Save) is **hidden by default**, and the placement box on the page
> only appears while the mode is active; new tabs respect the current mode
> and Ctrl+S enters the mode first if it's off. Add a **"Signatures in
> this document"** section that reads embedded signatures from the active
> PDF via pyhanko (signer name, signing time with timezone parsed from the
> PDF `/M` date, reason, location, certificate CN, field name); after
> signing, open the signed copy automatically in a new tab so its details
> appear there immediately. Add **"Create new certificate…"**: a dialog
> (full name required; organization, email, validity years optional) that
> creates a self-signed document-signing certificate in the Windows store
> via PowerShell `New-SelfSignedCertificate` (RSA-2048, DigitalSignature +
> NonRepudiation key usage, PDF-signing EKU 1.2.840.113583.1.1.5),
> sanitizing all inputs against RDN/command injection, then selects it for
> signing right away — with a clear note that self-signed signatures show
> as valid-but-untrusted to recipients.

**Accept when:** PDFs open in a clean reading view with no signing UI; the
toggle reveals pane + placement box; signing opens the signed copy in a tab
whose signature details display in the panel; a certificate created in the
dialog immediately signs successfully.

---

## Step 7 — Branding, signature inspector, and portable packaging

> Give the app an identity and a review workflow. Generate a **logo**
> programmatically (script in `assets/`: rounded blue gradient badge, bold
> white "D", amber handwritten swoosh) producing `logo.png`, a
> light-palette `logo_light.png`, and a multi-size `logo.ico`. Use it as
> the window/taskbar icon (set a Windows AppUserModelID so the taskbar
> shows it) and embed the light variant as the **background watermark of
> the visible signature stamp** (pyhanko `TextStampStyle(background=
> PdfImage(...), background_opacity≈0.3)`). Make existing signatures
> **clickable in the viewer**: hit-test PyMuPDF signature widgets
> (`PDF_WIDGET_TYPE_SIGNATURE` rects) in reading mode with a pointing-hand
> cursor, and open a details dialog showing integrity status (verified
> with pyhanko: intact/modified), signer, date, reason, location,
> certificate subject/issuer/serial/validity, SHA-256 fingerprint,
> signature algorithm, key type and size, and the **public key as PEM**
> with a copy button. Package everything as a portable single-file exe
> with PyInstaller (`--onefile --windowed --icon assets\logo.ico
> --add-data "assets;assets"`), using a `resource_path()` helper that
> resolves assets from `sys._MEIPASS` when frozen, and writing logs to
> `%LOCALAPPDATA%\DSigner` in that case. Open PDF writers with
> `strict=False` so hybrid-xref documents (MS Word exports) sign cleanly.

**Accept when:** the window and exe carry the logo; signed stamps show the
light logo behind the text; clicking a signature on the page opens the
inspector with a correct intact/modified verdict and a copyable public
key; the exe runs on a machine without Python.

---

## Verification ritual (every step)

1. Run the relevant smoke test headlessly (instantiate `QApplication` +
   window without `show()`, drive the widgets programmatically).
2. For signing steps, validate cryptographically with pyhanko — never
   assume the signature is correct because the stamp is visible.
3. Commit with a descriptive message and push to
   `https://github.com/bge007/DSigner.git`.
