import sys
try:
    from gevent import monkey
    monkey.patch_all()
    print("[TEST] gevent monkey patch successful")
    has_gevent = True
except ImportError:
    print("[TEST] gevent import failed")
    has_gevent = False

import os
from flask import Flask, jsonify
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'

if has_gevent:
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
else:
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

@app.route('/')
def home():
    return jsonify({"status": "ok", "async_mode": socketio.async_mode})

if __name__ == '__main__':
    ssl_cert = '../cert.pem'
    ssl_key = '../key.pem'
    if not os.path.exists(ssl_cert):
        ssl_cert = 'cert.pem'
        ssl_key = 'key.pem'
        
    if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
        print("[TEST] Starting with HTTPS...")
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=ssl_cert, keyfile=ssl_key)
        socketio.run(app, host='127.0.0.1', port=5001, ssl_context=context)
    else:
        print("[TEST] Starting with HTTP...")
        socketio.run(app, host='127.0.0.1', port=5001)
