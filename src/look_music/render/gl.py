"""Headless OpenGL renderer for instanced rounded rectangles."""

from __future__ import annotations

import math
from dataclasses import dataclass

import moderngl
import numpy as np

_VERTEX_SHADER = """
#version 330
uniform vec2 u_size;
in vec2 in_corner;
in vec4 in_rect;
in vec4 in_color;
in float in_radius;
in float in_glow;
out vec2 v_local;
out vec2 v_half;
out vec4 v_color;
out float v_radius;
out float v_glow;
void main() {
    vec2 half_size = in_rect.zw * 0.5;
    v_local = (in_corner - 0.5) * in_rect.zw;
    v_half = half_size;
    v_color = in_color;
    v_glow = in_glow;
    v_radius = min(in_radius, min(half_size.x, half_size.y));
    // Pixel y=0 (top) -> NDC y=-1 so fbo.read's bottom-first rows come out top-to-bottom.
    vec2 pos = in_rect.xy + in_corner * in_rect.zw;
    gl_Position = vec4(pos.x / u_size.x * 2.0 - 1.0, pos.y / u_size.y * 2.0 - 1.0, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER = """
#version 330
in vec2 v_local;
in vec2 v_half;
in vec4 v_color;
in float v_radius;
in float v_glow;
layout(location = 0) out vec4 f_color;
layout(location = 1) out vec4 f_glow;
void main() {
    vec2 q = abs(v_local) - v_half + v_radius;
    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - v_radius;
    float alpha = clamp(0.5 - d, 0.0, 1.0) * v_color.a;
    f_color = vec4(v_color.rgb, alpha);
    // Same blend func as f_color: result is color * coverage * alpha * glow.
    f_glow = vec4(v_color.rgb, alpha * v_glow);
}
"""

_FULLSCREEN_VERTEX = """
#version 330
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

_COPY_FRAGMENT = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_size;
out vec4 f_out;
void main() {
    f_out = texture(u_tex, gl_FragCoord.xy / u_size);
}
"""

_BLUR_FRAGMENT = """
#version 330
uniform sampler2D u_tex;
uniform vec2 u_size;
uniform vec2 u_dir;     // texel step direction, e.g. (1, 0)
uniform float u_sigma;  // in texels
uniform int u_taps;     // samples per side
uniform float u_step;   // texel spacing between taps
out vec4 f_out;
void main() {
    vec2 uv = gl_FragCoord.xy / u_size;
    vec2 off = u_dir * u_step / u_size;
    float inv = 1.0 / (2.0 * u_sigma * u_sigma);
    vec4 sum = texture(u_tex, uv);
    float wsum = 1.0;
    for (int i = 1; i <= u_taps; i++) {
        float d = float(i) * u_step;
        float w = exp(-d * d * inv);
        sum += w * (texture(u_tex, uv + off * float(i)) + texture(u_tex, uv - off * float(i)));
        wsum += 2.0 * w;
    }
    f_out = sum / wsum;
}
"""

_COMPOSITE_FRAGMENT = """
#version 330
uniform sampler2D u_scene;
uniform sampler2D u_glow;
uniform vec2 u_size;
uniform float u_intensity;
out vec4 f_out;
void main() {
    vec2 uv = gl_FragCoord.xy / u_size;
    vec3 base = texture(u_scene, uv).rgb;
    vec3 glow = texture(u_glow, uv).rgb;
    f_out = vec4(clamp(base + u_intensity * glow, 0.0, 1.0), 1.0);
}
"""

_FLOATS_PER_INSTANCE = 10
_INITIAL_CAPACITY = 1024
_MAX_BLUR_TAPS = 16


@dataclass(frozen=True)
class BloomSettings:
    intensity: float = 0.9  # how strongly the blurred glow is added back
    radius: float = 24.0  # blur radius in pixels at 1080p (scales with frame height)
    downsample: int = 2  # blur at 1/downsample resolution for speed


class Renderer:
    """Draws rounded rectangles offscreen and returns RGB24 frames."""

    def __init__(
        self,
        width: int,
        height: int,
        background: tuple[float, float, float],
        bloom: BloomSettings | None = None,
    ):
        self.width = width
        self.height = height
        self.background = background
        self.bloom = bloom
        self.ctx = moderngl.create_standalone_context(require=330)
        self._objects: list[object] = []
        self.prog = self._track(
            self.ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)
        )
        self.prog["u_size"].value = (float(width), float(height))
        quad = np.array([0, 0, 1, 0, 0, 1, 1, 1], dtype="f4")
        self.quad_vbo = self._track(self.ctx.buffer(quad.tobytes()))
        self.capacity = 0
        self.instance_vbo: moderngl.Buffer | None = None
        self.vao: moderngl.VertexArray | None = None
        self._resize(_INITIAL_CAPACITY)
        if bloom is None:
            self.fbo = self._track(
                self.ctx.framebuffer(
                    color_attachments=[self.ctx.renderbuffer((width, height), components=4)]
                )
            )
        else:
            self._init_bloom(bloom)

    def _track(self, obj):
        self._objects.append(obj)
        return obj

    def _texture(self, size: tuple[int, int], dtype: str = "f1") -> moderngl.Texture:
        tex = self._track(self.ctx.texture(size, 4, dtype=dtype))
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        return tex

    def _init_bloom(self, bloom: BloomSettings) -> None:
        w, h = self.width, self.height
        ds = max(1, int(bloom.downsample))
        self.bw, self.bh = max(1, w // ds), max(1, h // ds)
        self.scene_tex = self._texture((w, h))
        try:
            self.glow_tex = self._texture((w, h), "f2")
            self.fbo = self._track(
                self.ctx.framebuffer(color_attachments=[self.scene_tex, self.glow_tex])
            )
        except Exception:
            self.glow_tex = self._texture((w, h))
            self.fbo = self._track(
                self.ctx.framebuffer(color_attachments=[self.scene_tex, self.glow_tex])
            )
        glow_dtype = "f2" if self.glow_tex.dtype == "f2" else "f1"
        self.blur_a = self._texture((self.bw, self.bh), glow_dtype)
        self.blur_b = self._texture((self.bw, self.bh), glow_dtype)
        self.blur_fbo_a = self._track(self.ctx.framebuffer(color_attachments=[self.blur_a]))
        self.blur_fbo_b = self._track(self.ctx.framebuffer(color_attachments=[self.blur_b]))
        self.out_tex = self._texture((w, h))
        self.out_fbo = self._track(self.ctx.framebuffer(color_attachments=[self.out_tex]))

        def program(fragment: str) -> moderngl.Program:
            return self._track(
                self.ctx.program(vertex_shader=_FULLSCREEN_VERTEX, fragment_shader=fragment)
            )

        self.copy_prog = program(_COPY_FRAGMENT)
        self.blur_prog = program(_BLUR_FRAGMENT)
        self.comp_prog = program(_COMPOSITE_FRAGMENT)
        self.empty_vao = self._track(self.ctx.vertex_array(self.copy_prog, []))
        self.blur_vao = self._track(self.ctx.vertex_array(self.blur_prog, []))
        self.comp_vao = self._track(self.ctx.vertex_array(self.comp_prog, []))
        sigma = max(bloom.radius * h / 1080.0 / ds, 0.01)
        taps = max(1, min(_MAX_BLUR_TAPS, math.ceil(3.0 * sigma)))
        self.blur_prog["u_sigma"].value = sigma
        self.blur_prog["u_taps"].value = taps
        self.blur_prog["u_step"].value = max(1.0, 3.0 * sigma / taps)
        self.blur_prog["u_size"].value = (float(self.bw), float(self.bh))
        self.blur_prog["u_tex"].value = 0
        self.copy_prog["u_size"].value = (float(self.bw), float(self.bh))
        self.copy_prog["u_tex"].value = 0
        self.comp_prog["u_size"].value = (float(w), float(h))
        self.comp_prog["u_scene"].value = 0
        self.comp_prog["u_glow"].value = 1
        self.comp_prog["u_intensity"].value = float(bloom.intensity)

    def _resize(self, capacity: int) -> None:
        if self.vao is not None:
            self.vao.release()
            self._objects.remove(self.vao)
        if self.instance_vbo is not None:
            self.instance_vbo.release()
            self._objects.remove(self.instance_vbo)
        self.capacity = capacity
        self.instance_vbo = self._track(
            self.ctx.buffer(reserve=capacity * _FLOATS_PER_INSTANCE * 4, dynamic=True)
        )
        self.vao = self._track(
            self.ctx.vertex_array(
                self.prog,
                [
                    (self.quad_vbo, "2f", "in_corner"),
                    (
                        self.instance_vbo,
                        "4f 4f 1f 1f/i",
                        "in_rect",
                        "in_color",
                        "in_radius",
                        "in_glow",
                    ),
                ],
            )
        )

    def _fullscreen_pass(self, fbo: moderngl.Framebuffer, vao: moderngl.VertexArray) -> None:
        fbo.use()
        self.ctx.viewport = (0, 0, *fbo.size)
        vao.render(moderngl.TRIANGLES, vertices=3)

    def render(self, instances: np.ndarray) -> bytes:
        """Draw one frame; return RGB24 bytes, rows top-to-bottom."""
        self.fbo.use()
        self.ctx.viewport = (0, 0, self.width, self.height)
        self.ctx.disable(moderngl.BLEND)
        if self.bloom is None:
            self.fbo.clear(*self.background, 1.0)
        else:
            self.fbo.clear(0.0, 0.0, 0.0, 0.0)  # both attachments to transparent black
            self.fbo.color_mask = ((True,) * 4, (False,) * 4)
            self.fbo.clear(*self.background, 1.0)  # scene attachment only
            self.fbo.color_mask = ((True,) * 4, (True,) * 4)
        n = len(instances)
        if n:
            if n > self.capacity:
                self._resize(max(n, self.capacity * 2))
            data = np.ascontiguousarray(instances, dtype="f4")
            self.instance_vbo.write(data)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.vao.render(moderngl.TRIANGLE_STRIP, instances=n)
            self.ctx.disable(moderngl.BLEND)
        if self.bloom is None:
            return self.fbo.read(components=3)
        # Downsample, then separable Gaussian (horizontal -> vertical).
        self.glow_tex.use(0)
        self._fullscreen_pass(self.blur_fbo_a, self.empty_vao)
        self.blur_a.use(0)
        self.blur_prog["u_dir"].value = (1.0, 0.0)
        self._fullscreen_pass(self.blur_fbo_b, self.blur_vao)
        self.blur_b.use(0)
        self.blur_prog["u_dir"].value = (0.0, 1.0)
        self._fullscreen_pass(self.blur_fbo_a, self.blur_vao)
        self.scene_tex.use(0)
        self.blur_a.use(1)
        self._fullscreen_pass(self.out_fbo, self.comp_vao)
        return self.out_fbo.read(components=3)

    def release(self) -> None:
        for obj in reversed(self._objects):
            obj.release()
        self._objects.clear()
        self.vao = self.instance_vbo = None
        self.ctx.release()

    def __enter__(self) -> Renderer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
