"""
Setup script for DSigner application
"""
import os
import sys
import subprocess


def create_directories():
    """Create necessary directories"""
    dirs = ['keys', 'signed_pdfs', 'temp']
    for dir_name in dirs:
        os.makedirs(dir_name, exist_ok=True)
        print(f"✓ Created directory: {dir_name}")


def check_python_version():
    """Check Python version"""
    if sys.version_info < (3, 8):
        print("✗ Python 3.8 or higher is required")
        return False
    print(f"✓ Python version: {sys.version.split()[0]}")
    return True


def install_dependencies():
    """Install required packages"""
    print("\nInstalling dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError:
        print("✗ Failed to install dependencies")
        return False


def generate_test_keys():
    """Generate RSA keys for testing"""
    print("\nGenerating test RSA keys...")
    try:
        from core.signer import DigitalSigner
        signer = DigitalSigner()
        private_key, public_key = signer.generate_keys("test")
        print(f"✓ Generated test keys:")
        print(f"  - Private key: {private_key}")
        print(f"  - Public key: {public_key}")
        return True
    except Exception as e:
        print(f"✗ Failed to generate keys: {str(e)}")
        return False


def main():
    """Run setup"""
    print("=" * 50)
    print("PDF Digital Signer - Setup")
    print("=" * 50)

    if not check_python_version():
        return False

    create_directories()

    if not install_dependencies():
        return False

    if generate_test_keys():
        print("\n" + "=" * 50)
        print("Setup completed successfully!")
        print("=" * 50)
        print("\nTo start the application, run:")
        print("  python main.py")
        return True
    else:
        print("\n⚠ Setup completed with some warnings")
        print("You can still try to run: python main.py")
        return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
