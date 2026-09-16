"""Minimal fal queue client (plain HTTP, no SDK). API key from, in order: FAL_KEY env, ~/.fal/key, or the
`key = "..."` line of ~/.fal/config.toml. The key is never printed."""
import json, os, sys, time, urllib.request, urllib.error

def _key():
    k = os.environ.get("FAL_KEY")
    if not k:
        p = os.path.expanduser("~/.fal/key")
        if os.path.exists(p): k = open(p).read().strip()
    if not k:
        p = os.path.expanduser("~/.fal/config.toml")
        if os.path.exists(p):
            import re
            m = re.search(r'^\s*key\s*=\s*"([^"]+)"', open(p).read(), re.M)
            if m: k = m.group(1)
    if not k: raise SystemExit("No fal API key. Set FAL_KEY, or put the key in ~/.fal/key (create one at https://fal.ai/dashboard/keys).")
    return k

def _req(url, data=None, method=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Authorization": f"Key {_key()}", "Content-Type": "application/json"},
                                 method=method or ("POST" if data is not None else "GET"))
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < 5: time.sleep(3*(attempt+1)); continue
            raise RuntimeError(f"HTTP {e.code} {url}: {body}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 5: time.sleep(3*(attempt+1)); continue
            raise

def submit(endpoint, payload):
    r = _req(f"https://queue.fal.run/{endpoint}", payload)
    return {"request_id": r["request_id"], "status_url": r["status_url"], "response_url": r["response_url"]}

def wait(job, poll=6, budget=900, label=""):
    t0 = time.time(); last = None
    while time.time() - t0 < budget:
        s = _req(job["status_url"] + "?logs=0")
        st = s.get("status")
        if st != last: print(f"  [{label}] {st} @ {time.time()-t0:5.0f}s", flush=True); last = st
        if st == "COMPLETED": return _req(job["response_url"])
        if st in ("FAILED", "CANCELLED"): raise RuntimeError(f"{label}: {st} {s}")
        time.sleep(poll)
    raise TimeoutError(f"{label}: no result in {budget}s")

def download(url, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"tiny-voxel-batch"}), timeout=300) as r, open(path,"wb") as f:
                while True:
                    b = r.read(1<<20)
                    if not b: break
                    f.write(b)
            return path
        except Exception:
            if attempt == 3: raise
            time.sleep(2)

SEEDREAM = "bytedance/seedream/v5/pro/text-to-image"
HUNYUAN  = "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d"

def concept_payload(prompt, n=4):
    return {"prompt": prompt, "image_size": {"width": 1024, "height": 1024}, "num_images": n, "output_format": "png"}

def mesh_payload(image_url, face_count=100000):
    return {"input_image_url": image_url, "generate_type": "Normal", "enable_pbr": True, "face_count": face_count}
