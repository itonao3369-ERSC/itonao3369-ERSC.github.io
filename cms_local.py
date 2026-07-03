"""
エスエス技研 ローカルCMS（GitHub Pages対応版）
==============================================
GitHub Pages では /api/data が使えないため、
このツールは HTML ファイルを直接書き換えて保存します。

起動方法:
  python cms_local.py

ブラウザが自動で http://localhost:8080 を開きます。
編集・保存後は GitHub Desktop で Push するだけで公開されます。
"""

import json, re, shutil, threading, webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR   = Path(__file__).parent
DATA_FILE  = BASE_DIR / "site_data.json"
INDEX_HTML = BASE_DIR / "index.html"
PROD_HTML  = BASE_DIR / "products.html"
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

PORT = 8080

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".ico":  "image/x-icon",
}

# ── データ管理 ────────────────────────────────────────────
def load_data():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))

def backup(path: Path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"{path.stem}_{ts}{path.suffix}"
    shutil.copy(path, dst)
    # 古いバックアップを削除（各ファイル10件まで）
    pattern = f"{path.stem}_*{path.suffix}"
    old = sorted(BACKUP_DIR.glob(pattern))
    for f in old[:-10]:
        f.unlink()

def save_data(data: dict):
    backup(DATA_FILE)
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ── HTML 直接書き換え ─────────────────────────────────────
def replace_between(html: str, marker_id: str, new_content: str) -> str:
    """id="marker_id" を持つ要素の内容を置換する"""
    # <tag id="marker_id"...>...</tag> パターン
    pattern = rf'(<[^>]+\bid="{re.escape(marker_id)}"[^>]*>)(.*?)(</[^>]+>)'
    result = re.sub(pattern, rf'\g<1>{re.escape(new_content)}\3',
                    html, flags=re.DOTALL)
    return result

def update_index_html(data: dict):
    """index.html の d- 付きIDを持つ要素を書き換える"""
    if not INDEX_HTML.exists():
        return
    backup(INDEX_HTML)
    html = INDEX_HTML.read_text(encoding="utf-8")
    c, h = data["company"], data["hero"]

    replacements = {
        "d-eyebrow":     h.get("eyebrow", ""),
        "d-hero-body":   h.get("body", ""),
        "d-btn-primary": h.get("btn_primary", ""),
        "d-btn-outline": h.get("btn_outline", ""),
        "d-name":        c.get("name", ""),
        "d-name-en":     c.get("name_en", ""),
        "d-tel":         c.get("tel", ""),
        "d-fax":         c.get("fax", ""),
        "d-tel2":        c.get("tel", ""),
        "d-fax2":        c.get("fax", ""),
        "d-address2":    c.get("address", ""),
        "d-hours":       c.get("business_hours", ""),
        "d-message":     c.get("message", ""),
        "d-message-author": "— " + c.get("message_author", ""),
    }

    for elem_id, value in replacements.items():
        if not value:
            continue
        pattern = rf'(<[^>]+\bid="{re.escape(elem_id)}"[^>]*>)(.*?)(</\w+>)'
        html = re.sub(pattern,
                      lambda m: m.group(1) + value + m.group(3),
                      html, flags=re.DOTALL)

    # 住所は <br> を含むので別処理
    addr = f"〒{c.get('zip','')}<br>{c.get('address','')}"
    pattern_addr = r'(<[^>]+\bid="d-address"[^>]*>)(.*?)(</\w+>)'
    html = re.sub(pattern_addr,
                  lambda m: m.group(1) + addr + m.group(3),
                  html, flags=re.DOTALL)

    # ヒーロータイトル
    t1 = h.get("title_line1", "")
    t2 = h.get("title_line2", "")
    t3 = h.get("title_line3", "")
    if t1 or t2 or t3:
        new_title = f"{t1}<br><span>{t2}</span>"
        if t3:
            new_title += f"<br><span>{t3}</span>"
        pattern_title = r'(<[^>]+\bid="d-hero-title"[^>]*>)(.*?)(</h1>)'
        html = re.sub(pattern_title,
                      lambda m: m.group(1) + "\n      " + new_title + "\n    " + m.group(3),
                      html, flags=re.DOTALL)

    INDEX_HTML.write_text(html, encoding="utf-8")


# ── HTTPハンドラ ──────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"  {format % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path):
        mime = MIME.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def send_err(self, msg="Not Found", status=404):
        body = msg.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
        p = urlparse(self.path).path.rstrip("/") or "/"
        static = {
            "/":              "index.html",
            "/index.html":    "index.html",
            "/products.html": "products.html",
            "/admin":         "admin.html",
            "/admin.html":    "admin.html",
        }
        if p in static:
            f = BASE_DIR / static[p]
            self.send_file(f) if f.exists() else self.send_err(f"{static[p]} not found")
        elif p == "/api/data":
            self.send_json(load_data())
        elif p == "/api/backups":
            files = sorted(BACKUP_DIR.glob("*.json"), reverse=True)
            self.send_json([{"name": f.name, "size": f.stat().st_size}
                            for f in files[:10]])
        else:
            f = BASE_DIR / p.lstrip("/")
            self.send_file(f) if (f.exists() and f.is_file()) else self.send_err()

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = self.read_json_body()
            data = load_data()

            if p == "/api/company":
                data["company"].update(body)
            elif p == "/api/hero":
                data["hero"].update(body)
            elif p == "/api/stats":
                data["stats"] = body["stats"]
            elif p.startswith("/api/product/"):
                parts = p.split("/")
                pid = parts[3]
                sub = parts[4] if len(parts) > 4 else None
                for prod in data["products"]:
                    if prod["id"] == pid:
                        if sub == "features":
                            prod["features"] = body["features"]
                        else:
                            prod.update(body)
                        break
            else:
                self.send_json({"error": "unknown"}, 404)
                return

            save_data(data)

            # ★ HTML を直接書き換えて GitHub Pages でも反映されるようにする
            update_index_html(data)

            self.send_json({"ok": True})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json({"error": str(e)}, 500)


# ── 起動 ─────────────────────────────────────────────────
if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}/admin"
    print("=" * 52)
    print("  SS-Giken Local CMS  （GitHub Pages対応版）")
    print(f"  管理画面 → {url}")
    print(f"  サイト確認 → http://localhost:{PORT}/")
    print()
    print("  保存後は GitHub Desktop で Push するだけ！")
    print("  終了: Ctrl+C")
    print("=" * 52)
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
