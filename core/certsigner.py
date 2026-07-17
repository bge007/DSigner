"""
Cryptographic PDF signing (PAdES) using a Windows-store certificate.

pyhanko builds the signature container and visual appearance; the
actual private-key operation is delegated to Windows CNG through
core.wincert, so non-exportable keys and USB tokens work.
"""
import hashlib
import logging
import os
import time
import warnings
from datetime import datetime

from asn1crypto import algos
from asn1crypto import x509 as asn1_x509
from cryptography import x509 as crypto_x509
from cryptography.x509.oid import NameOID
from pyhanko import stamp
from pyhanko.pdf_utils import text
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers
from pyhanko_certvalidator.registry import SimpleCertificateStore

from core import wincert
from core.resources import resource_path

logger = logging.getLogger(__name__)


class WindowsCertSigner(signers.Signer):
    """pyhanko Signer that signs through the Windows CNG key store."""

    def __init__(self, win_cert):
        self.win_cert = win_cert
        signing_cert = asn1_x509.Certificate.load(win_cert.der)
        registry = SimpleCertificateStore()
        registry.register(signing_cert)
        super().__init__(
            signing_cert=signing_cert,
            cert_registry=registry,
            signature_mechanism=algos.SignedDigestAlgorithm(
                {"algorithm": "sha256_rsa"}),
        )

    async def async_sign_raw(self, data, digest_algorithm, dry_run=False):
        if dry_run:
            return bytes(self.signing_cert.public_key.bit_size // 8)
        digest = hashlib.new(digest_algorithm, data).digest()
        return wincert.sign_digest(self.win_cert, digest, digest_algorithm)


def sign_pdf_with_certificate(input_pdf, output_pdf, win_cert, page_index,
                              box, reason="", location=""):
    """Digitally sign one page of a PDF with a visible signature box.

    box is (x1, y1, x2, y2) in PDF page space (origin bottom-left) —
    obtain it from PDFViewer.view_rect_to_page_box().
    """

    field_name = f"DSigner-{int(time.time())}"

    # pull extra visible details from the certificate itself
    def _attr(name, oid):
        values = name.get_attributes_for_oid(oid)
        return values[0].value if values else ""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cert = crypto_x509.load_der_x509_certificate(win_cert.der)
    organization = _attr(cert.subject, NameOID.ORGANIZATION_NAME)
    email = _attr(cert.subject, NameOID.EMAIL_ADDRESS)

    now = datetime.now().astimezone()
    tz = now.strftime("%z")
    signed_at = f"{now:%Y-%m-%d %H:%M:%S} {tz[:3]}:{tz[3:]}" if tz else \
        f"{now:%Y-%m-%d %H:%M:%S}"

    lines = [f"Digitally signed by {win_cert.subject}"]
    if organization:
        lines.append(f"Organization: {organization}")
    if email:
        lines.append(f"Email: {email}")
    lines.append(f"Date: {signed_at}")
    if reason:
        lines.append(f"Reason: {reason}")
    if location:
        lines.append(f"Location: {location}")
    lines.append(f"Issued by: {win_cert.issuer}")
    # TextStampStyle %-interpolates its text; escape literal percents
    stamp_text = "\n".join(lines).replace("%", "%%")

    signer = WindowsCertSigner(win_cert)
    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        name=win_cert.subject,
        reason=reason or None,
        location=location or None,
        md_algorithm="sha256",
    )
    # light DSigner logo as the stamp's background watermark
    background = None
    logo_path = resource_path("assets/logo_light.png")
    if os.path.exists(logo_path):
        try:
            from pyhanko.pdf_utils.images import PdfImage
            background = PdfImage(logo_path)
        except Exception:
            logger.exception("Could not load stamp background image")

    style = stamp.TextStampStyle(
        stamp_text=stamp_text,
        border_width=1,
        text_box_style=text.TextBoxStyle(font_size=8),
        background=background,
        background_opacity=0.50,
    )
    pdf_signer = signers.PdfSigner(
        meta, signer=signer, stamp_style=style,
        new_field_spec=fields.SigFieldSpec(
            sig_field_name=field_name, on_page=page_index, box=box),
    )

    with open(input_pdf, "rb") as inf:
        # strict=False accepts real-world files: hybrid cross-reference
        # tables (e.g. PDFs exported by MS Word) and minor spec deviations
        writer = IncrementalPdfFileWriter(inf, strict=False)
        with open(output_pdf, "wb") as outf:
            pdf_signer.sign_pdf(writer, output=outf)

    logger.info("Signed %s -> %s (field %s, page %d)",
                input_pdf, output_pdf, field_name, page_index + 1)


def _pdf_date_to_text(value):
    """'D:20260709142824+05'30'' -> '2026-07-09 14:28:24 +05:30'."""
    s = str(value or "")
    if not s.startswith("D:") or len(s) < 16:
        return s
    out = f"{s[2:6]}-{s[6:8]}-{s[8:10]} {s[10:12]}:{s[12:14]}:{s[14:16]}"
    if len(s) >= 22 and s[16] in "+-":
        out += f" {s[16:19]}:{s[20:22]}"
    return out


def read_signatures(pdf_path):
    """Details of the digital signatures embedded in a PDF (for display)."""
    from pyhanko.pdf_utils.reader import PdfFileReader

    results = []
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfFileReader(f, strict=False)
            for sig in reader.embedded_signatures:
                obj = sig.sig_object
                signer_cn = ""
                try:
                    subject = sig.signer_cert.subject.native
                    signer_cn = (subject.get("common_name")
                                 or subject.get("organization_name", ""))
                except Exception:
                    logger.debug("No parseable signer cert in %s",
                                 sig.field_name, exc_info=True)
                results.append({
                    "field": sig.field_name,
                    "name": str(obj.get("/Name", "") or "") or signer_cn,
                    "signer_cn": signer_cn,
                    "signed_at": _pdf_date_to_text(obj.get("/M")),
                    "reason": str(obj.get("/Reason", "") or ""),
                    "location": str(obj.get("/Location", "") or ""),
                })
    except Exception:
        logger.exception("Failed to read signatures from %s", pdf_path)
    return results


def signature_details(pdf_path):
    """Full review data for every signature in a PDF: signer, certificate,
    public key (PEM), fingerprints, and an integrity check."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    from cryptography.hazmat.primitives import hashes as crypto_hashes
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    results = []
    try:
        with open(pdf_path, "rb") as f:
            reader = PdfFileReader(f, strict=False)
            for sig in reader.embedded_signatures:
                obj = sig.sig_object
                info = {
                    "field": sig.field_name,
                    "name": str(obj.get("/Name", "") or ""),
                    "signed_at": _pdf_date_to_text(obj.get("/M")),
                    "reason": str(obj.get("/Reason", "") or ""),
                    "location": str(obj.get("/Location", "") or ""),
                    "subject": "", "issuer": "", "serial": "",
                    "valid_from": "", "valid_to": "", "key_info": "",
                    "sig_algorithm": "", "sha256_fp": "", "pubkey_pem": "",
                    "intact": None, "valid_crypto": None,
                }

                try:
                    der = sig.signer_cert.dump()
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        cert = crypto_x509.load_der_x509_certificate(der)
                        info["subject"] = cert.subject.rfc4514_string()
                        info["issuer"] = cert.issuer.rfc4514_string()
                    info["serial"] = format(cert.serial_number, "X")
                    info["valid_from"] = f"{cert.not_valid_before_utc:%Y-%m-%d}"
                    info["valid_to"] = f"{cert.not_valid_after_utc:%Y-%m-%d}"
                    info["sha256_fp"] = cert.fingerprint(
                        crypto_hashes.SHA256()).hex(":").upper()
                    info["sig_algorithm"] = cert.signature_algorithm_oid._name

                    public_key = cert.public_key()
                    if isinstance(public_key, rsa.RSAPublicKey):
                        info["key_info"] = f"RSA, {public_key.key_size} bits"
                    elif isinstance(public_key, ec.EllipticCurvePublicKey):
                        info["key_info"] = f"EC, curve {public_key.curve.name}"
                    else:
                        info["key_info"] = type(public_key).__name__
                    info["pubkey_pem"] = public_key.public_bytes(
                        serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    ).decode()
                except Exception:
                    logger.exception("Cannot parse signer certificate for %s",
                                     sig.field_name)

                try:
                    status = validate_pdf_signature(
                        sig, ValidationContext(allow_fetching=False))
                    info["intact"] = status.intact
                    info["valid_crypto"] = status.valid
                except Exception:
                    logger.exception("Integrity check failed for %s",
                                     sig.field_name)

                results.append(info)
    except Exception:
        logger.exception("Failed to read signature details from %s", pdf_path)
    return results
