// voxelizer — converts a textured mesh (OBJ or GLB) into a MagicaVoxel .vox
// model, replacing the manual drububu.com web-voxelizer step of the asset
// pipeline (text-to-image -> image-to-3D -> voxelize -> rig/animate).
//
// Behavior matches the drububu outputs the pipeline was built around:
//   - the mesh AABB is centered in a uniform grid; the cell size comes from
//     a target voxel count along the longest axis (voxels = meters * 10 at
//     the project scale, chosen by the caller),
//   - a voxel is set when any triangle overlaps its cell (surface shell),
//   - voxels fully hidden from outside air are dropped by default (hollow,
//     like drububu's "skip enclosed voxels"); --fill keeps them and also
//     fills the enclosed cavity solid,
//   - colors are sampled from the albedo texture and quantized to a
//     255-color palette sorted dark-to-light.
//
// Axes: input meshes are Y-up (glTF and the Hunyuan OBJ exports); .vox is
// Z-up. Mapped as vox(x,y,z) = (grid.x, depth-1-grid.z, grid.y), a proper
// rotation, so a mesh facing +Z faces -Y in vox space — the orientation the
// rigging scripts in tools/creatures expect.

#define TINYOBJLOADER_IMPLEMENTATION
#include "third_party/tiny_obj_loader.h"
#define CGLTF_IMPLEMENTATION
#include "third_party/cgltf.h"
#define STB_IMAGE_IMPLEMENTATION
#include "third_party/stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "third_party/stb_image_write.h"

#include <algorithm>
#include <array>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace {

struct Vec3 {
    float x = 0, y = 0, z = 0;
    Vec3() = default;
    Vec3(float a, float b, float c) : x(a), y(b), z(c) {}
    Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
    Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }
    float operator[](int i) const { return i == 0 ? x : (i == 1 ? y : z); }
    float& operator[](int i) { return i == 0 ? x : (i == 1 ? y : z); }
};
float dot(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(const Vec3& a, const Vec3& b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}

struct Image {
    int w = 0, h = 0;
    std::vector<uint8_t> rgba;   // w*h*4
    bool flipV = false;          // OBJ UVs are bottom-left origin; stb rows are top-first
};

struct Tri {
    Vec3 p[3];
    float u[3] = {0, 0, 0}, v[3] = {0, 0, 0};
    int tex = -1;                      // index into Mesh::textures, -1 = none
    uint8_t flat[3] = {200, 200, 200}; // fallback color (base color factor / vertex color)
};

struct Mesh {
    std::vector<Tri> tris;
    std::vector<Image> textures;
};

// ---------------------------------------------------------------------------
// loading

bool loadImageFile(const std::string& path, Image& out) {
    int n = 0;
    uint8_t* data = stbi_load(path.c_str(), &out.w, &out.h, &n, 4);
    if (!data) return false;
    out.rgba.assign(data, data + size_t(out.w) * out.h * 4);
    stbi_image_free(data);
    return true;
}

bool loadImageMemory(const uint8_t* bytes, size_t len, Image& out) {
    int n = 0;
    uint8_t* data = stbi_load_from_memory(bytes, int(len), &out.w, &out.h, &n, 4);
    if (!data) return false;
    out.rgba.assign(data, data + size_t(out.w) * out.h * 4);
    stbi_image_free(data);
    return true;
}

std::string dirOf(const std::string& path) {
    size_t s = path.find_last_of("/\\");
    return s == std::string::npos ? std::string(".") : path.substr(0, s);
}

bool loadObj(const std::string& path, const std::string& texOverride, Mesh& mesh) {
    tinyobj::attrib_t attrib;
    std::vector<tinyobj::shape_t> shapes;
    std::vector<tinyobj::material_t> materials;
    std::string warn, err;
    std::string base = dirOf(path) + "/";
    if (!tinyobj::LoadObj(&attrib, &shapes, &materials, &warn, &err, path.c_str(), base.c_str())) {
        fprintf(stderr, "OBJ load failed: %s\n", err.c_str());
        return false;
    }
    if (!warn.empty()) fprintf(stderr, "OBJ warning: %s\n", warn.c_str());

    // material textures; fall back to --texture for every material (the
    // Hunyuan OBJ exports reference a material.mtl that is often missing)
    std::vector<int> matTex(materials.size() ? materials.size() : 1, -1);
    auto addTexture = [&](const std::string& p) -> int {
        Image img;
        if (!loadImageFile(p, img)) return -1;
        img.flipV = true; // OBJ convention
        mesh.textures.push_back(std::move(img));
        return int(mesh.textures.size()) - 1;
    };
    for (size_t m = 0; m < materials.size(); ++m) {
        if (!materials[m].diffuse_texname.empty())
            matTex[m] = addTexture(base + materials[m].diffuse_texname);
    }
    int overrideTex = -1;
    if (!texOverride.empty()) {
        overrideTex = addTexture(texOverride);
        if (overrideTex < 0) {
            fprintf(stderr, "failed to load texture %s\n", texOverride.c_str());
            return false;
        }
    }

    for (const auto& shape : shapes) {
        size_t off = 0;
        for (size_t f = 0; f < shape.mesh.num_face_vertices.size(); ++f) {
            int fv = shape.mesh.num_face_vertices[f];
            int mat = f < shape.mesh.material_ids.size() ? shape.mesh.material_ids[f] : -1;
            int tex = overrideTex >= 0 ? overrideTex
                      : (mat >= 0 && mat < int(matTex.size()) ? matTex[mat] : -1);
            // triangle fan for polygons (Hunyuan exports are all triangles)
            for (int t = 2; t < fv; ++t) {
                Tri tri;
                int idxs[3] = {0, t - 1, t};
                bool hasUV = true;
                for (int k = 0; k < 3; ++k) {
                    tinyobj::index_t idx = shape.mesh.indices[off + idxs[k]];
                    tri.p[k] = {attrib.vertices[3 * idx.vertex_index + 0],
                                attrib.vertices[3 * idx.vertex_index + 1],
                                attrib.vertices[3 * idx.vertex_index + 2]};
                    if (idx.texcoord_index >= 0) {
                        tri.u[k] = attrib.texcoords[2 * idx.texcoord_index + 0];
                        tri.v[k] = attrib.texcoords[2 * idx.texcoord_index + 1];
                    } else {
                        hasUV = false;
                    }
                }
                tri.tex = hasUV ? tex : -1; // a texture without UVs would sample one texel
                if (mat >= 0 && mat < int(materials.size())) {
                    for (int c = 0; c < 3; ++c)
                        tri.flat[c] = uint8_t(std::min(1.f, materials[mat].diffuse[c]) * 255.f + .5f);
                }
                mesh.tris.push_back(tri);
            }
            off += fv;
        }
    }
    return true;
}

bool loadGlb(const std::string& path, Mesh& mesh) {
    cgltf_options options = {};
    cgltf_data* data = nullptr;
    if (cgltf_parse_file(&options, path.c_str(), &data) != cgltf_result_success) {
        fprintf(stderr, "GLB parse failed: %s\n", path.c_str());
        return false;
    }
    if (cgltf_load_buffers(&options, data, path.c_str()) != cgltf_result_success) {
        fprintf(stderr, "GLB buffer load failed\n");
        cgltf_free(data);
        return false;
    }

    std::unordered_map<const cgltf_image*, int> imageCache;
    auto textureIndex = [&](const cgltf_texture* t) -> int {
        if (!t || !t->image) return -1;
        auto it = imageCache.find(t->image);
        if (it != imageCache.end()) return it->second;
        Image img;
        bool ok = false;
        const cgltf_image* im = t->image;
        if (im->buffer_view && im->buffer_view->buffer->data) {
            const uint8_t* bytes = (const uint8_t*)im->buffer_view->buffer->data + im->buffer_view->offset;
            ok = loadImageMemory(bytes, im->buffer_view->size, img);
        } else if (im->uri && strncmp(im->uri, "data:", 5) != 0) {
            ok = loadImageFile(dirOf(path) + "/" + im->uri, img);
        }
        int idx = -1;
        if (ok) {
            mesh.textures.push_back(std::move(img)); // glTF UVs are top-left origin: no flip
            idx = int(mesh.textures.size()) - 1;
        } else {
            fprintf(stderr, "warning: could not decode a glTF texture image%s — "
                            "affected triangles fall back to the material color\n",
                    (im->uri && strncmp(im->uri, "data:", 5) == 0) ? " (data: URIs unsupported)" : "");
        }
        imageCache[t->image] = idx;
        return idx;
    };

    // linear (glTF factors / vertex colors) -> sRGB bytes, matching texture output
    auto linearToSrgb = [](float c) -> uint8_t {
        c = std::min(1.f, std::max(0.f, c));
        float s = c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.f / 2.4f) - 0.055f;
        return uint8_t(s * 255.f + .5f);
    };

    size_t skippedPrims = 0;
    for (size_t ni = 0; ni < data->nodes_count; ++ni) {
        const cgltf_node* node = &data->nodes[ni];
        if (!node->mesh) continue;
        float m[16];
        cgltf_node_transform_world(node, m);
        auto xform = [&](const Vec3& p) -> Vec3 {
            return {m[0] * p.x + m[4] * p.y + m[8] * p.z + m[12],
                    m[1] * p.x + m[5] * p.y + m[9] * p.z + m[13],
                    m[2] * p.x + m[6] * p.y + m[10] * p.z + m[14]};
        };
        for (size_t pi = 0; pi < node->mesh->primitives_count; ++pi) {
            const cgltf_primitive* prim = &node->mesh->primitives[pi];
            if (prim->type != cgltf_primitive_type_triangles) { skippedPrims++; continue; }
            // the material declares which UV set its base color texture uses
            int uvSet = prim->material
                ? int(prim->material->pbr_metallic_roughness.base_color_texture.texcoord) : 0;
            const cgltf_accessor* pos = nullptr;
            const cgltf_accessor* uv = nullptr;
            const cgltf_accessor* uv0 = nullptr;
            const cgltf_accessor* col = nullptr;
            for (size_t a = 0; a < prim->attributes_count; ++a) {
                if (prim->attributes[a].type == cgltf_attribute_type_position && !pos)
                    pos = prim->attributes[a].data;
                if (prim->attributes[a].type == cgltf_attribute_type_texcoord) {
                    if (prim->attributes[a].index == uvSet) uv = prim->attributes[a].data;
                    if (prim->attributes[a].index == 0) uv0 = prim->attributes[a].data;
                }
                if (prim->attributes[a].type == cgltf_attribute_type_color && prim->attributes[a].index == 0)
                    col = prim->attributes[a].data;
            }
            if (!uv) uv = uv0; // declared set missing from the primitive: fall back
            if (!pos) continue;
            int tex = -1;
            uint8_t flat[3] = {200, 200, 200};
            if (prim->material) {
                const auto& pbr = prim->material->pbr_metallic_roughness;
                tex = textureIndex(pbr.base_color_texture.texture);
                for (int c = 0; c < 3; ++c)
                    flat[c] = linearToSrgb(pbr.base_color_factor[c]);
            }
            if (!uv) tex = -1; // a texture without UVs would sample one texel
            size_t count = prim->indices ? prim->indices->count : pos->count;
            auto vertexAt = [&](size_t k) {
                return prim->indices ? cgltf_accessor_read_index(prim->indices, k) : k;
            };
            for (size_t k = 0; k + 2 < count; k += 3) {
                Tri tri;
                for (int j = 0; j < 3; ++j) {
                    size_t vi = vertexAt(k + j);
                    float p3[3] = {0, 0, 0};
                    cgltf_accessor_read_float(pos, vi, p3, 3);
                    tri.p[j] = xform({p3[0], p3[1], p3[2]});
                    if (uv) {
                        float t2[2] = {0, 0};
                        cgltf_accessor_read_float(uv, vi, t2, 2);
                        tri.u[j] = t2[0];
                        tri.v[j] = t2[1];
                    }
                    if (col && !uv) {
                        float c4[4] = {1, 1, 1, 1};
                        cgltf_accessor_read_float(col, vi, c4, 4);
                        if (j == 0)
                            for (int c = 0; c < 3; ++c)
                                flat[c] = linearToSrgb(c4[c]);
                    }
                }
                tri.tex = tex;
                memcpy(tri.flat, flat, 3);
                mesh.tris.push_back(tri);
            }
        }
    }
    if (skippedPrims)
        fprintf(stderr, "warning: skipped %zu non-triangle glTF primitives\n", skippedPrims);
    cgltf_free(data);
    return true;
}

// ---------------------------------------------------------------------------
// geometry: Akenine-Moller triangle/AABB SAT and closest point on triangle

bool planeBoxOverlap(const Vec3& n, const Vec3& v, const Vec3& half) {
    Vec3 vmin, vmax;
    for (int i = 0; i < 3; ++i) {
        if (n[i] > 0) { vmin[i] = -half[i] - v[i]; vmax[i] = half[i] - v[i]; }
        else          { vmin[i] =  half[i] - v[i]; vmax[i] = -half[i] - v[i]; }
    }
    if (dot(n, vmin) > 0) return false;
    return dot(n, vmax) >= 0;
}

bool triBoxOverlap(const Vec3& center, const Vec3& half, const Vec3& a, const Vec3& b, const Vec3& c) {
    Vec3 v0 = a - center, v1 = b - center, v2 = c - center;
    Vec3 e0 = v1 - v0, e1 = v2 - v1, e2 = v0 - v2;

    auto axisTest = [&](float ea, float eb, int i, int j, const Vec3& va, const Vec3& vb) {
        float p0 = ea * va[i] - eb * va[j];
        float p1 = ea * vb[i] - eb * vb[j];
        float mn = std::min(p0, p1), mx = std::max(p0, p1);
        float rad = std::fabs(ea) * half[i] + std::fabs(eb) * half[j];
        return !(mn > rad || mx < -rad);
    };
    // 9 cross-product axes
    if (!axisTest(e0.z, e0.y, 1, 2, v0, v2)) return false;
    if (!axisTest(-e0.z, -e0.x, 0, 2, v0, v2)) return false; // note: use (z,x) pair sign-folded below
    if (!axisTest(e0.y, e0.x, 0, 1, v1, v2)) return false;
    if (!axisTest(e1.z, e1.y, 1, 2, v0, v2)) return false;
    if (!axisTest(-e1.z, -e1.x, 0, 2, v0, v2)) return false;
    if (!axisTest(e1.y, e1.x, 0, 1, v0, v1)) return false;
    if (!axisTest(e2.z, e2.y, 1, 2, v0, v1)) return false;
    if (!axisTest(-e2.z, -e2.x, 0, 2, v0, v1)) return false;
    if (!axisTest(e2.y, e2.x, 0, 1, v1, v2)) return false;

    // AABB overlap
    for (int i = 0; i < 3; ++i) {
        float mn = std::min({v0[i], v1[i], v2[i]});
        float mx = std::max({v0[i], v1[i], v2[i]});
        if (mn > half[i] || mx < -half[i]) return false;
    }
    // triangle plane
    return planeBoxOverlap(cross(e0, e1), v0, half);
}

// Ericson, Real-Time Collision Detection 5.1.5
Vec3 closestPointOnTri(const Vec3& p, const Vec3& a, const Vec3& b, const Vec3& c, float bary[3]) {
    Vec3 ab = b - a, ac = c - a, ap = p - a;
    float d1 = dot(ab, ap), d2 = dot(ac, ap);
    if (d1 <= 0 && d2 <= 0) { bary[0] = 1; bary[1] = 0; bary[2] = 0; return a; }
    Vec3 bp = p - b;
    float d3 = dot(ab, bp), d4 = dot(ac, bp);
    if (d3 >= 0 && d4 <= d3) { bary[0] = 0; bary[1] = 1; bary[2] = 0; return b; }
    float vc = d1 * d4 - d3 * d2;
    if (vc <= 0 && d1 >= 0 && d3 <= 0) {
        float denomAB = d1 - d3; // == |ab|^2; zero only for a degenerate a==b edge
        float t = denomAB > 0.f ? d1 / denomAB : 0.f;
        bary[0] = 1 - t; bary[1] = t; bary[2] = 0;
        return a + ab * t;
    }
    Vec3 cp = p - c;
    float d5 = dot(ab, cp), d6 = dot(ac, cp);
    if (d6 >= 0 && d5 <= d6) { bary[0] = 0; bary[1] = 0; bary[2] = 1; return c; }
    float vb = d5 * d2 - d1 * d6;
    if (vb <= 0 && d2 >= 0 && d6 <= 0) {
        float t = d2 / (d2 - d6);
        bary[0] = 1 - t; bary[1] = 0; bary[2] = t;
        return a + ac * t;
    }
    float va = d3 * d6 - d5 * d4;
    if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
        float t = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        bary[0] = 0; bary[1] = 1 - t; bary[2] = t;
        return b + (c - b) * t;
    }
    float denom = 1.f / (va + vb + vc);
    float v = vb * denom, w = vc * denom;
    bary[0] = 1 - v - w; bary[1] = v; bary[2] = w;
    return a + ab * v + ac * w;
}

// ---------------------------------------------------------------------------
// palette quantization (median cut to <= 255 colors)

struct RGB {
    uint8_t r, g, b;
    bool operator<(const RGB& o) const {
        return std::tie(r, g, b) < std::tie(o.r, o.g, o.b);
    }
};

std::vector<RGB> medianCut(std::vector<RGB> colors, size_t maxColors) {
    struct Box { std::vector<RGB> c; };
    std::vector<Box> boxes{Box{std::move(colors)}};
    while (boxes.size() < maxColors) {
        // split the box with the largest channel range
        int best = -1, bestCh = 0, bestRange = 0;
        for (size_t i = 0; i < boxes.size(); ++i) {
            if (boxes[i].c.size() < 2) continue;
            int mn[3] = {255, 255, 255}, mx[3] = {0, 0, 0};
            for (const RGB& c : boxes[i].c) {
                int v[3] = {c.r, c.g, c.b};
                for (int ch = 0; ch < 3; ++ch) {
                    mn[ch] = std::min(mn[ch], v[ch]);
                    mx[ch] = std::max(mx[ch], v[ch]);
                }
            }
            for (int ch = 0; ch < 3; ++ch)
                if (mx[ch] - mn[ch] > bestRange) { bestRange = mx[ch] - mn[ch]; best = int(i); bestCh = ch; }
        }
        if (best < 0 || bestRange == 0) break;
        Box& bx = boxes[best];
        int ch = bestCh;
        std::sort(bx.c.begin(), bx.c.end(), [ch](const RGB& a, const RGB& b) {
            return (ch == 0 ? a.r : ch == 1 ? a.g : a.b) < (ch == 0 ? b.r : ch == 1 ? b.g : b.b);
        });
        Box hi;
        hi.c.assign(bx.c.begin() + bx.c.size() / 2, bx.c.end());
        bx.c.resize(bx.c.size() / 2);
        boxes.push_back(std::move(hi));
    }
    std::vector<RGB> pal;
    for (const Box& bx : boxes) {
        if (bx.c.empty()) continue;
        long r = 0, g = 0, b = 0;
        for (const RGB& c : bx.c) { r += c.r; g += c.g; b += c.b; }
        size_t n = bx.c.size();
        pal.push_back({uint8_t(r / n), uint8_t(g / n), uint8_t(b / n)});
    }
    return pal;
}

// ---------------------------------------------------------------------------

struct Args {
    std::string input, out, texture, previewDir;
    int longAxis = 32;      // target voxels along the driving axis
    int axis = -1;          // -1 = longest extent, else 0/1/2 (x/y-up/z)
    int dims[3] = {0, 0, 0}; // explicit LxHxD override (x, up, depth)
    float cell = 0;         // explicit cell size in mesh units
    int yaw = 0;            // rotate mesh about up axis before voxelizing
    bool anchorMin = true;  // bbox-min grid anchor (drububu-verified; 0.97 IoU vs web tool)
    bool fill = false;      // solid interior instead of drububu-style hollow shell
    bool noDepthFlip = false;
    bool ascii = false;
};

void usage() {
    fprintf(stderr,
        "usage: voxelizer <input.obj|input.glb> --out <file.vox> [options]\n"
        "  --long-axis N     voxels along the longest mesh axis (default 32)\n"
        "  --axis x|y|z      pick the driving axis explicitly (y = up)\n"
        "  --dims LxHxD      exact grid dims (length x height x depth), overrides --long-axis\n"
        "  --cell M          explicit cell size in mesh units, overrides both\n"
        "  --texture P.png   albedo texture (OBJ inputs with a missing .mtl)\n"
        "  --yaw 0|90|180|270  rotate about the up axis first (fix facing; front must end at -Y vox)\n"
        "  --anchor min|center grid placement against the mesh AABB (default min)\n"
        "  --fill            solid interior (default: hollow shell like drububu)\n"
        "  --no-depth-flip   mirror depth mapping (compat experiments only)\n"
        "  --previews DIR    write <name>_vox_front/_side/_top.png QA renders\n"
        "  --ascii           print per-height ASCII slices (rig rule authoring)\n");
}

} // namespace

int main(int argc, char** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> const char* {
            if (i + 1 >= argc) { usage(); exit(2); }
            return argv[++i];
        };
        if (a == "--out") args.out = next();
        else if (a == "--long-axis") {
            args.longAxis = atoi(next());
            if (args.longAxis < 1 || args.longAxis > 256) { fprintf(stderr, "--long-axis must be 1..256\n"); return 2; }
        }
        else if (a == "--axis") {
            std::string v = next();
            if (v != "x" && v != "y" && v != "z") { fprintf(stderr, "--axis must be x, y or z\n"); return 2; }
            args.axis = v[0] == 'x' ? 0 : v[0] == 'y' ? 1 : 2;
        }
        else if (a == "--dims") {
            if (sscanf(next(), "%dx%dx%d", &args.dims[0], &args.dims[1], &args.dims[2]) != 3 ||
                args.dims[0] < 1 || args.dims[1] < 1 || args.dims[2] < 1) {
                fprintf(stderr, "--dims expects LxHxD with positive integers\n");
                return 2;
            }
        }
        else if (a == "--cell") {
            args.cell = float(atof(next()));
            if (!(args.cell > 0)) { fprintf(stderr, "--cell must be a positive size\n"); return 2; }
        }
        else if (a == "--texture") args.texture = next();
        else if (a == "--yaw") args.yaw = atoi(next());
        else if (a == "--anchor") {
            std::string v = next();
            if (v != "min" && v != "center") { fprintf(stderr, "--anchor must be min or center\n"); return 2; }
            args.anchorMin = v == "min";
        }
        else if (a == "--fill") args.fill = true;
        else if (a == "--no-depth-flip") args.noDepthFlip = true;
        else if (a == "--previews") args.previewDir = next();
        else if (a == "--ascii") args.ascii = true;
        else if (a[0] != '-') args.input = a;
        else { usage(); return 2; }
    }
    if (args.input.empty() || args.out.empty()) { usage(); return 2; }

    Mesh mesh;
    std::string ext;
    {
        size_t dot = args.input.find_last_of('.');
        if (dot != std::string::npos) ext = args.input.substr(dot + 1);
        for (char& c : ext) c = char(tolower((unsigned char)c));
    }
    bool isGlb = ext == "glb" || ext == "gltf";
    if (isGlb && !args.texture.empty())
        fprintf(stderr, "warning: --texture is ignored for glTF inputs (textures come from the file)\n");
    if (isGlb ? !loadGlb(args.input, mesh) : !loadObj(args.input, args.texture, mesh)) return 1;
    if (mesh.tris.empty()) { fprintf(stderr, "no triangles loaded\n"); return 1; }
    printf("loaded %zu triangles, %zu textures\n", mesh.tris.size(), mesh.textures.size());

    // yaw about the up axis (Y), around the mesh center
    if (args.yaw % 360 != 0) {
        Vec3 mn{1e30f, 1e30f, 1e30f}, mx{-1e30f, -1e30f, -1e30f};
        for (const Tri& t : mesh.tris)
            for (const Vec3& p : t.p)
                for (int i = 0; i < 3; ++i) { mn[i] = std::min(mn[i], p[i]); mx[i] = std::max(mx[i], p[i]); }
        Vec3 c = (mn + mx) * 0.5f;
        float rad = float(args.yaw) * 3.14159265f / 180.f;
        float cs = std::cos(rad), sn = std::sin(rad);
        for (Tri& t : mesh.tris)
            for (Vec3& p : t.p) {
                float dx = p.x - c.x, dz = p.z - c.z;
                p.x = c.x + dx * cs + dz * sn;
                p.z = c.z - dx * sn + dz * cs;
            }
    }

    // bounds and grid dims
    Vec3 mn{1e30f, 1e30f, 1e30f}, mx{-1e30f, -1e30f, -1e30f};
    for (const Tri& t : mesh.tris)
        for (const Vec3& p : t.p)
            for (int i = 0; i < 3; ++i) { mn[i] = std::min(mn[i], p[i]); mx[i] = std::max(mx[i], p[i]); }
    Vec3 extent = mx - mn;

    float cell = args.cell;
    int dims[3];
    if (args.dims[0] > 0) {
        dims[0] = args.dims[0]; dims[1] = args.dims[1]; dims[2] = args.dims[2];
        if (cell <= 0)
            cell = std::max({extent.x / dims[0], extent.y / dims[1], extent.z / dims[2]});
    } else {
        int drive = args.axis;
        if (drive < 0)
            drive = extent.x >= extent.y && extent.x >= extent.z ? 0 : (extent.y >= extent.z ? 1 : 2);
        if (cell <= 0) cell = extent[drive] / float(args.longAxis);
        for (int i = 0; i < 3; ++i)
            dims[i] = std::max(1, int(std::ceil(extent[i] / cell - 1e-5f)));
    }
    if (!(cell > 0) || !std::isfinite(cell)) {
        fprintf(stderr, "degenerate mesh extents %g x %g x %g — cannot derive a cell size\n",
                extent.x, extent.y, extent.z);
        return 1;
    }
    if (dims[0] > 256 || dims[1] > 256 || dims[2] > 256) {
        fprintf(stderr, "grid %dx%dx%d exceeds the .vox limit of 256 per axis\n", dims[0], dims[1], dims[2]);
        return 1;
    }
    // grid placement: mesh centered in the grid (default) or anchored at bbox min
    Vec3 origin;
    for (int i = 0; i < 3; ++i)
        origin[i] = args.anchorMin ? mn[i] : mn[i] - (dims[i] * cell - extent[i]) * 0.5f;

    printf("grid %dx%dx%d (x,up,depth), cell %.5f units\n", dims[0], dims[1], dims[2], cell);
    printf("world size at 1 voxel = 10 cm: %.2f x %.2f x %.2f m (L x H x D)\n",
           dims[0] * 0.1f, dims[1] * 0.1f, dims[2] * 0.1f);

    const int W = dims[0], H = dims[1], D = dims[2];
    const size_t cells = size_t(W) * H * D;
    auto cellIndex = [&](int x, int y, int z) { return (size_t(z) * H + y) * W + x; };

    std::vector<uint8_t> occ(cells, 0);
    struct Accum { double r = 0, g = 0, b = 0; uint32_t n = 0; };
    std::unordered_map<size_t, Accum> color;
    color.reserve(1 << 16);

    Vec3 half{cell * 0.5f, cell * 0.5f, cell * 0.5f};
    Vec3 halfEps = half * 1.0001f;
    for (const Tri& t : mesh.tris) {
        Vec3 tmn = t.p[0], tmx = t.p[0];
        for (int k = 1; k < 3; ++k)
            for (int i = 0; i < 3; ++i) {
                tmn[i] = std::min(tmn[i], t.p[k][i]);
                tmx[i] = std::max(tmx[i], t.p[k][i]);
            }
        int lo[3], hi[3];
        for (int i = 0; i < 3; ++i) {
            lo[i] = std::max(0, int(std::floor((tmn[i] - origin[i]) / cell)));
            hi[i] = std::min(dims[i] - 1, int(std::floor((tmx[i] - origin[i]) / cell)));
        }
        for (int z = lo[2]; z <= hi[2]; ++z)
            for (int y = lo[1]; y <= hi[1]; ++y)
                for (int x = lo[0]; x <= hi[0]; ++x) {
                    Vec3 center{origin.x + (x + 0.5f) * cell,
                                origin.y + (y + 0.5f) * cell,
                                origin.z + (z + 0.5f) * cell};
                    if (!triBoxOverlap(center, halfEps, t.p[0], t.p[1], t.p[2])) continue;
                    size_t ci = cellIndex(x, y, z);
                    occ[ci] = 1;
                    // sample the albedo at the point of the triangle nearest the cell center
                    float bary[3];
                    closestPointOnTri(center, t.p[0], t.p[1], t.p[2], bary);
                    uint8_t rgb[3] = {t.flat[0], t.flat[1], t.flat[2]};
                    if (t.tex >= 0) {
                        const Image& img = mesh.textures[t.tex];
                        float u = bary[0] * t.u[0] + bary[1] * t.u[1] + bary[2] * t.u[2];
                        float v = bary[0] * t.v[0] + bary[1] * t.v[1] + bary[2] * t.v[2];
                        // wrap only true out-of-range UVs; exact 1.0 must stay at
                        // the far edge (the min() below clamps it to the last texel)
                        if (u < 0.f || u > 1.f) u -= std::floor(u);
                        if (v < 0.f || v > 1.f) v -= std::floor(v);
                        if (img.flipV) v = 1.f - v;
                        int px = std::min(img.w - 1, int(u * img.w));
                        int py = std::min(img.h - 1, int(v * img.h));
                        const uint8_t* tex = &img.rgba[(size_t(py) * img.w + px) * 4];
                        if (tex[3] >= 128) { rgb[0] = tex[0]; rgb[1] = tex[1]; rgb[2] = tex[2]; }
                        else continue; // transparent texel: occupancy without color vote
                    }
                    Accum& acc = color[ci];
                    acc.r += rgb[0]; acc.g += rgb[1]; acc.b += rgb[2]; acc.n += 1;
                }
    }

    size_t shellCount = 0;
    for (uint8_t o : occ) shellCount += o;
    printf("surface voxels: %zu\n", shellCount);
    if (!shellCount) { fprintf(stderr, "mesh produced no voxels\n"); return 1; }

    // flood fill outside air (6-connected, seeded from every boundary empty cell)
    std::vector<uint8_t> outside(cells, 0);
    std::deque<std::array<int, 3>> queue;
    auto seed = [&](int x, int y, int z) {
        size_t ci = cellIndex(x, y, z);
        if (!occ[ci] && !outside[ci]) { outside[ci] = 1; queue.push_back({x, y, z}); }
    };
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x) { seed(x, y, 0); seed(x, y, D - 1); }
    for (int z = 0; z < D; ++z)
        for (int x = 0; x < W; ++x) { seed(x, 0, z); seed(x, H - 1, z); }
    for (int z = 0; z < D; ++z)
        for (int y = 0; y < H; ++y) { seed(0, y, z); seed(W - 1, y, z); }
    const int nbr[6][3] = {{1,0,0},{-1,0,0},{0,1,0},{0,-1,0},{0,0,1},{0,0,-1}};
    while (!queue.empty()) {
        auto [x, y, z] = queue.front();
        queue.pop_front();
        for (auto& d : nbr) {
            int nx = x + d[0], ny = y + d[1], nz = z + d[2];
            if (nx < 0 || ny < 0 || nz < 0 || nx >= W || ny >= H || nz >= D) continue;
            seed(nx, ny, nz);
        }
    }

    // enclosed voxels: no 6-neighbor is outside air (grid border counts as outside)
    auto touchesOutside = [&](int x, int y, int z) {
        for (auto& d : nbr) {
            int nx = x + d[0], ny = y + d[1], nz = z + d[2];
            if (nx < 0 || ny < 0 || nz < 0 || nx >= W || ny >= H || nz >= D) return true;
            if (outside[cellIndex(nx, ny, nz)]) return true;
        }
        return false;
    };

    // final voxel set. hollow: shell minus enclosed. fill: shell + enclosed empty space.
    std::vector<uint8_t> keep(cells, 0);
    size_t dropped = 0, cavity = 0;
    for (int z = 0; z < D; ++z)
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x) {
                size_t ci = cellIndex(x, y, z);
                if (occ[ci]) {
                    bool enclosed = !touchesOutside(x, y, z);
                    if (enclosed && !args.fill) { dropped++; continue; }
                    keep[ci] = 1;
                } else if (args.fill && !outside[ci]) {
                    keep[ci] = 1;
                    cavity++;
                }
            }
    if (args.fill) printf("filled: +%zu cavity voxels, kept %zu enclosed surface voxels\n", cavity, dropped);
    else if (dropped) printf("dropped %zu enclosed voxels (hollow shell; use --fill to keep)\n", dropped);

    // colors: average accumulated samples; colorless kept voxels (cavity fill /
    // fully transparent) inherit the nearest colored voxel via BFS
    std::vector<std::array<uint8_t, 3>> voxColor(cells, {0, 0, 0});
    std::vector<uint8_t> hasColor(cells, 0);
    std::deque<std::array<int, 3>> cq;
    for (int z = 0; z < D; ++z)
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x) {
                size_t ci = cellIndex(x, y, z);
                if (!keep[ci]) continue;
                auto it = color.find(ci);
                if (it != color.end() && it->second.n) {
                    const Accum& a = it->second;
                    voxColor[ci] = {uint8_t(a.r / a.n + .5), uint8_t(a.g / a.n + .5), uint8_t(a.b / a.n + .5)};
                    hasColor[ci] = 1;
                    cq.push_back({x, y, z});
                }
            }
    while (!cq.empty()) {
        auto [x, y, z] = cq.front();
        cq.pop_front();
        size_t ci = cellIndex(x, y, z);
        for (auto& d : nbr) {
            int nx = x + d[0], ny = y + d[1], nz = z + d[2];
            if (nx < 0 || ny < 0 || nz < 0 || nx >= W || ny >= H || nz >= D) continue;
            size_t nc = cellIndex(nx, ny, nz);
            if (keep[nc] && !hasColor[nc]) {
                voxColor[nc] = voxColor[ci];
                hasColor[nc] = 1;
                cq.push_back({nx, ny, nz});
            }
        }
    }
    for (size_t ci = 0; ci < cells; ++ci)
        if (keep[ci] && !hasColor[ci]) voxColor[ci] = {200, 200, 200};

    // palette: unique colors, median cut to 255, sort dark->light
    std::map<RGB, uint32_t> hist;
    for (size_t ci = 0; ci < cells; ++ci)
        if (keep[ci]) hist[{voxColor[ci][0], voxColor[ci][1], voxColor[ci][2]}]++;
    printf("unique voxel colors: %zu\n", hist.size());
    std::vector<RGB> pal;
    if (hist.size() <= 255) {
        for (auto& kv : hist) pal.push_back(kv.first);
    } else {
        std::vector<RGB> all;
        all.reserve(hist.size());
        for (auto& kv : hist)
            for (uint32_t k = 0; k < std::min(kv.second, 32u); ++k) // weight by count, capped
                all.push_back(kv.first);
        pal = medianCut(std::move(all), 255);
    }
    std::sort(pal.begin(), pal.end(), [](const RGB& a, const RGB& b) {
        int la = 299 * a.r + 587 * a.g + 114 * a.b;
        int lb = 299 * b.r + 587 * b.g + 114 * b.b;
        return la != lb ? la < lb : a < b;
    });
    pal.erase(std::unique(pal.begin(), pal.end(), [](const RGB& a, const RGB& b) {
                  return a.r == b.r && a.g == b.g && a.b == b.b;
              }),
              pal.end());
    auto nearestPal = [&](const std::array<uint8_t, 3>& c) -> uint8_t {
        int best = 0;
        long bestD = LONG_MAX;
        for (size_t i = 0; i < pal.size(); ++i) {
            long dr = long(pal[i].r) - c[0], dg = long(pal[i].g) - c[1], db = long(pal[i].b) - c[2];
            long d = dr * dr + dg * dg + db * db;
            if (d < bestD) { bestD = d; best = int(i); }
        }
        return uint8_t(best + 1); // .vox color indices are 1-based
    };

    // emit voxels in vox space: vox(x,y,z) = (gx, D-1-gz, gy)  [Y-up -> Z-up rotation]
    struct VoxOut { uint8_t x, y, z, c; };
    std::vector<VoxOut> voxels;
    voxels.reserve(shellCount + cavity);
    for (int z = 0; z < D; ++z)
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x) {
                size_t ci = cellIndex(x, y, z);
                if (!keep[ci]) continue;
                uint8_t vy = args.noDepthFlip ? uint8_t(z) : uint8_t(D - 1 - z);
                voxels.push_back({uint8_t(x), vy, uint8_t(y), nearestPal(voxColor[ci])});
            }

    // write .vox (version 150: SIZE + XYZI + RGBA inside MAIN)
    {
        FILE* f = fopen(args.out.c_str(), "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", args.out.c_str()); return 1; }
        auto u32 = [&](uint32_t v) { fwrite(&v, 4, 1, f); };
        uint32_t nvox = uint32_t(voxels.size());
        uint32_t sizeLen = 12, xyziLen = 4 + nvox * 4, rgbaLen = 1024;
        uint32_t childLen = (12 + sizeLen) + (12 + xyziLen) + (12 + rgbaLen);
        fwrite("VOX ", 4, 1, f); u32(150);
        fwrite("MAIN", 4, 1, f); u32(0); u32(childLen);
        fwrite("SIZE", 4, 1, f); u32(sizeLen); u32(0);
        u32(uint32_t(W)); u32(uint32_t(D)); u32(uint32_t(H)); // vox x, y(depth), z(up)
        fwrite("XYZI", 4, 1, f); u32(xyziLen); u32(0); u32(nvox);
        for (const VoxOut& v : voxels) fwrite(&v, 4, 1, f);
        fwrite("RGBA", 4, 1, f); u32(rgbaLen); u32(0);
        for (int i = 0; i < 256; ++i) {
            uint8_t entry[4] = {0, 0, 0, 255};
            if (i < int(pal.size())) { entry[0] = pal[i].r; entry[1] = pal[i].g; entry[2] = pal[i].b; }
            fwrite(entry, 4, 1, f);
        }
        bool wfail = ferror(f) != 0;
        wfail = (fclose(f) != 0) || wfail;
        if (wfail) { fprintf(stderr, "write failed for %s\n", args.out.c_str()); return 1; }
        printf("wrote %s: %u voxels, %zu palette colors, SIZE %dx%dx%d (vox x/y/z)\n",
               args.out.c_str(), nvox, pal.size(), W, D, H);
    }

    // QA previews: orthographic first-hit renders, x16 nearest upscale
    if (!args.previewDir.empty()) {
        std::string base = args.out;
        size_t slash = base.find_last_of("/\\");
        if (slash != std::string::npos) base = base.substr(slash + 1);
        size_t dot = base.find_last_of('.');
        if (dot != std::string::npos) base = base.substr(0, dot);

        // rebuild a vox-space lookup
        std::map<std::array<int, 3>, std::array<uint8_t, 3>> voxMap;
        for (const VoxOut& v : voxels) {
            RGB c = pal[v.c - 1];
            voxMap[{v.x, v.y, v.z}] = {c.r, c.g, c.b};
        }
        const int SC = 16;
        int VD = D; // vox y extent
        auto writeView = [&](const char* name, int iw, int ih,
                             std::function<const std::array<uint8_t, 3>*(int, int)> hit) {
            std::vector<uint8_t> img(size_t(iw) * ih * 3 * SC * SC, 205);
            for (int py = 0; py < ih; ++py)
                for (int px = 0; px < iw; ++px) {
                    const std::array<uint8_t, 3>* c = hit(px, py);
                    if (!c) continue;
                    for (int sy = 0; sy < SC; ++sy)
                        for (int sx = 0; sx < SC; ++sx) {
                            size_t o = ((size_t(py) * SC + sy) * (size_t(iw) * SC) + size_t(px) * SC + sx) * 3;
                            img[o] = (*c)[0]; img[o + 1] = (*c)[1]; img[o + 2] = (*c)[2];
                        }
                }
            std::string p = args.previewDir + "/" + base + "_vox_" + name + ".png";
            if (stbi_write_png(p.c_str(), iw * SC, ih * SC, 3, img.data(), iw * SC * 3))
                printf("preview %s\n", p.c_str());
            else
                fprintf(stderr, "preview write FAILED: %s (does the directory exist?)\n", p.c_str());
        };
        // front: viewer at -Y looking +Y. image x = vox x mirrored, image y = up flipped.
        writeView("front", W, H, [&](int px, int py) -> const std::array<uint8_t, 3>* {
            for (int y = 0; y < VD; ++y) {
                auto it = voxMap.find({W - 1 - px, y, H - 1 - py});
                if (it != voxMap.end()) return &it->second;
            }
            return nullptr;
        });
        // side: viewer at +X looking -X (animal's left side if it faces -Y). image x = vox y.
        writeView("side", VD, H, [&](int px, int py) -> const std::array<uint8_t, 3>* {
            for (int x = W - 1; x >= 0; --x) {
                auto it = voxMap.find({x, px, H - 1 - py});
                if (it != voxMap.end()) return &it->second;
            }
            return nullptr;
        });
        // top: viewer above looking down -Z. image x = vox x, image y = vox y (front at top).
        writeView("top", W, VD, [&](int px, int py) -> const std::array<uint8_t, 3>* {
            for (int z = H - 1; z >= 0; --z) {
                auto it = voxMap.find({px, py, z});
                if (it != voxMap.end()) return &it->second;
            }
            return nullptr;
        });
    }

    // ASCII slices in vox space, one per height level (z), for rig rule authoring
    if (args.ascii) {
        std::map<std::array<int, 3>, uint8_t> m;
        for (const VoxOut& v : voxels) m[{v.x, v.y, v.z}] = 1;
        for (int z = H - 1; z >= 0; --z) {
            printf("\n-- z=%d (height) --  x: 0..%d ->, y: 0 (front) at top\n", z, W - 1);
            for (int y = 0; y < D; ++y) {
                std::string row;
                for (int x = 0; x < W; ++x) row += m.count({x, y, z}) ? '#' : '.';
                printf("%3d %s\n", y, row.c_str());
            }
        }
    }
    return 0;
}
