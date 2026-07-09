"""
Digital signing functionality for PDF documents
"""
from datetime import datetime
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pypdf import PdfReader, PdfWriter
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import hashlib
import os


class DigitalSigner:
    def __init__(self):
        self.keys_dir = "keys"
        if not os.path.exists(self.keys_dir):
            os.makedirs(self.keys_dir)

    def generate_keys(self, key_name="default", key_size=2048):
        """Generate RSA key pair for signing"""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        private_path = os.path.join(self.keys_dir, f"{key_name}_private.pem")
        public_path = os.path.join(self.keys_dir, f"{key_name}_public.pem")

        with open(private_path, "wb") as f:
            f.write(private_pem)

        with open(public_path, "wb") as f:
            f.write(public_pem)

        return private_path, public_path

    def sign_pdf(self, input_pdf, output_pdf, page_index, position_pt, size_pt,
                 signer_name, reason="", location="", include_date=True):
        """Sign a PDF page with a visual signature box.

        position_pt is the TOP-LEFT corner of the signature box in PDF
        points measured from the top-left of the page (as shown in the
        viewer); it is converted here to PDF's bottom-left origin.
        """
        try:
            reader = PdfReader(input_pdf)
            if not (0 <= page_index < len(reader.pages)):
                raise ValueError(f"Page {page_index + 1} does not exist")

            target = reader.pages[page_index]
            page_w = float(target.mediabox.width)
            page_h = float(target.mediabox.height)

            x, y_top = position_pt
            w, h = size_pt
            y = page_h - y_top - h  # bottom edge of box in PDF coords

            packet = BytesIO()
            can = canvas.Canvas(packet, pagesize=(page_w, page_h))

            # signature box
            can.setLineWidth(1)
            can.setStrokeColorRGB(0.15, 0.31, 0.55)
            can.setFillColorRGB(0.95, 0.97, 1.0)
            can.roundRect(x, y, w, h, 4, stroke=1, fill=1)

            # text lines, top-down inside the box
            name_size = max(7.0, min(12.0, h * 0.22))
            meta_size = max(6.0, name_size - 2.5)
            pad = 6.0

            lines = [("Helvetica-Bold", name_size, (0.08, 0.17, 0.36),
                      f"Digitally signed by {signer_name}")]
            if include_date:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                lines.append(("Helvetica", meta_size, (0.25, 0.3, 0.4),
                              f"Date: {timestamp}"))
            if reason:
                lines.append(("Helvetica", meta_size, (0.25, 0.3, 0.4),
                              f"Reason: {reason}"))
            if location:
                lines.append(("Helvetica", meta_size, (0.25, 0.3, 0.4),
                              f"Location: {location}"))

            text_y = y + h - pad - name_size
            for font_name, font_size, color, text in lines:
                if text_y < y + 2:
                    break
                max_w = w - 2 * pad
                while len(text) > 1 and can.stringWidth(text, font_name, font_size) > max_w:
                    text = text[:-2] + "…"
                try:
                    can.setFont(font_name, font_size)
                except:
                    can.setFont("Helvetica", font_size)
                can.setFillColorRGB(*color)
                can.drawString(x + pad, text_y, text)
                text_y -= font_size + 3

            can.save()
            packet.seek(0)

            overlay = PdfReader(packet).pages[0]

            writer = PdfWriter()
            for idx, page in enumerate(reader.pages):
                if idx == page_index:
                    page.merge_page(overlay)
                writer.add_page(page)

            with open(output_pdf, "wb") as f:
                writer.write(f)

            return True

        except Exception as e:
            raise Exception(f"Failed to sign PDF: {str(e)}")

    def verify_signature(self, pdf_path, public_key_path):
        """Verify a digital signature on a PDF (placeholder)"""
        try:
            with open(public_key_path, "rb") as f:
                public_key = serialization.load_pem_public_key(
                    f.read(),
                    backend=default_backend()
                )

            return True

        except Exception as e:
            raise Exception(f"Failed to verify signature: {str(e)}")

    def compute_file_hash(self, file_path):
        """Compute SHA256 hash of file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
