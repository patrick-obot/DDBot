#!/bin/bash
# DDBot Raspberry Pi Setup Script
# Run as: curl -sSL https://raw.githubusercontent.com/patrick-obot/DDBot/master/setup-pi.sh | bash
# Or: bash setup-pi.sh

set -e

echo "=========================================="
echo "  DDBot - Raspberry Pi Setup"
echo "=========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/ddbot"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo bash setup-pi.sh)${NC}"
    exit 1
fi

# Check architecture
ARCH=$(uname -m)
echo -e "${YELLOW}Detected architecture: $ARCH${NC}"

# Update system
echo -e "\n${GREEN}[1/7] Updating system packages...${NC}"
apt update && apt upgrade -y

# Install system dependencies
echo -e "\n${GREEN}[2/7] Installing system dependencies...${NC}"
apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    chromium-browser \
    git \
    curl \
    xvfb \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2

# Clone or update repo
echo -e "\n${GREEN}[3/7] Setting up DDBot...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "Cloning repository..."
    git clone https://github.com/patrick-obot/DDBot.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Create virtual environment
echo -e "\n${GREEN}[4/7] Creating Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo -e "\n${GREEN}[5/7] Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright with Chromium
echo -e "\n${GREEN}[6/7] Installing Playwright browser...${NC}"
# Use system Chromium on Pi (ARM compatible)
export PLAYWRIGHT_BROWSERS_PATH=/usr/bin
# Skip Playwright browser download - we'll use system Chromium
pip install playwright
playwright install-deps chromium 2>/dev/null || true

# Create data directory
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/logs"

# Create .env file if it doesn't exist
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo -e "\n${GREEN}[6.5/7] Creating .env configuration...${NC}"
    cat > "$INSTALL_DIR/.env" << 'ENVEOF'
# Services to monitor (comma-separated)
DD_SERVICES=mtn

# Alert threshold (number of reports to trigger alert)
DD_THRESHOLD=10

# Polling interval in seconds (30 minutes)
DD_POLL_INTERVAL=1800

# Alert cooldown in seconds (15 minutes)
DD_ALERT_COOLDOWN=900

# OpenClaw gateway config (for WhatsApp)
OPENCLAW_GATEWAY_URL=http://77.37.125.213:50548
OPENCLAW_GATEWAY_TOKEN=

# WhatsApp recipients (comma-separated, with country code, no +)
WHATSAPP_RECIPIENTS=

# Telegram bot config
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_IDS=

# Chrome path (use system Chromium on Pi)
DD_CHROME_PATH=/usr/bin/chromium-browser

# Logging level
LOG_LEVEL=INFO
ENVEOF
    echo -e "${YELLOW}Created $INSTALL_DIR/.env - Please edit with your credentials${NC}"
fi

# Create systemd service
echo -e "\n${GREEN}[7/7] Creating systemd service...${NC}"
cat > /etc/systemd/system/ddbot.service << 'SERVICEEOF'
[Unit]
Description=DDBot - DownDetector Alert Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ddbot
Environment=DISPLAY=:99
ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1280x720x24 &
ExecStart=/opt/ddbot/venv/bin/python -m ddbot.main
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Alternative service using xvfb-run (simpler)
cat > /etc/systemd/system/ddbot.service << 'SERVICEEOF'
[Unit]
Description=DDBot - DownDetector Alert Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ddbot
ExecStart=/usr/bin/xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24" /opt/ddbot/venv/bin/python -m ddbot.main
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Reload systemd
systemctl daemon-reload

echo ""
echo -e "${GREEN}=========================================="
echo "  DDBot Installation Complete!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Edit the configuration file:"
echo -e "   ${YELLOW}sudo nano $INSTALL_DIR/.env${NC}"
echo ""
echo "2. Add your credentials:"
echo "   - OPENCLAW_GATEWAY_TOKEN (for WhatsApp)"
echo "   - WHATSAPP_RECIPIENTS (e.g., 27123456789 or groupid@g.us)"
echo "   - TELEGRAM_BOT_TOKEN (from @BotFather)"
echo "   - TELEGRAM_CHAT_IDS (your chat ID)"
echo ""
echo "3. Test the bot:"
echo -e "   ${YELLOW}cd $INSTALL_DIR && source venv/bin/activate${NC}"
echo -e "   ${YELLOW}python -m ddbot.main --once${NC}"
echo ""
echo "4. Start the service:"
echo -e "   ${YELLOW}sudo systemctl enable ddbot${NC}"
echo -e "   ${YELLOW}sudo systemctl start ddbot${NC}"
echo ""
echo "5. Check logs:"
echo -e "   ${YELLOW}sudo journalctl -u ddbot -f${NC}"
echo ""
