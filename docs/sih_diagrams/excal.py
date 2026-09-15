"""
Tiny Excalidraw scene builder + matplotlib previewer for the SIH diagrams.
Shapes are addressed by centre (cx, cy); arrows bind to shapes and route
orthogonally so every connection stays readable on a slide.
"""
import json
import random
import textwrap

FONT = 2          # Excalidraw "Normal" (Helvetica) -- clean for slides
CHAR_W = 0.56     # average glyph width as a fraction of font size
LINE_H = 1.25

C = {  # fill, stroke
    "blue": ("#d0ebff", "#1971c2"), "green": ("#d3f9d8", "#2f9e44"), "yellow": ("#fff3bf", "#e67700"),
    "red": ("#ffe3e3", "#c92a2a"), "violet": ("#e5dbff", "#6741d9"), "grey": ("#f1f3f5", "#495057"),
    "teal": ("#c3fae8", "#0c8599"), "orange": ("#ffe8cc", "#d9480f"), "pink": ("#ffdeeb", "#a61e4d"),
    "white": ("#ffffff", "#1e1e1e"), "dark": ("#343a40", "#212529"), "none": ("transparent", "#1e1e1e"),
}


class Scene:
    def __init__(self, title=None, subtitle=None):
        self.els, self.shapes = [], {}
        self._rng = random.Random(len(title or "x"))
        if title:
            self.text(40, 20, title, 34, "#1e1e1e")
        if subtitle:
            self.text(42, 66, subtitle, 18, "#495057")

    # ------------------------------------------------------------------ utils
    def _id(self):
        return "".join(self._rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))

    def _base(self, typ, x, y, w, h, stroke, bg, **kw):
        el = dict(id=self._id(), type=typ, x=x, y=y, width=w, height=h, angle=0,
                  strokeColor=stroke, backgroundColor=bg, fillStyle="solid",
                  strokeWidth=kw.get("sw", 2), strokeStyle=kw.get("ss", "solid"), roughness=0,
                  opacity=100, groupIds=kw.get("groups", []), frameId=None,
                  roundness=kw.get("roundness"), seed=self._rng.randint(1, 2**31),
                  version=1, versionNonce=self._rng.randint(1, 2**31), isDeleted=False,
                  boundElements=[], updated=1726444800000, link=None, locked=False)
        self.els.append(el)
        return el

    @staticmethod
    def wrap(text, w, fs):
        per = max(4, int((w - 16) / (fs * CHAR_W)))
        out = []
        for para in text.split("\n"):
            out += textwrap.wrap(para, per) or [""]
        return "\n".join(out)

    def _text_el(self, x, y, text, fs, color, align="left", valign="top", container=None, groups=None):
        lines = text.split("\n")
        w = max(len(l) for l in lines) * fs * CHAR_W
        h = len(lines) * fs * LINE_H
        el = self._base("text", x, y, w, h, color, "transparent", sw=1, groups=groups or [])
        el.update(text=text, originalText=text, fontSize=fs, fontFamily=FONT, textAlign=align,
                  verticalAlign=valign, containerId=container, autoResize=True, lineHeight=LINE_H)
        return el

    def text(self, x, y, text, fs=18, color="#1e1e1e", align="left"):
        el = self._text_el(x, y, text, fs, color, align)
        if align == "center":
            el["x"] = x - el["width"] / 2
        return el

    # ----------------------------------------------------------------- shapes
    def box(self, key, cx, cy, w, h, text="", color="blue", fs=16, shape="rectangle",
            ss="solid", sw=2, text_color=None, align="center", round_=True, fill=None):
        bg, stroke = C[color]
        if fill:
            bg = fill
        rnd = {"type": 3} if (shape == "rectangle" and round_) else ({"type": 2} if shape != "rectangle" else None)
        el = self._base(shape, cx - w / 2, cy - h / 2, w, h, stroke, bg, ss=ss, sw=sw, roundness=rnd)
        self.shapes[key] = el
        if text:
            inner = w * (0.62 if shape == "diamond" else 0.8 if shape == "ellipse" else 1)
            t = self.wrap(text, inner, fs)
            tel = self._text_el(0, 0, t, fs, text_color or ("#ffffff" if color == "dark" else "#1e1e1e"),
                                align=align, valign="middle", container=el["id"])
            need = tel["height"] + (16 if shape == "rectangle" else 40)
            if need > h + 1:
                print(f"  ! text overflows '{key}': needs h>={need:.0f}, has {h}")
            tel["x"] = cx - tel["width"] / 2 if align == "center" else el["x"] + 10
            tel["y"] = cy - tel["height"] / 2
            el["boundElements"].append({"type": "text", "id": tel["id"]})
        return el

    def label_box(self, key, x, y, w, h, title, color="grey", fs=20, ss="dashed"):
        """Big container (lane / group / system boundary) with title in top-left."""
        bg, stroke = C[color]
        el = self._base("rectangle", x, y, w, h, stroke, bg, ss=ss, sw=2, roundness={"type": 3})
        el["fillStyle"] = "solid"
        self.shapes[key] = el
        self.text(x + 14, y + 10, title, fs, stroke)
        return el

    def actor(self, key, cx, cy, name, color="#1e1e1e"):
        g = [self._id()]
        head = self._base("ellipse", cx - 16, cy - 60, 32, 32, color, "#ffffff", groups=g, roundness={"type": 2})
        self.line([(cx, cy - 28), (cx, cy + 12)], color, groups=g)
        self.line([(cx - 28, cy - 14), (cx + 28, cy - 14)], color, groups=g)
        self.line([(cx, cy + 12), (cx - 22, cy + 46)], color, groups=g)
        self.line([(cx, cy + 12), (cx + 22, cy + 46)], color, groups=g)
        t = self.text(cx, cy + 54, name, 16, color, align="center")
        t["groupIds"] = g
        hit = self._base("rectangle", cx - 60, cy - 64, 120, 150, "transparent", "transparent", groups=g, sw=1)
        self.shapes[key] = hit
        return hit

    def line(self, pts, color="#1e1e1e", ss="solid", sw=2, groups=None):
        x0, y0 = pts[0]
        rel = [[px - x0, py - y0] for px, py in pts]
        el = self._base("line", x0, y0, max(abs(p[0]) for p in rel), max(abs(p[1]) for p in rel),
                        color, "transparent", ss=ss, sw=sw, groups=groups or [])
        el.update(points=rel, lastCommittedPoint=None, startBinding=None, endBinding=None,
                  startArrowhead=None, endArrowhead=None)
        return el

    # ----------------------------------------------------------------- arrows
    @staticmethod
    def _side_pt(el, side, f=0.5):
        x, y, w, h = el["x"], el["y"], el["width"], el["height"]
        return {"l": (x, y + h * f), "r": (x + w, y + h * f), "t": (x + w * f, y), "b": (x + w * f, y + h)}[side]

    @staticmethod
    def _toward(el, other):
        """boundary point of el in the direction of other's centre (straight connectors)."""
        cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
        ox, oy = other["x"] + other["width"] / 2, other["y"] + other["height"] / 2
        dx, dy = ox - cx, oy - cy
        a, b = el["width"] / 2, el["height"] / 2
        if el["type"] == "ellipse":
            k = 1 / (((dx / a) ** 2 + (dy / b) ** 2) ** 0.5 or 1)
        else:
            k = min(a / abs(dx) if dx else 1e9, b / abs(dy) if dy else 1e9)
        return cx + dx * k, cy + dy * k

    def arrow(self, a, b, label=None, sides=None, at=(0.5, 0.5), via=None, color="#1e1e1e",
              ss="solid", sw=2, both=False, head=True, straight=False, fs=14, label_pos=None):
        A, B = self.shapes[a], self.shapes[b]
        acx, acy = A["x"] + A["width"] / 2, A["y"] + A["height"] / 2
        bcx, bcy = B["x"] + B["width"] / 2, B["y"] + B["height"] / 2
        if straight:
            pts = [self._toward(A, B), self._toward(B, A)]
        else:
            if sides is None:
                dx, dy = bcx - acx, bcy - acy
                sides = ("r", "l") if abs(dx) >= abs(dy) and dx > 0 else ("l", "r") if abs(dx) >= abs(dy) \
                    else ("b", "t") if dy > 0 else ("t", "b")
            S = self._side_pt(A, sides[0], at[0])
            E = self._side_pt(B, sides[1], at[1])
            hz = {"l", "r"}
            if via:
                pts = [S, *via, E]
            elif sides[0] in hz and sides[1] in hz:
                mx = (S[0] + E[0]) / 2
                pts = [S, E] if abs(S[1] - E[1]) < 1 else [S, (mx, S[1]), (mx, E[1]), E]
            elif sides[0] not in hz and sides[1] not in hz:
                my = (S[1] + E[1]) / 2
                pts = [S, E] if abs(S[0] - E[0]) < 1 else [S, (S[0], my), (E[0], my), E]
            elif sides[0] in hz:
                pts = [S, (E[0], S[1]), E]
            else:
                pts = [S, (S[0], E[1]), E]
        clean = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - clean[-1][0]) > 0.5 or abs(p[1] - clean[-1][1]) > 0.5:
                clean.append(p)
        pts = clean
        x0, y0 = pts[0]
        rel = [[px - x0, py - y0] for px, py in pts]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        el = self._base("arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), color, "transparent",
                        ss=ss, sw=sw, roundness=None)
        el.update(points=rel, lastCommittedPoint=None, elbowed=False,
                  startBinding={"elementId": A["id"], "focus": 0, "gap": 4},
                  endBinding={"elementId": B["id"], "focus": 0, "gap": 4},
                  startArrowhead="arrow" if both else None, endArrowhead="arrow" if head else None)
        A["boundElements"].append({"type": "arrow", "id": el["id"]})
        B["boundElements"].append({"type": "arrow", "id": el["id"]})
        if label:
            n = len(pts)
            if label_pos:
                mx, my = label_pos
            elif n % 2:
                mx, my = pts[n // 2]
            else:
                (ax, ay), (bx, by) = pts[n // 2 - 1], pts[n // 2]
                mx, my = (ax + bx) / 2, (ay + by) / 2
            t = self._text_el(0, 0, label, fs, color if color != "#1e1e1e" else "#343a40",
                              align="center", valign="middle", container=el["id"])
            t["x"], t["y"] = mx - t["width"] / 2, my - t["height"] / 2
            el["boundElements"].append({"type": "text", "id": t["id"]})
        return el

    def free_arrow(self, pts, label=None, color="#1e1e1e", ss="solid", sw=2, both=False, fs=14, head=True):
        """Unbound arrow through absolute points (sequence-diagram messages)."""
        x0, y0 = pts[0]
        rel = [[px - x0, py - y0] for px, py in pts]
        xs, ys = [p[0] for p in rel], [p[1] for p in rel]
        el = self._base("arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), color, "transparent",
                        ss=ss, sw=sw, roundness=None)
        el.update(points=rel, lastCommittedPoint=None, elbowed=False, startBinding=None, endBinding=None,
                  startArrowhead="arrow" if both else None, endArrowhead="arrow" if head else None)
        if label:
            (ax, ay), (bx, by) = pts[0], pts[-1]
            t = self._text_el(0, 0, label, fs, color, align="center", valign="middle", container=el["id"])
            t["x"], t["y"] = (ax + bx) / 2 - t["width"] / 2, (ay + by) / 2 - t["height"] / 2
            el["boundElements"].append({"type": "text", "id": t["id"]})
        return el

    # ------------------------------------------------------------------- save
    def save(self, path):
        doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
               "elements": self.els,
               "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"}, "files": {}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)

    def preview(self, path, dpi=150):
        """Render a PNG with matplotlib (close to what Excalidraw shows, for slides/README)."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch, Ellipse, Polygon, FancyArrowPatch
        xs, ys = [], []
        for e in self.els:
            if "points" in e:  # linear elements: bbox from their actual points
                xs += [e["x"] + p[0] for p in e["points"]]
                ys += [e["y"] + p[1] for p in e["points"]]
            elif e["strokeColor"] != "transparent" or e["type"] == "text":
                xs += [e["x"], e["x"] + e["width"]]
                ys += [e["y"], e["y"] + e["height"]]
        X0, X1, Y0, Y1 = min(xs) - 30, max(xs) + 30, min(ys) - 30, max(ys) + 30
        fig = plt.figure(figsize=((X1 - X0) / 100, (Y1 - Y0) / 100), dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(X0, X1)
        ax.set_ylim(Y1, Y0)
        ax.axis("off")
        fig.patch.set_facecolor("white")
        byid = {e["id"]: e for e in self.els}
        pt = 0.72  # px -> pt for a figure sized at 100 units per inch
        for e in self.els:
            col = e["strokeColor"] if e["strokeColor"] != "transparent" else "none"
            fc = e["backgroundColor"] if e["backgroundColor"] != "transparent" else "none"
            ls = "--" if e["strokeStyle"] == "dashed" else "-"
            lw = e["strokeWidth"] * 0.8
            if e["type"] == "rectangle":
                ax.add_patch(FancyBboxPatch((e["x"], e["y"]), e["width"], e["height"],
                                            boxstyle="round,pad=0,rounding_size=14" if e["roundness"] else "square,pad=0",
                                            fc=fc, ec=col, lw=lw, ls=ls))
            elif e["type"] == "ellipse":
                ax.add_patch(Ellipse((e["x"] + e["width"] / 2, e["y"] + e["height"] / 2), e["width"], e["height"],
                                     fc=fc, ec=col, lw=lw, ls=ls))
            elif e["type"] == "diamond":
                x, y, w, h = e["x"], e["y"], e["width"], e["height"]
                ax.add_patch(Polygon([(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)],
                                     fc=fc, ec=col, lw=lw, ls=ls))
            elif e["type"] in ("arrow", "line"):
                P = [(e["x"] + p[0], e["y"] + p[1]) for p in e["points"]]
                ax.plot([p[0] for p in P], [p[1] for p in P], color=col, lw=lw, ls=ls, solid_capstyle="round")
                for tip, tail, on in ((P[-1], P[-2], e.get("endArrowhead")), (P[0], P[1], e.get("startArrowhead"))):
                    if on:
                        ax.add_patch(FancyArrowPatch(tail, tip, arrowstyle="-|>", mutation_scale=16,
                                                     color=col, lw=0, shrinkA=0, shrinkB=0))
        for e in self.els:
            if e["type"] != "text":
                continue
            cont = byid.get(e["containerId"]) if e["containerId"] else None
            fs = e["fontSize"] * pt
            kw = dict(fontsize=fs, color=e["strokeColor"], family="Arial", linespacing=1.3)
            if cont and cont["type"] == "arrow":
                ax.text(e["x"] + e["width"] / 2, e["y"] + e["height"] / 2, e["text"], ha="center", va="center",
                        bbox=dict(fc="white", ec="none", pad=1.5), **kw)
            elif cont:
                cy = cont["y"] + cont["height"] / 2
                if e["textAlign"] == "center":
                    ax.text(cont["x"] + cont["width"] / 2, cy, e["text"], ha="center", va="center", **kw)
                else:
                    ax.text(cont["x"] + 14, cy, e["text"], ha="left", va="center", **kw)
            else:
                ha = "center" if e["textAlign"] == "center" else "left"
                x = e["x"] + (e["width"] / 2 if ha == "center" else 0)
                ax.text(x, e["y"], e["text"], ha=ha, va="top", **kw)
        fig.savefig(path, dpi=dpi, facecolor="white")
        plt.close(fig)
