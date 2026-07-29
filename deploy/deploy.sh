#!/bin/bash
# =============================================================================
# deploy.sh — AI 生活管家 EC2 一鍵部署腳本
# 適用：Amazon Linux 2023 / Ubuntu 22.04 (t3.medium 以上)
# 用法：sudo bash deploy.sh
#
# 執行前請先設定下列環境變數（或直接修改下方 CONFIG 區段）：
#   export REPO_URL="https://github.com/your-org/your-repo.git"
#   export APP_DIR="/opt/butler"
#   export BRANCH="feature/schema-align-pdf"
# =============================================================================
set -euo pipefail

# ── CONFIG ───────────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/your-org/ai-life-butler.git}"
BRANCH="${BRANCH:-feature/schema-align-pdf}"
APP_DIR="${APP_DIR:-/opt/butler}"
DATA_DIR="${DATA_DIR:-/data}"          # EBS 掛載點（butler.db 存這裡）
APP_USER="${APP_USER:-ec2-user}"       # Amazon Linux: ec2-user / Ubuntu: ubuntu
PYTHON_VER="3.11"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"

# ── 顏色輸出 ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

info "=========================================="
info "  AI 生活管家 — EC2 部署腳本"
info "  Branch: ${BRANCH}"
info "  App Dir: ${APP_DIR}"
info "  Data Dir: ${DATA_DIR}"
info "=========================================="

# ── 1. 偵測 OS ───────────────────────────────────────────────────────────────
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="${ID}"
else
    error "無法偵測作業系統"
fi
info "偵測到 OS: ${OS_ID}"

# ── 2. 系統更新 & 安裝依賴 ───────────────────────────────────────────────────
info "安裝系統依賴..."
if [[ "${OS_ID}" == "amzn" ]]; then
    dnf update -y
    dnf install -y git python${PYTHON_VER} python${PYTHON_VER}-pip \
        gcc openssl-devel libffi-devel
    # uv 安裝
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
elif [[ "${OS_ID}" == "ubuntu" ]]; then
    apt-get update -y
    apt-get install -y git python${PYTHON_VER} python${PYTHON_VER}-pip \
        python${PYTHON_VER}-venv build-essential libssl-dev libffi-dev
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    error "不支援的 OS: ${OS_ID}"
fi

# ── 3. 建立 /data 目錄（EBS 掛載點）─────────────────────────────────────────
info "設定資料目錄 ${DATA_DIR}..."
mkdir -p "${DATA_DIR}"
chown "${APP_USER}:${APP_USER}" "${DATA_DIR}"

# 若 /dev/xvdf 存在（額外 EBS），自動掛載
if lsblk | grep -q xvdf; then
    info "偵測到 EBS /dev/xvdf，嘗試掛載..."
    if ! blkid /dev/xvdf | grep -q ext4; then
        mkfs.ext4 /dev/xvdf
    fi
    mount /dev/xvdf "${DATA_DIR}" || warn "EBS 已掛載或掛載失敗，繼續..."
    # 加入 /etc/fstab 確保重啟後自動掛載
    if ! grep -q "${DATA_DIR}" /etc/fstab; then
        echo "/dev/xvdf  ${DATA_DIR}  ext4  defaults,nofail  0  2" >> /etc/fstab
    fi
    chown "${APP_USER}:${APP_USER}" "${DATA_DIR}"
fi

# ── 4. Clone / 更新 Repo ────────────────────────────────────────────────────
info "部署應用程式到 ${APP_DIR}..."
if [ -d "${APP_DIR}/.git" ]; then
    info "Repo 已存在，拉取最新版本..."
    cd "${APP_DIR}"
    sudo -u "${APP_USER}" git fetch origin
    sudo -u "${APP_USER}" git checkout "${BRANCH}"
    sudo -u "${APP_USER}" git pull origin "${BRANCH}"
else
    sudo -u "${APP_USER}" git clone -b "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
fi

# ── 5. 建立 venv & 安裝 Python 套件 ─────────────────────────────────────────
info "安裝 Python 套件..."
cd "${APP_DIR}"
sudo -u "${APP_USER}" uv venv --python python${PYTHON_VER} .venv
sudo -u "${APP_USER}" .venv/bin/pip install --upgrade pip
sudo -u "${APP_USER}" uv pip install -r requirements.txt

# ── 6. 設定 .env（從 Secrets Manager 或本地範本）────────────────────────────
info "設定環境變數..."
ENV_FILE="${APP_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    if [ -f "${APP_DIR}/.env.aws" ]; then
        cp "${APP_DIR}/.env.aws" "${ENV_FILE}"
        warn ".env 從 .env.aws 複製，請確認填入正確金鑰"
    else
        warn ".env 不存在，請手動建立或從 Secrets Manager 載入"
    fi
fi
chown "${APP_USER}:${APP_USER}" "${ENV_FILE}" 2>/dev/null || true
chmod 600 "${ENV_FILE}" 2>/dev/null || true

# ── 7. 設定 DB 路徑指向 EBS ─────────────────────────────────────────────────
info "設定 DB 路徑 -> ${DATA_DIR}/butler.db ..."
# 在 .env 加入 DB_PATH（app_helpers.py 讀取此變數）
if ! grep -q "^DB_PATH=" "${ENV_FILE}" 2>/dev/null; then
    echo "DB_PATH=${DATA_DIR}/butler.db" >> "${ENV_FILE}"
fi

# ── 8. 初始化資料庫（首次執行）──────────────────────────────────────────────
info "初始化資料庫..."
if [ ! -f "${DATA_DIR}/butler.db" ]; then
    cd "${APP_DIR}"
    sudo -u "${APP_USER}" bash -c "
        source .venv/bin/activate
        export ALLOW_SEED_RESET=yes
        # 載入 .env
        set -a; source .env; set +a
        python seed.py
    "
    info "資料庫初始化完成：${DATA_DIR}/butler.db"
else
    info "資料庫已存在，跳過初始化"
fi

# ── 9. 建立 uploads 目錄軟連結到 EBS ────────────────────────────────────────
mkdir -p "${DATA_DIR}/uploads"
chown "${APP_USER}:${APP_USER}" "${DATA_DIR}/uploads"
if [ ! -L "${APP_DIR}/uploads" ]; then
    rm -rf "${APP_DIR}/uploads"
    ln -s "${DATA_DIR}/uploads" "${APP_DIR}/uploads"
fi

# ── 10. 安裝 systemd service ────────────────────────────────────────────────
info "安裝 systemd services..."

# 消費者前端
cp "${APP_DIR}/deploy/butler-app.service"    /etc/systemd/system/
# 廠商後台
cp "${APP_DIR}/deploy/butler-vendor.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable butler-app butler-vendor
systemctl restart butler-app butler-vendor

# ── 11. 設定防火牆（若有 firewalld）────────────────────────────────────────
if systemctl is-active --quiet firewalld 2>/dev/null; then
    info "設定 firewalld..."
    firewall-cmd --permanent --add-port=8501/tcp
    firewall-cmd --permanent --add-port=8502/tcp
    firewall-cmd --reload
fi

# ── 12. 驗證服務啟動 ────────────────────────────────────────────────────────
info "等待服務啟動（15秒）..."
sleep 15

for PORT in 8501 8502; do
    if curl -sf "http://localhost:${PORT}" -o /dev/null 2>&1; then
        info "✅ Port ${PORT} 回應正常"
    else
        warn "⚠️  Port ${PORT} 尚未回應，請檢查：journalctl -u butler-app -n 50"
    fi
done

# ── 完成 ─────────────────────────────────────────────────────────────────────
INSTANCE_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "未知")
info "=========================================="
info "  部署完成！"
info "  消費者前端: http://${INSTANCE_IP}:8501"
info "  廠商後台:   http://${INSTANCE_IP}:8502"
info ""
info "  查看 log："
info "    journalctl -u butler-app -f"
info "    journalctl -u butler-vendor -f"
info ""
info "  重啟服務："
info "    systemctl restart butler-app butler-vendor"
info "=========================================="
