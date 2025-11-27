#!/bin/bash
# Arch Linux dependency installation script for Polkadot build environment
# IMPORTANT: Run this as your SUDO USER (not as root)
# Example: Run as 'chris' user, not as 'root'

set -e  # Exit on error

# Check if running as root and warn
if [ "$EUID" -eq 0 ]; then
    echo "WARNING: You are running this script as root!"
    echo "This script should be run as your sudo user (e.g., 'chris'), not as root."
    echo "Rust will be installed in the current user's home directory."
    echo ""
    read -p "Are you sure you want to continue as root? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Exiting. Please run this script as your sudo user."
        exit 1
    fi
fi

echo "Installing system packages via pacman..."
sudo pacman -S --needed git clang curl openssl protobuf make cmake python-pip

echo "Installing Rust via rustup..."
if command -v rustc &> /dev/null && [ ! -d "$HOME/.cargo" ]; then
    echo "System Rust detected. Installing rustup alongside it..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
else
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi

echo "Configuring Rust environment..."
source $HOME/.cargo/env

echo "Creating system-wide Rust PATH configuration..."
sudo tee /etc/profile.d/rustup.sh > /dev/null << 'EOF'
# Add user's cargo bin to PATH with higher priority than /usr/bin
if [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi
EOF
sudo chmod +x /etc/profile.d/rustup.sh

echo "Installing Python packages..."
pip3 install --break-system-packages psutil pyarrow paretoset tomlkit python-dateutil

echo ""
echo "✓ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Add wasm target: rustup target add wasm32-unknown-unknown"
echo "2. Log out and back in (or restart shell) for PATH changes to take effect"
echo "3. Verify installation with: which rustc && rustc --version && python3 -c 'import psutil, pyarrow'"
echo "4. Ensure 'which rustc' shows ~/.cargo/bin/rustc (not /usr/bin/rustc)"
