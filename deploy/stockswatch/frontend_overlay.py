"""Apply only the StocksWatch view and API route to a clean shared frontend checkout."""

import argparse
from pathlib import Path

VIEWS = (
    "StocksWatch.tsx",
    "StocksWatchIntraday.tsx",
    "StocksWatch.css",
    "ScannerMonitor.tsx",
    "ScannerMonitor.css",
)


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("shared_frontend_anchor_changed")
    return text.replace(old, new, 1)


def integrate(source: Path, target: Path):
    if source.resolve() == target.resolve():
        raise ValueError("separate_shared_frontend_checkout_required")
    files = {}
    for name in VIEWS:
        dest = target / "src" / name
        if dest.exists() or dest.is_symlink():
            raise ValueError("existing_stockswatch_frontend_requires_manual_merge")
        files[dest] = (source / "src" / name).read_text()
    path = target / "src/main.tsx"
    content = path.read_text()
    if 'active === "StocksWatch"' in content:
        raise ValueError("existing_stockswatch_navigation_requires_manual_merge")
    if "  TrendingUp,\n" not in content:
        content = replace_once(content, "  RefreshCw,\n", "  RefreshCw,\n  TrendingUp,\n")
    content = replace_once(
        content,
        'import "./styles.css";',
        'const StocksWatch = lazy(() => import("./StocksWatch").then(m => ({ default: m.StocksWatch })));\nimport "./styles.css";',
    )
    content = replace_once(
        content,
        "const navigation = [",
        'const navigation = [\n  { name: "StocksWatch", icon: TrendingUp },',
    )
    content = replace_once(
        content,
        '        {active === "Dashboard" && <Dashboard/>}',
        '        {active === "Dashboard" && <Dashboard/>}\n        {active === "StocksWatch" && <StocksWatch />}',
    )
    files[path] = content
    path = target / "src/api.tsx"
    marker = "      if (response.status === 401) {"
    source_api = (source / "src/api.tsx").read_text()
    begin = source_api.index("        // An optional, isolated StocksWatch")
    end = source_api.index("        this.onUnauthorized?.();", begin)
    if 'path.startsWith("/api/stockswatch/")' in path.read_text():
        raise ValueError("existing_stockswatch_auth_requires_manual_merge")
    files[path] = replace_once(
        path.read_text(), marker, marker + "\n" + source_api[begin:end].rstrip()
    )
    path = target / "nginx.conf"
    source_nginx = (source / "nginx.conf").read_text()
    begin = source_nginx.index("  # Separate cookie-authenticated StocksWatch")
    end = source_nginx.index("  location /api/ {", begin)
    if "/api/stockswatch/" in path.read_text():
        raise ValueError("existing_stockswatch_proxy_requires_manual_merge")
    files[path] = replace_once(
        path.read_text(), "  location /api/ {", source_nginx[begin:end] + "  location /api/ {"
    )
    if any(path.is_symlink() for path in files):
        raise ValueError("frontend_overlay_symlink_refused")
    for path, text in files.items():
        path.write_text(text)
    return [str(p.relative_to(target)) for p in files]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks-frontend", required=True, type=Path)
    parser.add_argument("--shared-frontend", required=True, type=Path)
    args = parser.parse_args()
    for path in integrate(args.stocks_frontend, args.shared_frontend):
        print(path)


if __name__ == "__main__":
    main()
