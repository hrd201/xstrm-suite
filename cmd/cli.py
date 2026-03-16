"""Command-line interface for XSTRM."""
import argparse
import json
import sys
from pathlib import Path

# Handle both module and script execution
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.config import (
    load_config,
    ensure_config,
    show_config,
    show_integration,
    build_example_target,
)
from src.state import show_state
from src.scanner import (
    run_source,
    run_all_sources,
    discover_sources,
    build_source_from_input,
)


def print_main_menu():
    """Print main menu."""
    print('\nXSTRM 菜单')
    print('1. 从已配置 AList 目录中选择扫描')
    print('2. 扫描指定 AList 目录')
    print('3. 查看同源配置')
    print('4. 定时扫描设定')
    print('5. 查看当前配置')
    print('6. 查看状态文件')
    print('0. 退出')


def cron_menu():
    """Print cron menu."""
    print('\n定时扫描设定')
    print('1. 自动发现设置（待实现）')
    print('2. 自定义扫描设置（待实现）')
    print('当前版本已支持：按已配置的 AList 目录或手工输入逻辑目录扫描。')


def choose_discovered_source(config: dict):
    """Interactive: choose from discovered sources."""
    discovered = discover_sources(config)
    if not discovered:
        print('未发现可扫描目录')
        return

    print('\n已配置的 AList 扫描目录：')
    for idx, item in enumerate(discovered, 1):
        print(f'{idx}. {item["output_prefix"]}')

    choice = input('请输入要扫描的编号（0 取消）: ').strip()
    if not choice or choice == '0':
        print('已取消')
        return

    try:
        idx = int(choice)
        if idx < 1 or idx > len(discovered):
            raise ValueError
    except ValueError:
        print('输入无效')
        return

    picked = discovered[idx - 1]
    print('当前使用 AList 目录扫描模式：直接扫描逻辑目录并生成对应 .strm。')
    run_source(config, picked)


def scan_specified_dir(config: dict):
    """Interactive: scan specified directory."""
    source_input = input('请输入需要扫描的 AList 目录（例如 /115/电影 或 /115/电影/泰坦尼克号）: ').strip()
    if not source_input:
        print('已取消')
        return
    src = build_source_from_input(config, source_input)
    print('当前使用 AList 目录扫描模式：直接扫描逻辑目录并生成对应 .strm。')
    run_source(config, src)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description='XSTRM - STRM file management')
    parser.add_argument('--config', action='store_true', help='Show configuration')
    parser.add_argument('--state', action='store_true', help='Show state')
    parser.add_argument('--integration', action='store_true', help='Show integration config')
    parser.add_argument('--scan-all', action='store_true', help='Scan all sources')
    parser.add_argument('--scan-path', type=str, help='Scan specified path')
    parser.add_argument('--example-target', action='store_true', help='Show example target path')

    args = parser.parse_args()

    config = ensure_config(load_config())

    if args.config:
        show_config(config)
        return

    if args.state:
        show_state()
        return

    if args.integration:
        show_integration(config)
        return

    if args.example_target:
        print(build_example_target(config))
        return

    if args.scan_all:
        result = run_all_sources(config)
        print(json.dumps({'mode': 'scan_all', **result}, ensure_ascii=False))
        return

    if args.scan_path:
        print('当前使用 AList 目录扫描模式：直接扫描逻辑目录并生成对应 .strm。')
        src = build_source_from_input(config, args.scan_path.strip())
        result = run_source(config, src)
        print(json.dumps({'mode': 'scan_path', **result}, ensure_ascii=False))
        return

    # Interactive mode
    while True:
        print_main_menu()
        choice = input('请输入选项: ').strip()
        if choice == '1':
            choose_discovered_source(config)
        elif choice == '2':
            scan_specified_dir(config)
        elif choice == '3':
            show_integration(config)
        elif choice == '4':
            cron_menu()
        elif choice == '5':
            show_config(config)
        elif choice == '6':
            show_state()
        elif choice == '0':
            print('退出')
            break
        else:
            print('无效选项')


if __name__ == '__main__':
    main()
