#!/usr/bin/env python3
"""
GoYose Server - SQLite-backed server for the 囲碁ヨセ研究 tool.
Uses only Python standard library (no external packages required).

Usage:
    python3 server.py [port]

Then open http://localhost:5000/ in your browser.
"""
import http.server
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / 'goyose.db'


# ── Database ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trees (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            tree_id    INTEGER NOT NULL UNIQUE,
            title      TEXT NOT NULL DEFAULT 'Untitled',
            data       TEXT NOT NULL DEFAULT '{"nodes":[],"nextNodeId":1,"panX":0,"panY":0,"zoom":1}',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def db_get_state():
    conn = get_db()
    trees_rows = conn.execute(
        'SELECT tree_id, title, data FROM trees ORDER BY sort_order, tree_id'
    ).fetchall()
    meta_rows = conn.execute('SELECT key, value FROM meta').fetchall()
    conn.close()

    meta = {row['key']: row['value'] for row in meta_rows}
    trees = [
        {
            'id': row['tree_id'],
            'title': row['title'],
            'data': json.loads(row['data']),
        }
        for row in trees_rows
    ]

    next_tree_id = int(meta.get('nextTreeId', '1'))
    if 'activeTreeId' in meta and trees:
        active_tree_id = int(meta['activeTreeId'])
    elif trees:
        active_tree_id = trees[0]['id']
    else:
        active_tree_id = None

    return {
        'version': 1,
        'nextTreeId': next_tree_id,
        'trees': trees,
        'activeTreeId': active_tree_id,
    }


def db_put_state(payload):
    trees = payload.get('trees', [])
    next_tree_id = payload.get('nextTreeId', 1)
    active_tree_id = payload.get('activeTreeId')

    conn = get_db()
    existing_ids = {
        row['tree_id']
        for row in conn.execute('SELECT tree_id FROM trees').fetchall()
    }
    new_ids = {t['id'] for t in trees}

    for old_id in existing_ids - new_ids:
        conn.execute('DELETE FROM trees WHERE tree_id = ?', (old_id,))

    for i, tree in enumerate(trees):
        conn.execute(
            '''
            INSERT INTO trees (tree_id, title, data, sort_order, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tree_id) DO UPDATE SET
                title      = excluded.title,
                data       = excluded.data,
                sort_order = excluded.sort_order,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (
                tree['id'],
                tree.get('title', 'Untitled'),
                json.dumps(tree.get('data', {})),
                i,
            ),
        )

    conn.execute(
        'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
        ('nextTreeId', str(next_tree_id)),
    )
    if active_tree_id is not None:
        conn.execute(
            'INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)',
            ('activeTreeId', str(active_tree_id)),
        )

    conn.commit()
    conn.close()


# ── HTTP Handler ─────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args)

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self.send_file(BASE_DIR / 'server.html', 'text/html; charset=utf-8')
        elif self.path == '/api/state':
            self.send_json(200, db_get_state())
        else:
            self.send_error(404)

    def do_PUT(self):
        if self.path == '/api/state':
            payload = self.read_body_json()
            if payload is None:
                self.send_json(400, {'error': 'invalid JSON'})
                return
            db_put_state(payload)
            self.send_json(200, {'ok': True})
        else:
            self.send_error(404)

    # Allow cross-origin requests from file:// during development
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    server = http.server.HTTPServer(('0.0.0.0', port), Handler)
    print(f'GoYose server: http://localhost:{port}/')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
