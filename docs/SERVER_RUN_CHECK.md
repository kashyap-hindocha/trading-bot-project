# How the app runs on the Oracle server (and how to confirm)

## How it runs (from your repo)

| Component | How it runs |
|-----------|-------------|
| **Flask API** | **systemd** service `server.service` → `python server/app.py` |
| **Working directory** | `/home/ubuntu/trading-bot` |
| **Command** | `/home/ubuntu/trading-bot/venv/bin/python server/app.py` |
| **User** | `ubuntu` |
| **Reverse proxy** | **nginx** → proxies `/api/` to `http://127.0.0.1:5000` |

So the app is **not** run with gunicorn; it is run with **`python server/app.py`**.  
That means `if __name__ == "__main__"` runs and the process uses **SocketIO** and the live chart relay. The 502 fix (no SocketIO at module level) still applies: the Flask app is only wrapped when that `__main__` block runs, so the process starts correctly.

---

## Steps to run on the server (to confirm)

SSH into the Oracle server, then run these and (optionally) send the outputs.

### 1. How the server process is started

```bash
# Check how the Flask server service is configured
cat /home/ubuntu/trading-bot/server.service
# or if it's installed system-wide:
systemctl cat server.service 2>/dev/null || true
```

Expected: `ExecStart=.../python server/app.py` (or similar).

### 2. Is the server service running?

```bash
# If using user systemd (e.g. deploy.sh / GitHub Actions)
systemctl --user status server.service

# If using system-wide systemd (e.g. server.service in repo with WantedBy=multi-user.target)
sudo systemctl status server.service
```

Note whether it says **active (running)** or not.

### 3. Which process is listening on port 5000?

```bash
sudo ss -tlnp | grep 5000
# or
sudo lsof -i :5000
```

You should see a **python** process (your Flask app). That confirms the app is running and bound to 5000.

### 4. Quick API check (on the server)

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/api/status
```

- **200** → API is responding (no 502 from the app itself).
- **502** or connection errors → problem is on the server (app crash, not listening, or nginx misconfiguration).

### 5. (Optional) Nginx and Socket.IO

If you want the **live chart** (Socket.IO) to work through nginx, nginx must forward `/socket.io/` to the same backend. Your current `nginx.conf` only has `location /api/`. If you add a block for Socket.IO, the backend is still the same: `http://127.0.0.1:5000` (see `server.service` and steps above). No code change is required for that; only nginx config.

---

## Summary

- **Run method:** systemd → `python server/app.py` (no gunicorn).
- **Current code:** Safe for this setup; 502 fix keeps the app runnable when started this way.
- After you run the steps above, you can share the outputs (or just “200 from curl” / “service active”) and we can confirm everything or suggest the next change (e.g. nginx for `/socket.io/`).
