"""Layout helpers for small windows, DPI scaling, and monitor-safe geometry."""
import re
import tkinter as tk
from tkinter import ttk


def work_area(window):
    try:
        import ctypes
        from ctypes import wintypes
        class Info(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
        user = ctypes.windll.user32
        user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.MonitorFromWindow.restype = wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
        info = Info(); info.size = ctypes.sizeof(Info)
        monitor = user.MonitorFromWindow(window.winfo_id(), 2)
        if user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.work
            return rect.left, rect.top, rect.right, rect.bottom
    except (AttributeError, OSError, ImportError):
        pass
    return 0, 0, window.winfo_screenwidth(), max(400, window.winfo_screenheight()-40)


def bounded_geometry(saved, area, default=(1160, 790), vertical_margin=80):
    left, top, right, bottom = area
    aw, ah = max(200, right-left-28), max(200, bottom-top-vertical_margin)
    width, height = min(default[0], aw), min(default[1], ah)
    x, y = left+8+(aw-width)//2, top+10+(ah-height)//2
    match = re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', str(saved or ''))
    if match:
        sw, sh, sx, sy = map(int, match.groups())
        width, height = max(min(640, aw), min(sw, aw)), max(min(420, ah), min(sh, ah))
        x, y = max(left+8,min(sx,right-width-20)), max(top+8,min(sy,top+ah-height+10))
    return width, height, x, y


def fit_window(window, saved=None, default=(1160, 790)):
    area = work_area(window)
    scale = float(window.tk.call('tk','scaling'))/(96/72)
    w, h, x, y = bounded_geometry(saved,area,default,vertical_margin=max(80,round(60*scale)))
    window.minsize(min(640, w), min(420, h))
    window.geometry(f'{w}x{h}{x:+d}{y:+d}')
    return w, h, x, y


class Flow(ttk.Frame):
    """Wrap controls by their requested widths instead of clipping a single row."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.items = []
        self.pending = None
        self.bind('<Configure>', self.schedule)
        self.bind('<Destroy>', self.dispose, add='+')

    def dispose(self,event):
        if event.widget is self and self.pending:
            try:
                self.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None

    def add(self, widget):
        self.items.append(widget)
        self.schedule()
        return widget

    def schedule(self, event=None):
        if self.pending is None:
            self.pending = self.after_idle(self.arrange)

    def arrange(self):
        self.pending = None
        width = max(100, self.winfo_width())
        x, y, row_height = 0, 3, 0
        for item in self.items:
            needed, height = min(item.winfo_reqwidth(), width-6), item.winfo_reqheight()
            if x and x+needed > width:
                x, y, row_height = 0, y+row_height+6, 0
            item.place(x=x, y=y, width=needed, height=height)
            x += needed+6
            row_height = max(row_height, height)
        self.configure(height=y+row_height+3)


class ScrollBody(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, background='#f0f0f0')
        self.scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scroll.grid(row=0, column=1, sticky='ns')
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        self.body = ttk.Frame(self.canvas, padding=6)
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.canvas.bind('<Configure>', self.resize)
        self.body.bind('<Configure>', self.update_region)
        self._top = self.winfo_toplevel()
        self._wheel_binding = self._top.bind('<MouseWheel>',self.wheel,add='+')
        self.bind('<Destroy>',self.dispose,add='+')

    def dispose(self,event):
        if event.widget is self:
            try:
                self._top.unbind('<MouseWheel>',self._wheel_binding)
            except tk.TclError:
                pass

    def resize(self, event=None):
        self.canvas.itemconfigure(self.item, width=max(1, self.canvas.winfo_width()),
                                  height=max(self.canvas.winfo_height(), self.body.winfo_reqheight()))
        self.update_region()

    def update_region(self, event=None):
        height = max(self.canvas.winfo_height(), self.body.winfo_reqheight())
        self.canvas.itemconfigure(self.item, height=height)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), height))

    def wheel(self, event):
        widget = event.widget
        if isinstance(widget, (ttk.Treeview, tk.Text, ttk.Combobox)):
            return
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(-int(event.delta/120), 'units')
                return
            widget = getattr(widget, 'master', None)


class TreeTooltip:
    def __init__(self, tree):
        self.tree, self.timer, self.popup, self.row = tree, None, None, None
        tree.bind('<Motion>', self.motion, add='+')
        tree.bind('<Leave>', self.hide, add='+')
        tree.bind('<ButtonPress>', self.hide, add='+')
        tree.bind('<Destroy>',self.hide,add='+')

    def hide(self, event=None):
        if self.timer:
            self.tree.after_cancel(self.timer); self.timer = None
        if self.popup:
            self.popup.destroy(); self.popup = None

    def motion(self, event):
        row = self.tree.identify_row(event.y)
        if row == self.row:
            return
        self.hide(); self.row = row
        if row:
            self.timer = self.tree.after(550, lambda: self.show(row))

    def show(self, row):
        self.timer = None
        if not self.tree.exists(row):
            return
        values = self.tree.item(row, 'values')
        popup = self.popup = tk.Toplevel(self.tree)
        popup.overrideredirect(True)
        tk.Label(popup, text='\n'.join(str(v) for v in values if str(v)), justify='left', wraplength=460,
                 background='#fffbe6', relief='solid', borderwidth=1, padx=8, pady=6).pack()
        popup.update_idletasks()
        left, top, right, bottom = work_area(popup)
        x = max(left, min(self.tree.winfo_pointerx()+12, right-popup.winfo_reqwidth()-8))
        y = max(top, min(self.tree.winfo_pointery()+16, bottom-popup.winfo_reqheight()-8))
        popup.geometry(f'{x:+d}{y:+d}')
