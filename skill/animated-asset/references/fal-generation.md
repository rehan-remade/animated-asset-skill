# fal generation reference (stages 1–2)

## Access

Preferred: the `fal-ai` MCP server (user-scope, `https://mcp.fal.ai/mcp`)
— tools `search_models`, `get_model_schema`, `run_model`, `submit_job`,
`check_job`, `upload_file`, `get_pricing`.

HTTP fallback (MCP not connected): `tools/pipeline/fal_client.py` wraps the queue API.
The key comes from `FAL_KEY`, `~/.fal/key`, or the `key = "..."` line of `~/.fal/config.toml`.
Never print it. Auth header: `Authorization: Key <key>`.

```bash
# submit
curl -s -X POST "https://queue.fal.run/<endpoint>" -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" -d '<json input>'
# poll + fetch: use the status_url / response_url from the submit response VERBATIM —
# they drop endpoint sub-paths (e.g. bytedance/seedream/requests/<id>); hand-built URLs 404.
```

Or just use the CLI: `python tools/pipeline/concept.py <Name> --idea "..." --len-m 0.9`.

Schema discovery for any endpoint:
`https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<endpoint>` (no auth).

## Text-to-image — `bytedance/seedream/v5/pro/text-to-image`

Input: `prompt` (required); `image_size` `{"width":1024,"height":1024}`;
`num_images` 4 for a candidate round (max 6); `output_format` "png".
Output: `images[]`, one `.url` (fal CDN) per candidate — keep the URLs,
stage 2 consumes the picked one directly. Wall time ~2 min for one image
— poll every 5 s, budget 6 min for a 4-image round.
Alternates: `openai/gpt-image-2`, `fal-ai/nano-banana-2` (check schema first).

### Prompt template (proven)

> A 3D render of a voxel art game asset: a {adjective} {creature}
> {pose, e.g. "standing"}, viewed from a side three-quarter angle. Built
> from large chunky visible cubes on a strict grid, roughly {L} cubes long
> and {H} cubes tall, MagicaVoxel style, crisp axis-aligned blocky edges,
> no smooth curves. {2–3 sentences of anatomy as BLOCKY shapes: "extremely
> short thick legs one cube tall", "oversized head", "fluff rendered as
> solid stepped cube layers, not strands"; suppress thin parts: "no tail"
> or "tail a thick plume slab lying flat against its side"}. Flat colors
> in clean regions: {color regions}. Centered, entire model in frame,
> plain solid light-gray background, soft even studio lighting, no
> shadows on background.

Rules of thumb: state cube counts matching the intended in-game size
(voxels = meters x 10) — they control style; the voxelizer enforces exact
dims. Thin appendages (tails, whiskers, thin antler tines) must be
thickened, slabbed against the body, or omitted — they shred at low voxel
resolutions. Legs must be separated from each other and the ground plane.

## Image-to-3D — `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d`

Input: `input_image_url` (required; 128–5000 px, <8 MB — pass the stage-1
CDN URL directly); `generate_type` "Normal" (textured); `enable_pbr` true;
`face_count` 40000–1500000 (default 500k ≈ 45 MB GLB; 100k is plenty);
optional multi-view conditioning: `back_image_url`, `left/right/top/...`.
Output: `model_glb.url`, `model_urls.{glb,obj,mtl,texture}`, `thumbnail.url`.
Wall time ~2.5 min — poll every 10–15 s, budget 10 min.

Known behavior: unseen views are hallucinated (a rear-facing "nose" blob
appeared on a corgi generated from a single 3/4 view). Usually 1–2 stray
voxels after voxelization — ignore, or supply `back_image_url` for a clean
rear.

## Cost sanity

Both models bill per run (concept ~cents, Hunyuan pro ~tens of cents).
`get_pricing` via MCP if the user asks; don't loop generations without a
passing QA gate in between.
