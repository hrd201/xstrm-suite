#!/usr/bin/env bash
#
# xstrm-suite 一键安装脚本
# 用法:
#   ./install.sh                 # 交互式安装
#   ./install.sh --non-interactive  # 静默安装（使用默认配置）
#   ./install.sh --help          # 查看帮助
#

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 变量定义
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/xstrm-suite}"
BIN_LINK="/usr/local/bin/xstrm"
ADMIN_LINK="/usr/local/bin/xstrm-admin"
SERVICE_DIR="/etc/systemd/system"
NON_INTERACTIVE=false

# 帮助信息
show_help() {
    cat <<EOF
xstrm-suite 一键安装脚本

用法:
  $0 [选项]

选项:
  --non-interactive    静默模式，使用默认配置
  --install-root PATH  指定安装目录 (默认: /opt/xstrm-suite)
  --help, -h           显示此帮助信息

示例:
  $0                           # 交互式安装
  $0 --non-interactive         # 使用默认配置安装
  --install-root /custom/path  # 安装到自定义目录

EOF
}

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# 检查命令是否存在
need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        log_error "命令 '$1' 未找到，请先安装"
        return 1
    fi
    return 0
}

# 检查并安装 Python
install_python() {
    log_info "检查 Python 环境..."
    
    if need_cmd python3; then
        local py_version
        py_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        log_success "Python3 已安装: $(python3 --version 2>&1)"
        
        # 检查 PyYAML
        if python3 - <<'PY' 2>/dev/null
import yaml
PY
        then
            log_success "PyYAML 已安装"
        else
            log_info "安装 PyYAML..."
            python3 -m pip install --quiet PyYAML
            log_success "PyYAML 安装完成"
        fi
    else
        log_info "安装 Python3..."
        if need_cmd apt-get; then
            apt-get update && apt-get install -y python3 python3-pip python3-yaml
        elif need_cmd dnf; then
            dnf install -y python3 python3-pip python3-PyYAML
        elif need_cmd yum; then
            yum install -y python3 python3-pip || true
            python3 -m pip install PyYAML
        elif need_cmd apk; then
            apk add --no-cache python3 py3-pip py3-yaml
        else
            log_error "无法自动安装 Python3，请手动安装后重试"
            exit 1
        fi
        log_success "Python3 安装完成"
    fi
}

# 检查 Docker
check_docker() {
    log_info "检查 Docker..."
    
    if ! need_cmd docker; then
        log_error "Docker 未安装，请先安装 Docker: https://docs.docker.com/install/"
        exit 1
    fi
    
    local docker_version
    docker_version=$(docker --version 2>&1)
    log_success "Docker 已安装: $docker_version"
    
    # 检查 docker compose
    if docker compose version >/dev/null 2>&1; then
        log_success "Docker Compose (plugin) 已安装"
    elif need_cmd docker-compose; then
        log_success "Docker Compose 已安装"
    else
        log_warn "Docker Compose 未安装，部分功能可能无法使用"
    fi
    
    # 检查 Docker 服务状态
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker 服务未运行，请启动 Docker: systemctl start docker"
        exit 1
    fi
    log_success "Docker 服务运行正常"
}

# 创建符号链接
install_bin_links() {
    log_info "安装命令链接..."
    
    mkdir -p "$(dirname "$BIN_LINK")"
    mkdir -p "$(dirname "$ADMIN_LINK")"
    
    ln -sf "$INSTALL_ROOT/bin/xstrm" "$BIN_LINK"
    ln -sf "$INSTALL_ROOT/bin/xstrm-admin" "$ADMIN_LINK"
    
    log_success "命令链接已创建: xstrm, xstrm-admin"
}

# 安装系统服务
install_systemd_services() {
    log_info "安装 systemd 服务..."
    
    mkdir -p "$SERVICE_DIR"
    
    # xstrm-admin-api 服务
    if [ -f "$INSTALL_ROOT/services/xstrm-admin-api.service" ]; then
        sed "s|/opt/xstrm-suite|$INSTALL_ROOT|g" \
            "$INSTALL_ROOT/services/xstrm-admin-api.service" \
            > "$SERVICE_DIR/xstrm-admin-api.service"
        log_success "服务已安装: xstrm-admin-api.service"
    fi
    
    # 重新加载 systemd
    if need_cmd systemctl; then
        systemctl daemon-reload 2>/dev/null || true
    fi
}

# 同步项目文件
sync_project() {
    log_info "同步项目到 $INSTALL_ROOT..."
    
    mkdir -p "$INSTALL_ROOT"
    
    # 排除不必要的文件
    rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='data' --exclude='logs' \
        "$BASE_DIR/" "$INSTALL_ROOT/"
    
    # 确保脚本可执行
    chmod +x "$INSTALL_ROOT/bin/xstrm" "$INSTALL_ROOT/bin/xstrm-admin" 2>/dev/null || true
    chmod +x "$INSTALL_ROOT/scripts/"*.sh 2>/dev/null || true
    chmod +x "$INSTALL_ROOT/scripts/strm_x.py" "$INSTALL_ROOT/scripts/admin_api.py" 2>/dev/null || true
    chmod +x "$INSTALL_ROOT/scripts/render_runtime.py" 2>/dev/null || true
    
    log_success "项目同步完成"
}

# 交互式配置
configure_interactive() {
    log_info "启动交互式配置..."
    python3 "$INSTALL_ROOT/scripts/configure_runtime.py"
}

# 使用默认配置
configure_default() {
    log_info "使用默认配置..."
    
    local runtime_config="$INSTALL_ROOT/config/runtime.yaml"
    mkdir -p "$(dirname "$runtime_config")"
    
    # 创建默认运行时配置
    cat > "$runtime_config" <<'EOF'
project:
  install_root: /opt/xstrm-suite
emby:
  host: http://127.0.0.1:8096
  api_key: ""
alist:
  scheme: http
  host: 172.17.0.1
  port: 5244
  token: ""
  public_addr: http://127.0.0.1:5244
  sign_enable: false
  sign_expire_time: 12
nginx:
  server_name: _
  http_port: 8095
  https_enabled: false
  https_port: 8096
  backend_scheme: http
  backend_port: 18095
  ssl_cert: ""
  ssl_key: ""
mount:
  media_mount_path: []
  output_root: /emby-strm
xstrm:
  mode: mirror
  strm_mode: auto
  incremental_only: true
EOF
    
    log_success "默认配置已创建: $runtime_config"
    
    # 创建默认 strm-sync.yaml
    local strm_config="$INSTALL_ROOT/config/strm-sync.yaml"
    cat > "$strm_config" <<'EOF'
output_root: /emby-strm
state_file: /opt/xstrm-suite/data/strm-sync-state.json
mode: mirror
alist:
  base_url: http://172.17.0.1:5244
  token: ""
  public_url: http://127.0.0.1:5244
scan:
  default_depth: 1
  incremental_only: true
  include_ext:
    - .mp4
    - .mkv
    - .avi
    - .ts
    - .m2ts
sources: []
emby2alist:
  media_mount_path: []
EOF
    
    log_success "默认 strm-sync.yaml 已创建: $strm_config"
    log_warn "请编辑配置文件并填入您的 AList token 和 Emby API Key"
}

# 渲染运行时配置
render_runtime() {
    log_info "渲染运行时配置..."
    
    if [ -f "$INSTALL_ROOT/scripts/render_runtime.py" ]; then
        cd "$INSTALL_ROOT" && python3 scripts/render_runtime.py
        log_success "运行时配置渲染完成"
    else
        log_warn "render_runtime.py 不存在，跳过"
    fi
}

# 应用运行时配置
apply_runtime() {
    log_info "应用运行时配置..."
    
    if [ -f "$INSTALL_ROOT/scripts/apply_runtime.py" ]; then
        cd "$INSTALL_ROOT" && python3 scripts/apply_runtime.py
        log_success "运行时配置应用完成"
    else
        log_warn "apply_runtime.py 不存在，跳过"
    fi
}

# 启动服务
start_services() {
    log_info "启动服务..."
    
    # 启动 Docker 容器
    if [ -f "$INSTALL_ROOT/docker-compose.yml" ]; then
        log_info "启动 Docker 容器..."
        cd "$INSTALL_ROOT" && docker-compose up -d 2>/dev/null || true
    fi
    
    # 启动 xstrm-admin-api
    if need_cmd systemctl && [ -f "$SERVICE_DIR/xstrm-admin-api.service" ]; then
        log_info "启动 xstrm-admin-api 服务..."
        systemctl enable xstrm-admin-api.service 2>/dev/null || true
        systemctl start xstrm-admin-api.service 2>/dev/null || true
        
        if systemctl is-active --quiet xstrm-admin-api.service; then
            log_success "xstrm-admin-api 服务已启动"
        else
            log_warn "xstrm-admin-api 服务启动失败，请检查: systemctl status xstrm-admin-api.service"
        fi
    fi
}

# 显示安装完成信息
show_complete() {
    local admin_port
    admin_port=$(python3 - <<'PY' 2>/dev/null || echo "8095"
import yaml
try:
    cfg = yaml.safe_load(open('/opt/xstrm-suite/config/runtime.yaml', encoding='utf-8').read()) or {}
    print(cfg.get('nginx', {}).get('http_port', 8095))
except:
    print(8095)
PY
)
    
    cat <<EOF

${GREEN}========================================${NC}
${GREEN}  xstrm-suite 安装完成!${NC}
${GREEN}========================================${NC}

安装目录: $INSTALL_ROOT

命令:
  xstrm          - 运行 xstrm CLI
  xstrm-admin    - 打开管理界面

管理界面: http://localhost:$admin_port/admin/xstrm/

${YELLOW}后续步骤:${NC}
  1. 编辑配置文件:
     - $INSTALL_ROOT/config/strm-sync.yaml
     - 填入 AList Token
     - 填入 Emby API Key
  
  2. 配置扫描源:
     xstrm-admin
     # 选择 "1" 扫描已配置的目录
     # 或选择 "2" 扫描指定目录
  
  3. 查看日志:
     journalctl -u xstrm-admin-api -f

${BLUE}更多信息:${NC}
  文档: $INSTALL_ROOT/README.md
  CHANGELOG: $INSTALL_ROOT/CHANGELOG.md

EOF
}

# 主函数
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  xstrm-suite 一键安装脚本${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --non-interactive)
                NON_INTERACTIVE=true
                shift
                ;;
            --install-root)
                INSTALL_ROOT="$2"
                shift 2
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 导出安装目录
    export INSTALL_ROOT
    
    # 1. 检查并安装依赖
    install_python
    check_docker
    
    # 2. 同步项目
    sync_project
    
    # 3. 配置
    if [ "$NON_INTERACTIVE" = true ]; then
        configure_default
    else
        configure_interactive
    fi
    
    # 4. 渲染和应用配置
    render_runtime
    apply_runtime
    
    # 5. 安装命令和服务
    install_bin_links
    install_systemd_services
    
    # 6. 启动服务
    start_services
    
    # 7. 完成
    show_complete
}

# 执行主函数
main "$@"
