# DSigner

A professional digital signing application for PDF documents with a visual interface for selecting signature position.

## Features

- 📄 **PDF Viewing**: Load and view PDF documents with page navigation
- 🖱️ **Position Selection**: Click on the PDF to select where you want the signature to appear
- 🔐 **Digital Signing**: Sign PDFs with timestamp and signer information
- 📍 **Customizable Signature**: Adjust position, size, and signature details
- 🎨 **Visual Interface**: User-friendly PyQt5 interface with split view
- ⚙️ **RSA Encryption**: Support for cryptographic signing

## Project Structure

```
PDF-DSigner/
├── main.py                 # Application entry point
├── config.py              # Configuration settings
├── requirements.txt       # Python dependencies
├── ui/                    # User interface modules
│   ├── main_window.py     # Main application window
│   ├── pdf_viewer.py      # PDF viewer with position selection
│   └── signature_panel.py # Signature details panel
├── core/                  # Core functionality
│   ├── pdf_handler.py     # PDF manipulation utilities
│   └── signer.py          # Digital signing logic
├── keys/                  # Generated RSA keys (auto-created)
└── signed_pdfs/           # Output directory for signed PDFs
```

## Installation

### 1. Create Virtual Environment
```bash
cd C:\BGE\AI\PDF-DSigner
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Application
```bash
python main.py
```

## Dependencies

- **PyQt5**: GUI framework
- **pdf2image**: Convert PDF to images for display
- **Pillow**: Image processing
- **pypdf**: PDF manipulation
- **cryptography**: Digital signing and encryption
- **reportlab**: PDF generation
- **python-dateutil**: Date utilities

## Usage

### Basic Workflow

1. **Open PDF**: Click "Open PDF" button and select a PDF file
2. **Select Position**: Click on the PDF page where you want the signature to appear
3. **Adjust Settings**:
   - Modify X/Y coordinates if needed
   - Adjust signature size (width/height)
   - Enter signer information
4. **Sign**: Click "Sign PDF" and choose output location
5. **Save**: The signed PDF is saved with signature and timestamp

### Signature Details

The signature includes:
- Signer name
- Date and time of signing
- Position coordinates
- Optional reason for signing

### Position Selection

- **Click on PDF**: Left-click on any location in the PDF to set the signature position
- **Visual Indicator**: A red circle marks the selected position
- **Manual Adjustment**: Use X/Y spinboxes to fine-tune the position
- **Size Settings**: Adjust width and height for the signature box

## Features in Detail

### PDF Viewer
- Zoom and pan capabilities
- Page navigation support
- Real-time position feedback
- Visual position indicator with coordinates

### Signature Settings
- Customizable signer name
- Automatic timestamp
- Optional signing reason
- Flexible positioning and sizing

### Digital Signing
- RSA-based cryptographic signing
- SHA256 hashing
- Signature verification capabilities
- Secure key generation and storage

## Configuration

Edit `config.py` to customize:
- Default signature dimensions
- Key size for RSA encryption
- Maximum PDF file size
- PDF rendering DPI
- Output directory

## Advanced Features (Roadmap)

- [ ] Multi-page signing
- [ ] Batch signing
- [ ] Signature verification
- [ ] Certificate support
- [ ] Custom signature images
- [ ] PDF form field signing
- [ ] Advanced encryption options

## Security Notes

- Private keys are stored locally in the `keys/` directory
- Ensure proper file permissions on the keys directory
- Use strong passphrases for production signing
- Verify PDF integrity after signing

## Troubleshooting

### PDF Won't Load
- Check file permissions
- Verify PDF is not corrupted
- Try with a different PDF file

### Signature Not Appearing
- Ensure position is within page bounds
- Check that X/Y coordinates are positive
- Verify signature size is not too small

### Key Generation Issues
- Ensure `keys/` directory exists and is writable
- Check available disk space
- Try regenerating keys

## System Requirements

- Python 3.8+
- Windows/macOS/Linux
- 500MB+ disk space
- 2GB+ RAM

## License

MIT License

## Support

For issues or questions, check the troubleshooting section or review the code documentation.

## Version History

### v1.0.0 (Initial Release)
- PDF viewing with position selection
- Visual signature creation
- Basic digital signing
- RSA key generation
- User-friendly interface
