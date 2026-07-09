"""
PDF handling utilities
"""
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
from datetime import datetime
import os


class PDFHandler:
    def __init__(self):
        pass

    def get_pdf_info(self, pdf_path):
        """Get information about the PDF"""
        try:
            reader = PdfReader(pdf_path)
            return {
                "pages": len(reader.pages),
                "title": reader.metadata.get("/Title", "N/A") if reader.metadata else "N/A",
                "author": reader.metadata.get("/Author", "N/A") if reader.metadata else "N/A",
                "created": reader.metadata.get("/CreationDate", "N/A") if reader.metadata else "N/A",
            }
        except Exception as e:
            raise Exception(f"Failed to read PDF: {str(e)}")

    def add_signature_visual(self, pdf_path, output_path, position, size, sig_text):
        """Add a visual signature to the PDF"""
        try:
            packet = BytesIO()
            can = canvas.Canvas(packet, pagesize=letter)

            x, y = position
            width, height = size

            can.setFont("Helvetica", 10)
            can.drawString(x, y, sig_text)

            can.save()

            packet.seek(0)

            signature_pdf = PdfReader(packet)
            sig_page = signature_pdf.pages[0]

            reader = PdfReader(pdf_path)
            writer = PdfWriter()

            for page_idx, page in enumerate(reader.pages):
                if page_idx == 0:
                    page.merge_page(sig_page)

                writer.add_page(page)

            with open(output_path, "wb") as f:
                writer.write(f)

            return True

        except Exception as e:
            raise Exception(f"Failed to add signature visual: {str(e)}")

    def merge_pdfs(self, pdf_list, output_path):
        """Merge multiple PDFs into one"""
        try:
            writer = PdfWriter()

            for pdf_path in pdf_list:
                reader = PdfReader(pdf_path)
                for page in reader.pages:
                    writer.add_page(page)

            with open(output_path, "wb") as f:
                writer.write(f)

            return True

        except Exception as e:
            raise Exception(f"Failed to merge PDFs: {str(e)}")

    def split_pdf(self, pdf_path, output_dir):
        """Split PDF into individual pages"""
        try:
            reader = PdfReader(pdf_path)
            output_files = []

            for idx, page in enumerate(reader.pages):
                writer = PdfWriter()
                writer.add_page(page)

                output_file = os.path.join(output_dir, f"page_{idx + 1}.pdf")
                with open(output_file, "wb") as f:
                    writer.write(f)

                output_files.append(output_file)

            return output_files

        except Exception as e:
            raise Exception(f"Failed to split PDF: {str(e)}")
