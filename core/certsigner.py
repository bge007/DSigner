"""
Cryptographic PDF signing (PAdES) using a Windows-store certificate.

pyhanko builds the signature container and visual appearance; the
actual private-key operation is delegated to Windows CNG through
core.wincert, so non-exportable keys and USB tokens work.
"""
import hashlib
import logging
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
                              position_pt, size_pt, page_height_pt,
                              reason="", location=""):
    """Digitally sign one page of a PDF with a visible signature box.

    position_pt is the TOP-LEFT corner of the box in PDF points measured
    from the top-left of the page (viewer coordinates); converted here to
    PDF's bottom-left origin.
    """
    x, y_top = position_pt
    w, h = size_pt
    box = (x, page_height_pt - y_top - h, x + w, page_height_pt - y_top)

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
    style = stamp.TextStampStyle(
        stamp_text=stamp_text,
        border_width=1,
        text_box_style=text.TextBoxStyle(font_size=8),
    )
    pdf_signer = signers.PdfSigner(
        meta, signer=signer, stamp_style=style,
        new_field_spec=fields.SigFieldSpec(
            sig_field_name=field_name, on_page=page_index, box=box),
    )

    with open(input_pdf, "rb") as inf:
        writer = IncrementalPdfFileWriter(inf)
        with open(output_pdf, "wb") as outf:
            pdf_signer.sign_pdf(writer, output=outf)

    logger.info("Signed %s -> %s (field %s, page %d)",
                input_pdf, output_pdf, field_name, page_index + 1)
