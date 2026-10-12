"""Headless OpenGL renderer for instanced rounded rectangles."""

from __future__ import annotations

import moderngl
import numpy as np

_VERTEX_SHADER = """
#version 330
uniform vec2 u_size;
in vec2 in_corner;
in vec4 in_rect;
in vec4 in_color;
in float in_radius;
out vec2 v_local;
out vec2 v_half;
out vec4 v_color;
out float v_radius;
void main() {
    vec2 half_size = in_rect.zw * 0.5;
    v_local = (in_corner - 0.5) * in_rect.zw;
    v_half = half_size;
    v_color = in_color;
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
out vec4 f_color;
void main() {
    vec2 q = abs(v_local) - v_half + v_radius;
    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - v_radius;
    float alpha = clamp(0.5 - d, 0.0, 1.0) * v_color.a;
    f_color = vec4(v_color.rgb, alpha);
}
"""

_FLOATS_PER_INSTANCE = 9
_INITIAL_CAPACITY = 1024


class Renderer:
    """Draws rounded rectangles offscreen and returns RGB24 frames."""

    def __init__(self, width: int, height: int, background: tuple[float, float, float]):
        self.width = width
        self.height = height
        self.background = background
        self.ctx = moderngl.create_standalone_context(require=330)
        self.fbo = self.ctx.framebuffer(
            color_attachments=[self.ctx.renderbuffer((width, height), components=4)]
        )
        self.prog = self.ctx.program(
            vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER
        )
        self.prog["u_size"].value = (float(width), float(height))
        quad = np.array([0, 0, 1, 0, 0, 1, 1, 1], dtype="f4")
        self.quad_vbo = self.ctx.buffer(quad.tobytes())
        self.capacity = 0
        self.instance_vbo: moderngl.Buffer | None = None
        self.vao: moderngl.VertexArray | None = None
        self._resize(_INITIAL_CAPACITY)

    def _resize(self, capacity: int) -> None:
        if self.vao is not None:
            self.vao.release()
        if self.instance_vbo is not None:
            self.instance_vbo.release()
        self.capacity = capacity
        self.instance_vbo = self.ctx.buffer(
            reserve=capacity * _FLOATS_PER_INSTANCE * 4, dynamic=True
        )
        self.vao = self.ctx.vertex_array(
            self.prog,
            [
                (self.quad_vbo, "2f", "in_corner"),
                (self.instance_vbo, "4f 4f 1f/i", "in_rect", "in_color", "in_radius"),
            ],
        )

    def render(self, instances: np.ndarray) -> bytes:
        """Draw one frame; return RGB24 bytes, rows top-to-bottom."""
        self.fbo.use()
        self.ctx.viewport = (0, 0, self.width, self.height)
        self.fbo.clear(*self.background, 1.0)
        n = len(instances)
        if n:
            if n > self.capacity:
                self._resize(max(n, self.capacity * 2))
            data = np.ascontiguousarray(instances, dtype="f4")
            self.instance_vbo.write(data)
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.vao.render(moderngl.TRIANGLE_STRIP, instances=n)
        return self.fbo.read(components=3)

    def release(self) -> None:
        for obj in (self.vao, self.instance_vbo, self.quad_vbo, self.prog, self.fbo):
            if obj is not None:
                obj.release()
        self.vao = self.instance_vbo = None
        self.ctx.release()

    def __enter__(self) -> Renderer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
