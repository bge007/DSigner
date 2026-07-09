"""
Utility functions for PDF Digital Signer
"""
import os
from datetime import datetime


def validate_pdf_path(pdf_path):
    """Validate if PDF path exists and is readable"""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if not os.path.isfile(pdf_path):
        raise IsADirectoryError(f"Path is not a file: {pdf_path}")

    if not pdf_path.lower().endswith('.pdf'):
        raise ValueError(f"File is not a PDF: {pdf_path}")

    if not os.access(pdf_path, os.R_OK):
        raise PermissionError(f"No read permission for: {pdf_path}")

    return True


def validate_position(position, page_width, page_height):
    """Validate signature position"""
    x, y = position

    if x < 0 or y < 0:
        raise ValueError("Position coordinates must be positive")

    if x > page_width or y > page_height:
        raise ValueError(f"Position out of page bounds: ({x}, {y})")

    return True


def validate_size(size, max_width=500, max_height=300):
    """Validate signature size"""
    width, height = size

    if width <= 0 or height <= 0:
        raise ValueError("Size must be positive")

    if width > max_width or height > max_height:
        raise ValueError(f"Size exceeds maximum: {width}x{height}")

    return True


def get_file_size_mb(file_path):
    """Get file size in MB"""
    size_bytes = os.path.getsize(file_path)
    return size_bytes / (1024 * 1024)


def format_timestamp(dt=None):
    """Format datetime to readable string"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def ensure_directory(directory):
    """Ensure directory exists, create if needed"""
    os.makedirs(directory, exist_ok=True)
    return directory


def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename


class Logger:
    """Simple logging utility"""

    def __init__(self, log_file=None):
        self.log_file = log_file

    def log(self, message, level="INFO"):
        """Log message with timestamp"""
        timestamp = format_timestamp()
        log_msg = f"[{timestamp}] {level}: {message}"

        print(log_msg)

        if self.log_file:
            with open(self.log_file, "a") as f:
                f.write(log_msg + "\n")

    def info(self, message):
        self.log(message, "INFO")

    def warning(self, message):
        self.log(message, "WARNING")

    def error(self, message):
        self.log(message, "ERROR")

    def debug(self, message):
        self.log(message, "DEBUG")
