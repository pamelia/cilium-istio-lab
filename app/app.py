import json
import os
import urllib.request

import psycopg2
from flask import Flask

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "hello")
DB_PASSWORD = os.getenv("DB_PASSWORD", "hello")
DB_NAME = os.getenv("DB_NAME", "hellodb")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )


def get_message():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 'Hello from PostgreSQL'::text;")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else "No message"
    finally:
        conn.close()


def check_github_status():
    """Check GitHub API status by calling api.github.com"""
    try:
        req = urllib.request.Request(
            "https://api.github.com/", headers={"User-Agent": "hello-app/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return True, "API responding"
    except Exception as e:
        return False, str(e)[:50]
    return False, "Unknown error"


def check_cloudflare_status():
    """Check Cloudflare API status by calling api.cloudflare.com"""
    import ssl

    try:
        # Create SSL context that doesn't verify certificates
        # (needed due to ztunnel TLS handling in ambient mode)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4/",
            headers={"User-Agent": "hello-app/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
            # Cloudflare API returns 400 without auth, but that means it's reachable
            return True, "API responding"
    except urllib.request.HTTPError as e:
        # 400/401/403 means the API is reachable but requires auth
        if e.code in (400, 401, 403):
            return True, "API responding (auth required)"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:50]


@app.route("/")
def index():
    # Database status
    try:
        db_message = get_message()
        db_status = "Connected"
        db_status_class = "success"
    except Exception as e:
        db_message = str(e)
        db_status = "Disconnected"
        db_status_class = "error"

    # GitHub status
    github_ok, github_message = check_github_status()
    github_status = "Connected" if github_ok else "Unreachable"
    github_status_class = "success" if github_ok else "error"

    # Cloudflare status
    cloudflare_ok, cloudflare_message = check_cloudflare_status()
    cloudflare_status = "Connected" if cloudflare_ok else "Unreachable"
    cloudflare_status_class = "success" if cloudflare_ok else "error"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cilium Istio Lab</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            padding: 40px;
            max-width: 600px;
            width: 100%;
        }}
        h1 {{
            color: #333;
            font-size: 2rem;
            margin-bottom: 8px;
            text-align: center;
        }}
        .subtitle {{
            color: #666;
            text-align: center;
            margin-bottom: 30px;
            font-size: 0.95rem;
        }}
        .card {{
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            margin-bottom: 12px;
        }}
        .card-icon {{
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 12px;
            font-size: 1.2rem;
        }}
        .card-icon.app {{
            background: linear-gradient(135deg, #667eea, #764ba2);
        }}
        .card-icon.db {{
            background: linear-gradient(135deg, #11998e, #38ef7d);
        }}
        .card-icon.github {{
            background: linear-gradient(135deg, #24292e, #404448);
        }}
        .card-icon.cloudflare {{
            background: linear-gradient(135deg, #f38020, #faad3f);
        }}
        .card-title {{
            font-weight: 600;
            color: #333;
        }}
        .card-content {{
            color: #555;
            font-size: 0.95rem;
            padding-left: 52px;
        }}
        .status {{
            display: inline-flex;
            align-items: center;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 500;
            margin-top: 8px;
        }}
        .status.success {{
            background: #d4edda;
            color: #155724;
        }}
        .status.error {{
            background: #f8d7da;
            color: #721c24;
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
        }}
        .status.success .status-dot {{
            background: #28a745;
        }}
        .status.error .status-dot {{
            background: #dc3545;
        }}
        .section-title {{
            font-size: 0.85rem;
            color: #999;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 24px 0 12px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid #eee;
        }}
        .footer {{
            text-align: center;
            margin-top: 24px;
            color: #999;
            font-size: 0.85rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Cilium Istio Lab</h1>
        <p class="subtitle">Flask Application with Network Policy Demo</p>

        <div class="card">
            <div class="card-header">
                <div class="card-icon app">&#x1F680;</div>
                <span class="card-title">Application</span>
            </div>
            <div class="card-content">
                Hello from Flask!
            </div>
        </div>

        <div class="section-title">Internal Services</div>

        <div class="card">
            <div class="card-header">
                <div class="card-icon db">&#x1F5C4;</div>
                <span class="card-title">PostgreSQL Database</span>
            </div>
            <div class="card-content">
                {db_message}
                <div class="status {db_status_class}">
                    <span class="status-dot"></span>
                    {db_status}
                </div>
            </div>
        </div>

        <div class="section-title">External Services (Egress)</div>

        <div class="card">
            <div class="card-header">
                <div class="card-icon github">&#x1F419;</div>
                <span class="card-title">GitHub API</span>
            </div>
            <div class="card-content">
                api.github.com
                <div class="status {github_status_class}">
                    <span class="status-dot"></span>
                    {github_status}
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <div class="card-icon cloudflare">&#x2601;</div>
                <span class="card-title">Cloudflare API</span>
            </div>
            <div class="card-content">
                api.cloudflare.com
                <div class="status {cloudflare_status_class}">
                    <span class="status-dot"></span>
                    {cloudflare_status}
                </div>
            </div>
        </div>

        <div class="footer">
            Running on port 8000
        </div>
    </div>
</body>
</html>"""
    return html


@app.route("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
