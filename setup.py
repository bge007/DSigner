"""
Setup script for DSigner application
"""
import os
import sys
import subprocess


def check_python_version():
    """Check Python version"""
    if sys.version_info < (3, 9):
        print("Python 3.9 or higher is required")
        return False
    print(f"Python version: {sys.version.split()[0]}")
    return True


def install_dependencies():
    """Install required packages"""
    print("\nInstalling dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "-r", "requirements.txt"])
        print("Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError:
        print("Failed to install dependencies")
        return False


def main():
    print("=" * 50)
    print("DSigner - Setup")
    print("=" * 50)

    if not check_python_version():
        return False

    if not install_dependencies():
        return False

    print("\nSetup completed. To start the application, run:")
    print("  python main.py")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
