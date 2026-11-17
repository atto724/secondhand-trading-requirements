"""Main-thread image reuse, wheel routing and bounded background jobs."""

import logging
import tkinter as tk
from collections import OrderedDict
from queue import Empty, Queue
from threading import Thread
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageTk


class BackgroundJob:
    """Run one non-Tk task at a time; deliver results only through the Tk event loop."""

    def __init__(self, root):
        self.root = root
        self.busy = False
        self.closed = False
        self.timer = None
        self.results = Queue()
        root.bind("<Destroy>", self.close, add="+")

    def run(self, work, success, failure):
        """Ignore duplicate submissions without starting unbounded worker threads."""
        if self.busy or self.closed:
            return False
        self.busy = True

        results = self.results

        def worker():
            try:
                results.put((True, work()))
            except Exception as error:
                results.put((False, error))

        Thread(target=worker, daemon=True).start()
        self.timer = self.root.after(20, lambda: self.poll(success, failure))
        return True

    def poll(self, success, failure):
        """Never touch widgets from a worker or deliver to a destroyed session."""
        self.timer = None
        if self.closed:
            return
        try:
            ok, value = self.results.get_nowait()
        except Empty:
            self.timer = self.root.after(20, lambda: self.poll(success, failure))
            return
        self.busy = False
        (success if ok else failure)(value)

    def close(self, event):
        """Discard UI delivery when the owning root is closed."""
        if event.widget == self.root:
            self.closed = True
            if self.timer:
                self.root.after_cancel(self.timer)
                self.timer = None


def cached_photo(parent, path, size, circular=False):
    """Reuse up to 128 root-owned Tk images, invalidated by file metadata."""
    root = parent
    while root.master is not None:
        root = root.master
    if not hasattr(root, "photo_cache"):
        root.photo_cache = OrderedDict()
    path = Path(path).resolve()
    stamp = path.stat()
    key = (str(path), stamp.st_mtime_ns, stamp.st_size, size, circular)
    cache = root.photo_cache
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    with Image.open(path) as source:
        source.draft("RGB", (size[0] * 2, size[1] * 2))
        picture = ImageOps.exif_transpose(source).convert("RGBA" if circular else "RGB")
        if circular:
            picture = ImageOps.fit(picture, size, method=Image.Resampling.LANCZOS)
            mask = Image.new("L", (size[0] * 4, size[1] * 4), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, mask.width - 1, mask.height - 1), fill=255)
            picture.putalpha(mask.resize(size, Image.Resampling.LANCZOS))
        else:
            picture.thumbnail(size)
            canvas = Image.new("RGB", size, "#f3ece3")
            canvas.paste(picture, ((size[0] - picture.width) // 2, (size[1] - picture.height) // 2))
            picture = canvas
    photo = ImageTk.PhotoImage(picture, master=root)
    cache[key] = photo
    if len(cache) > 128:
        cache.popitem(last=False)
    return photo


def install_scrolling(root):
    """Route wheel input from images/labels/buttons to their nearest scrollable canvas."""
    if hasattr(root, "scroll_router"):
        return
    router = WheelRouter(root)
    root.scroll_router = router


class WheelRouter:
    """Coalesce high-resolution touchpad deltas into small pixel scrolls."""

    def __init__(self, root):
        self.root = root
        self.tag = f"WheelRouter{id(root)}"
        root.bind_class(self.tag, "<MouseWheel>", self.route)
        root.bind_all("<MouseWheel>", self.route, add="+")
        root.bind_all("<Map>", self.attach, add="+")

    def attach(self, event):
        """Precede old widget bindings, including ones that truncate small deltas."""
        widget = event.widget
        if isinstance(widget, tk.Misc) and self.tag not in widget.bindtags():
            widget.bindtags((self.tag,) + widget.bindtags())

    def route(self, event):
        """Leave native text/list/combobox scrolling to their own bindings."""
        widget = event.widget
        # Windows may deliver wheel events to keyboard focus instead of hover.
        coordinates = (getattr(event, "x_root", None), getattr(event, "y_root", None))
        if all(isinstance(value, (int, float)) for value in coordinates):
            try:
                hovered = self.root.winfo_containing(*coordinates)
                if hovered is not None:
                    widget = hovered
            except (tk.TclError, KeyError):
                pass
        while widget is not None:
            if widget.winfo_class() in ("Text", "Listbox", "Treeview", "TCombobox"):
                return None
            if isinstance(widget, tk.Canvas) and widget.cget("yscrollcommand"):
                return self.enqueue(widget, -event.delta * 0.4)
            widget = widget.master
        return None

    def enqueue(self, canvas, pixels):
        """Apply at most one scroll per animation frame, retaining fractional movement."""
        canvas.wheel_pixels = getattr(canvas, "wheel_pixels", 0.0) + pixels
        if not getattr(canvas, "wheel_timer", None):
            canvas.wheel_timer = canvas.after(16, lambda: self.flush(canvas))
            if not getattr(canvas, "wheel_cleanup", False):
                canvas.wheel_cleanup = True
                canvas.bind("<Destroy>", lambda event: self.cancel(canvas, event), add="+")
        return "break"

    def flush(self, canvas):
        """Use pixel increments instead of viewport-sized jumps."""
        canvas.wheel_timer = None
        pixels = int(canvas.wheel_pixels)
        canvas.wheel_pixels -= pixels
        if pixels:
            canvas.configure(yscrollincrement=1)
            canvas.yview_scroll(pixels, "units")

    def cancel(self, canvas, event):
        """Cancel delayed scroll delivery before a page is destroyed."""
        if event.widget == canvas and getattr(canvas, "wheel_timer", None):
            canvas.after_cancel(canvas.wheel_timer)
            canvas.wheel_timer = None


def log_background_error(error):
    """Record maintenance failures without a modal interrupting the user."""
    logging.error("Background maintenance failed: %s", error)
