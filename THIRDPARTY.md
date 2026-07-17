# Third-Party Licenses

DSigner is released under the MIT License. It depends on the following
third-party components, all of which permit distribution of DSigner
under MIT:

| Component | License | Role |
|---|---|---|
| PySide6 (Qt for Python) | LGPL-3.0 | GUI framework |
| pypdfium2 | Apache-2.0 OR BSD-3-Clause | PDF rendering, text, search, page objects |
| PDFium (bundled by pypdfium2) | Apache-2.0 / BSD-3-Clause | PDF engine |
| pypdf | BSD-3-Clause | PDF structure edits (forms, annotations) |
| pyhanko | MIT | PAdES digital signature container |
| pyhanko-certvalidator | MIT | Certificate validation |
| cryptography | Apache-2.0 OR BSD-3-Clause | Certificate parsing, crypto primitives |
| Pillow | MIT-CMU | Image handling for rendering and stamps |
| asn1crypto | MIT | ASN.1 (via pyhanko) |
| certifi | MPL-2.0 | CA bundle (via requests; unmodified) |
| PyInstaller | GPL-2.0 with bootloader exception | Build tool only; the exception explicitly permits distributing bundled applications under any license |

## LGPL-3.0 note (PySide6 / Qt)

DSigner uses PySide6 via **dynamic linking** (the standard Python binding
mechanism); the Qt libraries are distributed as separate, replaceable
shared libraries both in source installs and inside the packaged
executable. No Qt source code is modified. Users may replace the Qt
libraries with their own builds, satisfying LGPL-3.0 §4. The full LGPL
text is available at https://www.gnu.org/licenses/lgpl-3.0.html.

## History

Earlier development versions used PyQt5 (GPL-3.0) and PyMuPDF
(AGPL-3.0). Both were removed and replaced with the components above so
the application can be distributed under the MIT License without
copyleft obligations.
