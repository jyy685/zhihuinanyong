import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

import requests
from .core import Client, Cancelled, LoginExpired, parse_cookies, check_cancel, friendly_error
from .help_ui import CookieGuide
from .cookies import extract_cookies
from .ui_support import Flow, ScrollBody, TreeTooltip, fit_window
from .updater import check_latest, RELEASES_URL

if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass

APP_NAME = '智慧南雍课件助手'
VERSION = '1.2.0'
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ZhihuiNanyong'


def resource(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / name


def size_text(size):
    if not size:
        return '未知'
    return f'{size / 1024 / 1024:.1f} MB' if size >= 1024 * 1024 else f'{size / 1024:.1f} KB'


class Application:
    def __init__(self, root, settings_dir=DATA_DIR, enable_updates=True):
        self.root, self.settings_dir = root, Path(settings_dir)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.busy = False
        self.connected = False
        self.closing = False
        self.raw_cookie = ''
        self.courses = []
        self.current = None
        self.selected = set()
        self.pending_courses = set()
        self.tasks = []
        self.cookie_visible = True
        self.settings = {}
        self.sort_state = {}
        self._save_timer = None
        self._cookie_timer = None
        self._normal_geometry = None
        self._pane_ratio = .27
        self.update_info = None
        self.update_checking = False
        self.update_manual_pending = False
        self.status = tk.StringVar(value='未连接：请粘贴 Cookie 后验证。')
        self.course_query = tk.StringVar()
        self.file_query = tk.StringVar()
        self.semester = tk.StringVar(value='全部学期')
        self.file_type = tk.StringVar(value='全部类型')
        self.only_selected = tk.BooleanVar()
        self.summary = tk.StringVar(value='已选 0 门课程 · 0 份课件')
        self.progress_text = tk.StringVar(value='就绪')
        self.folder = tk.StringVar(value=str(Path.home() / 'Downloads' / '智慧南雍课件'))
        try:
            settings = json.loads((self.settings_dir / 'settings.json').read_text(encoding='utf-8'))
            if isinstance(settings, dict):
                self.settings = settings
                if isinstance(settings.get('folder'), str):
                    self.folder.set(settings['folder'])
                self._pane_ratio = max(.18, min(.5, float(settings.get('pane_ratio', .27))))
        except (OSError, ValueError, TypeError):
            pass
        self.build()
        self.root.bind('<Configure>', self.window_changed, add='+')
        self.root.bind('<Destroy>',self.teardown,add='+')
        self.root.after(80, self.poll)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        if enable_updates:
            self.root.after(1800, self.check_updates)

    def build(self):
        r = self.root
        r.title(f'{APP_NAME} {VERSION}')
        w,h,x,y = fit_window(r,self.settings.get('geometry') if self.settings.get('remember_window',True) else None)
        self._normal_geometry = f'{w}x{h}{x:+d}{y:+d}'
        r.columnconfigure(0, weight=1)
        r.rowconfigure(2, weight=1)
        style = ttk.Style(r)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        font = tkfont.Font(family='Microsoft YaHei UI', size=9)
        style.configure('Treeview', rowheight=max(27, font.metrics('linespace')+8), font=('Microsoft YaHei UI', 9))
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 9))
        top = ttk.Frame(r, padding=(10, 6))
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(0, weight=1)
        self.app_title = ttk.Label(top, text=APP_NAME, font=('Microsoft YaHei UI', 13, 'bold'), wraplength=340)
        self.app_title.grid(row=0, column=0, sticky='w')
        self.update_dot = tk.Label(top, text='', fg='#dc2626', font=('Segoe UI', 12), width=1)
        self.update_dot.grid(row=0, column=1)
        self.update_button = ttk.Button(top, text='检查更新', command=self.manual_update)
        self.update_button.grid(row=0, column=2, padx=4)
        more = ttk.Menubutton(top, text='更多')
        menu = tk.Menu(more, tearoff=False)
        menu.add_command(label='连接设置', command=lambda: self.tabs.select(2))
        menu.add_command(label='Cookie 获取教程', command=self.help)
        menu.add_command(label='打开学校网站', command=lambda: webbrowser.open('https://lms.nju.edu.cn/user/courses#/'))
        menu.add_separator()
        menu.add_command(label='窗口设置', command=self.window_settings)
        menu.add_command(label='重置窗口布局', command=self.reset_layout)
        more.configure(menu=menu)
        more.grid(row=0, column=3)
        self.status_label = ttk.Label(r, textvariable=self.status, padding=(12, 3), wraplength=1000)
        self.status_label.grid(row=1, column=0, sticky='ew')
        self.tabs = ttk.Notebook(r)
        self.tabs.grid(row=2, column=0, sticky='nsew', padx=8, pady=4)
        pages = [ScrollBody(self.tabs) for _ in range(3)]
        for page, name in zip(pages, ('课程与课件', '下载任务', '连接设置')):
            self.tabs.add(page, text=name)
        self.pages = pages
        self.tabs.select(2)
        catalog, tasks, connection = (page.body for page in pages)
        connection.columnconfigure(0, weight=1)
        self.auth = ttk.LabelFrame(connection, text='Cookie 仅保存在本次运行内存中', padding=10)
        self.auth.grid(row=0, column=0, sticky='ew')
        self.cookie_hint = ttk.Label(self.auth, text='支持 Cookie 表格、请求头、JSON，或包含这些内容的整段页面文本；会自动提取登录项。', wraplength=900)
        self.cookie_hint.pack(anchor='w')
        self.cookie_text = tk.Text(self.auth, height=5, width=1, wrap='word', font=('Consolas', 10), undo=False)
        self.cookie_text.pack(fill='x', pady=6)
        self.cookie_text.bind('<<Modified>>', self.cookie_modified)
        self.cookie_info = tk.StringVar(value='等待粘贴。仅识别格式不代表登录有效，仍需服务器验证。')
        self.cookie_info_label = ttk.Label(self.auth, textvariable=self.cookie_info, wraplength=900)
        self.cookie_info_label.pack(fill='x', pady=4)
        auth_buttons = Flow(self.auth)
        auth_buttons.pack(fill='x')
        self.connect_button = auth_buttons.add(ttk.Button(auth_buttons, text='验证并探测全部课程', command=self.connect))
        self.import_button = auth_buttons.add(ttk.Button(auth_buttons, text='导入 Cookie 文件', command=self.import_cookie))
        self.clear_cookie_button = auth_buttons.add(ttk.Button(auth_buttons, text='清空 Cookie', command=self.clear_cookie))
        auth_buttons.add(ttk.Button(auth_buttons, text='显示 / 隐藏输入框', command=self.toggle_cookie))
        auth_buttons.add(ttk.Button(auth_buttons, text='图文获取教程', command=self.help))
        self.connection_tip = ttk.Label(connection,text='提示：F12 → 应用程序（或顶部 + / »）→ 存储 → Cookie → https://lms.nju.edu.cn。截图或被省略号截断的值不能还原。',wraplength=900)
        self.connection_tip.grid(row=1,column=0,sticky='ew',pady=10)
        self.auth.bind('<Configure>',lambda e:[label.configure(wraplength=max(180,e.width-28)) for label in (self.cookie_hint,self.cookie_info_label)])
        pages[2].canvas.bind('<Configure>',lambda e:self.connection_tip.configure(wraplength=max(180,e.width-20)),add='+')
        self.pane = ttk.Panedwindow(catalog, orient='horizontal')
        self.pane.pack(fill='both', expand=True)
        left, right = ttk.Frame(self.pane), ttk.Frame(self.pane)
        self.pane.add(left, weight=1); self.pane.add(right, weight=3)
        self.pane.bind('<Configure>', self.resize_pane)
        self.pane.bind('<ButtonRelease-1>', self.remember_pane)
        left.rowconfigure(3, weight=1); left.columnconfigure(0, weight=1)
        ttk.Label(left, text='搜索课程').grid(row=0, column=0, sticky='w')
        search = ttk.Frame(left); search.grid(row=1, column=0, sticky='ew', padx=(0,6), pady=3)
        search.columnconfigure(0, weight=1)
        ttk.Entry(search, textvariable=self.course_query, width=1).grid(row=0, column=0, sticky='ew')
        ttk.Button(search, text='×', width=2, command=lambda: self.course_query.set('')).grid(row=0, column=1)
        self.semester_box = ttk.Combobox(left, textvariable=self.semester, values=['全部学期'], state='readonly', width=1)
        self.semester_box.grid(row=2, column=0, sticky='ew', padx=(0,6), pady=3)
        course_frame = ttk.Frame(left); course_frame.grid(row=3, column=0, sticky='nsew')
        self.course_tree = self.tree(course_frame, ('name','count'), ('勾选 / 课程名称','课件状态'), (210,85))
        self.course_tree.bind('<Button-1>', self.click_course)
        self.course_tree.bind('<space>', self.space_course)
        self.course_tree.bind('<<TreeviewSelect>>', self.course_focus)
        self.retry_scan = ttk.Button(left, text='重新探测当前课程', command=self.rescan)
        self.retry_scan.grid(row=4, column=0, sticky='ew', padx=(0,6), pady=5)
        self.title = ttk.Label(right, text='请连接后选择课程', font=('Microsoft YaHei UI',10,'bold'), wraplength=600)
        self.title.pack(fill='x')
        self.file_search_hint = ttk.Label(right,text='搜索课件 · 点击表头排序，悬停或双击查看详情',wraplength=600)
        self.file_search_hint.pack(fill='x',pady=(4,0))
        search = ttk.Frame(right); search.pack(fill='x', pady=3); search.columnconfigure(0, weight=1)
        ttk.Entry(search, textvariable=self.file_query, width=1).grid(row=0, column=0, sticky='ew')
        ttk.Button(search, text='清除', command=lambda: self.file_query.set('')).grid(row=0, column=1, padx=4)
        filters = Flow(right); filters.pack(fill='x')
        filters.add(ttk.Combobox(filters, textvariable=self.file_type, width=11, state='readonly', values=['全部类型','PDF','PPT/PPTX','DOC/DOCX','ZIP/RAR','其他']))
        filters.add(ttk.Checkbutton(filters, text='只看已选', variable=self.only_selected, command=self.render_files))
        actions = Flow(right); actions.pack(fill='x')
        actions.add(ttk.Button(actions, text='全选当前结果', command=lambda: self.select_visible(True)))
        actions.add(ttk.Button(actions, text='清空当前结果', command=lambda: self.select_visible(False)))
        actions.add(ttk.Button(actions, text='清空全部选择', command=self.clear_selection))
        self.file_tree = self.tree(right, ('name','size','mode','activity'), ('勾选 / 课件名称','大小','下载方式','教学活动'), (300,85,125,180))
        self.file_tree.bind('<Button-1>', self.click_file)
        self.file_tree.bind('<space>', self.space_file)
        self.file_tree.bind('<Double-1>', self.file_details)
        self.empty_hint = ttk.Label(right,text='',wraplength=600)
        self.course_tree.heading('name', command=lambda: self.sort_by('course','name'))
        self.course_tree.heading('count', command=lambda: self.sort_by('course','count'))
        for column in ('name','size','mode','activity'):
            self.file_tree.heading(column, command=lambda c=column: self.sort_by('file',c))
        task_actions = Flow(tasks); task_actions.pack(fill='x', pady=(0,5))
        self.retry_button = task_actions.add(ttk.Button(task_actions, text='重试失败 / 未完成', command=self.retry_tasks))
        task_actions.add(ttk.Button(task_actions, text='打开下载文件夹', command=self.open_folder))
        self.task_tree = self.tree(tasks, ('name','course','state','progress','detail'), ('课件','课程','状态','进度','说明'), (260,180,100,80,300))
        self.task_tree.bind('<Double-1>', self.task_details)
        bottom = self.footer = ttk.Frame(r, padding=(10,5))
        bottom.grid(row=3, column=0, sticky='ew'); bottom.columnconfigure(0, weight=1)
        self.summary_label = ttk.Label(bottom, textvariable=self.summary, wraplength=1000)
        self.summary_label.grid(row=0, column=0, sticky='ew')
        path_row = ttk.Frame(bottom); path_row.grid(row=1, column=0, sticky='ew', pady=3); path_row.columnconfigure(1, weight=1)
        ttk.Label(path_row, text='保存到').grid(row=0, column=0, padx=(0,4))
        self.folder_entry = ttk.Entry(path_row, textvariable=self.folder, width=1)
        self.folder_entry.grid(row=0, column=1, sticky='ew')
        self.folder_button = ttk.Button(path_row, text='浏览…', command=self.choose_folder)
        self.folder_button.grid(row=0, column=2, padx=4)
        operations = ttk.Frame(bottom); operations.grid(row=2, column=0, sticky='ew'); operations.columnconfigure(0,weight=1)
        self.progress_bar = ttk.Progressbar(operations, maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky='ew', padx=(0,6))
        self.download_button = ttk.Button(operations, text='开始下载', command=self.download_selected)
        self.download_button.grid(row=0, column=1)
        self.stop_button = ttk.Button(operations, text='停止', command=self.stop)
        self.stop_button.grid(row=0, column=2, padx=(6,0))
        self.progress_label = ttk.Label(bottom, textvariable=self.progress_text, wraplength=1000)
        self.progress_label.grid(row=3, column=0, sticky='ew')
        r.bind('<Configure>', self.wrap_text, add='+')
        for var in (self.course_query,self.semester):
            var.trace_add('write', lambda *_: self.render_courses())
        for var in (self.file_query,self.file_type):
            var.trace_add('write', lambda *_: self.render_files())
        self.folder.trace_add('write', lambda *_: self.update_controls())
        self.update_controls()
        if self.settings.get('remember_window',True) and self.settings.get('maximized'):
            r.after_idle(lambda: r.state('zoomed'))

    def tree(self, parent, columns, headings, widths):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse', height=6)
        vs = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        hs = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0,column=0,sticky='nsew'); vs.grid(row=0,column=1,sticky='ns'); hs.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        for index,(col,title,width) in enumerate(zip(columns,headings,widths)):
            tree.heading(col,text=title)
            tree.column(col,width=width,minwidth=100 if index==0 else 60,stretch=index==0)
        tree.tooltip = TreeTooltip(tree)
        tree.heading_titles = dict(zip(columns,headings))
        return tree

    def wrap_text(self, event=None):
        if event and event.widget is not self.root:
            return
        width = max(200, self.root.winfo_width()-28)
        for label in (self.status_label,self.summary_label,self.progress_label):
            label.configure(wraplength=width)
        self.app_title.configure(wraplength=max(130,width-self.update_button.winfo_reqwidth()-120))

    def teardown(self,event):
        if event.widget is self.root:
            for token in self.root.tk.call('after','info'):
                try:
                    self.root.after_cancel(token)
                except tk.TclError:
                    pass

    def resize_pane(self, event=None):
        width = self.pane.winfo_width()
        if width > 350:
            self.pane.sashpos(0,max(130,min(width-220,int(width*self._pane_ratio))))
        self.title.configure(wraplength=max(180,int(width*(1-self._pane_ratio))-30))
        self.file_search_hint.configure(wraplength=max(180,int(width*(1-self._pane_ratio))-30))
        self.empty_hint.configure(wraplength=max(180,int(width*(1-self._pane_ratio))-30))

    def remember_pane(self, event=None):
        width = self.pane.winfo_width()
        if width > 1:
            self._pane_ratio = max(.18,min(.5,self.pane.sashpos(0)/width))
            self.save_settings()

    def window_changed(self, event):
        if event.widget is not self.root:
            return
        if self.root.state() == 'normal' and event.width > 100:
            self._normal_geometry = self.root.geometry()
        if self._save_timer:
            self.root.after_cancel(self._save_timer)
        self._save_timer = self.root.after(700,self.save_settings)

    def save_settings(self):
        self._save_timer = None
        settings = {'folder':self.folder.get(), 'remember_window':bool(self.settings.get('remember_window',True))}
        if settings['remember_window']:
            settings.update(geometry=self._normal_geometry or self.root.geometry(),
                            maximized=self.root.state()=='zoomed', pane_ratio=self._pane_ratio)
        self.settings = settings
        try:
            self.settings_dir.mkdir(parents=True,exist_ok=True)
            (self.settings_dir/'settings.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
        except OSError:
            pass

    def reset_layout(self):
        self.root.state('normal')
        self._pane_ratio = .27
        self._normal_geometry = None
        w,h,x,y = fit_window(self.root)
        self._normal_geometry = f'{w}x{h}{x:+d}{y:+d}'
        self.root.after_idle(self.resize_pane)
        self.save_settings()

    def window_settings(self):
        win = tk.Toplevel(self.root);win.title('窗口设置')
        fit_window(win,default=(700,480))
        win.columnconfigure(0,weight=1);win.rowconfigure(0,weight=1)
        body = ScrollBody(win);body.grid(row=0,column=0,sticky='nsew')
        remember = tk.BooleanVar(value=bool(self.settings.get('remember_window',True)))
        ttk.Label(body.body,text='窗口与布局',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',pady=10)
        ttk.Checkbutton(body.body,text='记住窗口布局（含位置和分栏）',variable=remember,
                        command=lambda:(self.settings.update(remember_window=remember.get()),self.save_settings())).pack(anchor='w',pady=8)
        label = ttk.Label(body.body,text='重启时会将窗口限制在当前屏幕可用区域内，避免恢复到屏幕外。窗口较小时，中间页面可滚动，底部操作栏保持可见。',wraplength=540)
        label.pack(fill='x',pady=10)
        body.canvas.bind('<Configure>',lambda e:label.configure(wraplength=max(200,e.width-30)),add='+')
        actions = Flow(win);actions.grid(row=1,column=0,sticky='ew',padx=10,pady=8)
        actions.add(ttk.Button(actions,text='恢复默认布局',command=self.reset_layout))
        actions.add(ttk.Button(actions,text='关闭',command=win.destroy))
        return win

    def cookie_modified(self,event=None):
        if not self.cookie_text.edit_modified():
            return
        self.cookie_text.edit_modified(False)
        if self._cookie_timer:
            self.root.after_cancel(self._cookie_timer)
        self._cookie_timer = self.root.after(400,self.preview_cookie)

    def preview_cookie(self):
        self._cookie_timer = None
        if self.busy:
            return
        try:
            result = extract_cookies(self.cookie_text.get('1.0','end'))
            self.cookie_info.set(result.summary)
        except ValueError as exc:
            self.cookie_info.set(str(exc))

    def sort_by(self,scope,column):
        previous = self.sort_state.get(scope)
        self.sort_state[scope] = (column,not previous[1] if previous and previous[0]==column else False)
        tree = self.course_tree if scope=='course' else self.file_tree
        for key,title in tree.heading_titles.items():
            suffix = (' ↓' if self.sort_state[scope][1] else ' ↑') if key==column else ''
            tree.heading(key,text=title+suffix)
        self.render_courses() if scope=='course' else self.render_files()

    @staticmethod
    def natural_key(value):
        return [(1,int(part)) if part.isdigit() else (0,part.casefold()) for part in re.split(r'(\d+)',str(value))]

    def details(self,title,text):
        win = tk.Toplevel(self.root);win.title(title)
        fit_window(win,default=(760,520));win.columnconfigure(0,weight=1);win.rowconfigure(0,weight=1)
        field = tk.Text(win,wrap='word',padx=12,pady=12,font=('Microsoft YaHei UI',10),width=1,height=1)
        scroll = ttk.Scrollbar(win,command=field.yview);field.configure(yscrollcommand=scroll.set)
        field.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
        field.insert('1.0',text);field.configure(state='disabled')
        actions = Flow(win);actions.grid(row=1,column=0,columnspan=2,sticky='ew',padx=10,pady=8)
        actions.add(ttk.Button(actions,text='复制详情',command=lambda:(win.clipboard_clear(),win.clipboard_append(text))))
        actions.add(ttk.Button(actions,text='关闭',command=win.destroy))
        return win

    def file_details(self,event=None):
        if event and not self.file_tree.identify_row(event.y):
            return
        selected = self.file_tree.selection()
        c = self.course()
        if not selected or not c:
            return
        u = next(u for u in c['_files'] if str(u['id'])==selected[0])
        return self.details('课件详情',f"课程：{c['name']}\n文件：{u['name']}\n大小：{size_text(u.get('size'))}\n教学活动：{u.get('activity_title','')}\n目标目录：{Path(self.folder.get())/str(c['id'])}")

    def task_details(self,event=None):
        if event and not self.task_tree.identify_row(event.y):
            return
        selected = self.task_tree.selection()
        if selected:
            t = self.tasks[int(selected[0])]
            return self.details('任务详情',f"{t['upload']['name']}\n课程：{t['course']}\n状态：{t['state']}\n{t['detail']}")

    def toggle_cookie(self):
        if self.cookie_visible:
            self.cookie_text.pack_forget()
        else:
            self.cookie_text.pack(fill='x', pady=6, after=self.cookie_hint)
        self.cookie_visible = not self.cookie_visible

    def import_cookie(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title='导入 Cookie', filetypes=[('Cookie 文件', '*.txt *.json'), ('全部文件', '*.*')])
        if path:
            try:
                raw = Path(path).read_text(encoding='utf-8-sig')
                self.cookie_text.delete('1.0', 'end')
                self.cookie_text.insert('1.0', raw)
                if not self.cookie_visible:
                    self.toggle_cookie()
            except (OSError, UnicodeError):
                messagebox.showerror('无法导入', '请选择 UTF-8 格式的 Cookie 文本文件。')

    def clear_cookie(self):
        if self.busy:
            return
        self.cookie_text.delete('1.0', 'end')
        self.raw_cookie = ''
        self.cookie_info.set('Cookie 已清空，请重新粘贴。')
        self.connected = False
        self.status.set('Cookie 已清空，请重新验证。')
        self.update_controls()

    def help(self):
        return CookieGuide(self.root, resource('docs/images'), self.focus_cookie)

    def focus_cookie(self):
        self.root.lift()
        self.tabs.select(2)
        if not self.cookie_visible:
            self.toggle_cookie()
        self.cookie_text.focus_set()

    def manual_update(self):
        if self.update_info and self.update_info.get('state') == 'available' and not self.update_checking:
            self.show_update()
        else:
            self.check_updates(manual=True)

    def check_updates(self, manual=False):
        self.update_manual_pending = self.update_manual_pending or manual
        if self.update_checking:
            return
        self.update_checking = True
        # Independent from the course/download worker. No LMS cookies are shared.
        self.update_button.configure(text='检查更新中…')

        def worker():
            try:
                result = check_latest(VERSION)
            except Exception:
                result = {'state': 'error', 'message': '暂时无法检查更新，请稍后重试。'}
            self.events.put(('update', result))
        threading.Thread(target=worker, daemon=True).start()

    def show_update(self):
        info = self.update_info
        if not info or info.get('state') != 'available':
            return
        text = f"新版本 {info['version']} 已发布\n当前版本 {VERSION}\n\n{info.get('notes','暂无说明。')}\n\n下载后退出旧版，再运行新版 EXE。"
        win = self.details('发现新版本',text)
        actions = next(w for w in win.winfo_children() if isinstance(w,Flow))
        actions.add(ttk.Button(actions,text='查看发布页面',command=lambda:webbrowser.open(info['url'])))
        if info.get('download_url'):
            actions.add(ttk.Button(actions,text='下载新版 EXE',command=lambda:webbrowser.open(info['download_url'])))
        actions.add(ttk.Button(actions,text='重新检查',command=lambda:(win.destroy(),self.check_updates(manual=True))))
        return win

    @staticmethod
    def can_select(u):
        return bool(u.get('allow_download') or u['name'].lower().endswith('.pdf'))

    def key(self, course, upload):
        return (int(course['id']), int(upload['id']))

    def course(self):
        return next((c for c in self.courses if str(c['id']) == str(self.current)), None)

    def render_courses(self):
        for item in self.course_tree.get_children():
            self.course_tree.delete(item)
        courses = self.courses
        if 'course' in self.sort_state:
            column,descending = self.sort_state['course']
            courses = sorted(courses,key=lambda c:self.natural_key(c['name']) if column=='name' else len(c['_files']),reverse=descending)
        visible = []
        for c in courses:
            if self.course_query.get().lower() not in c['name'].lower():
                continue
            if self.semester.get() != '全部学期' and c['_semester'] != self.semester.get():
                continue
            visible.append(c['id'])
            eligible = [u for u in c['_files'] if self.can_select(u)]
            n = sum(self.key(c, u) in self.selected for u in eligible)
            box = '☑' if eligible and n == len(eligible) else ('◩' if n else '☐')
            if c['id'] in self.pending_courses:
                box = '☑'
            self.course_tree.insert('', 'end', iid=str(c['id']), values=(f"{box} {c['name']}", c['_state']))
        changed = self.current not in visible
        if changed:
            self.current = visible[0] if visible else None
        if self.current and self.course_tree.exists(str(self.current)):
            self.course_tree.selection_set(str(self.current))
        if changed:
            self.render_files()
        self.update_summary()

    def visible_files(self):
        c = self.course()
        if not c:
            return []
        result = []
        types = {'PDF': {'.pdf'}, 'PPT/PPTX': {'.ppt', '.pptx'}, 'DOC/DOCX': {'.doc', '.docx'}, 'ZIP/RAR': {'.zip', '.rar'}}
        for u in c['_files']:
            ext = Path(u['name']).suffix.lower()
            kind = self.file_type.get()
            if self.file_query.get().lower() not in u['name'].lower():
                continue
            if kind in types and ext not in types[kind]:
                continue
            if kind == '其他' and ext in set().union(*types.values()):
                continue
            if self.only_selected.get() and self.key(c, u) not in self.selected:
                continue
            result.append(u)
        if 'file' in self.sort_state:
            column,descending = self.sort_state['file']
            def value(u):
                if column=='size':
                    return u.get('size') or 0
                field = u['name'] if column=='name' else u.get('activity_title','') if column=='activity' else ('原件' if u.get('allow_download') else '预览 PDF')
                return self.natural_key(field)
            result.sort(key=value,reverse=descending)
        return result

    def render_files(self):
        self.file_tree.delete(*self.file_tree.get_children())
        c = self.course()
        count = sum(self.key(c,u) in self.selected for u in c['_files']) if c else 0
        self.title.configure(text=f"{c['name']} · 已选 {count}/{len(c['_files'])}" if c else '选择课程查看课件')
        if c:
            for u in self.visible_files():
                selectable = self.can_select(u)
                box = ('☑' if self.key(c, u) in self.selected else '☐') if selectable else '—'
                mode = '原件' if u.get('allow_download') else ('尝试预览 PDF' if selectable else '暂不可下载')
                self.file_tree.insert('', 'end', iid=str(u['id']), values=(f"{box} {u['name']}", size_text(u.get('size')), mode, u.get('activity_title', '')))
        message = ''
        if c and not c['_files']:
            message = '此课程尚未探测或探测失败，可点击重新探测。' if c['_state']!='无附件' else '此课程没有附件课件。'
        elif c and not self.visible_files():
            message = '没有匹配课件，请清除关键词或调整筛选条件。'
        self.empty_hint.configure(text=message)
        if message:
            self.empty_hint.pack(fill='x',pady=3)
        else:
            self.empty_hint.pack_forget()
        self.update_summary()

    def course_focus(self, event=None):
        selection = self.course_tree.selection()
        if selection and str(self.current) != selection[0]:
            self.current = int(selection[0])
            self.render_files()

    def toggle_course(self, cid):
        c = next(c for c in self.courses if str(c['id']) == cid)
        eligible = [u for u in c['_files'] if self.can_select(u)]
        if c['_state'] in ('未探测', '探测中'):
            if c['id'] in self.pending_courses:
                self.pending_courses.remove(c['id'])
            else:
                self.pending_courses.add(c['id'])
        elif eligible:
            all_selected = all(self.key(c, u) in self.selected for u in eligible)
            for u in eligible:
                self.selected.discard(self.key(c, u)) if all_selected else self.selected.add(self.key(c, u))
        self.render_courses()
        self.render_files()

    def click_course(self, event):
        row = self.course_tree.identify_row(event.y)
        if not row:
            return
        self.current = int(row)
        if self.course_tree.identify_column(event.x) == '#1' and event.x < 34 and self.course_tree.xview()[0]==0:
            self.toggle_course(row)
        self.render_files()

    def space_course(self, event):
        rows = self.course_tree.selection()
        if rows:
            self.toggle_course(rows[0])
        return 'break'

    def toggle_file(self, uid):
        c = self.course()
        if not c:
            return
        u = next((u for u in c['_files'] if str(u['id']) == uid), None)
        if u and self.can_select(u):
            key = self.key(c, u)
            self.selected.remove(key) if key in self.selected else self.selected.add(key)
            self.render_courses()
            self.render_files()

    def click_file(self, event):
        row = self.file_tree.identify_row(event.y)
        if row and self.file_tree.identify_column(event.x) == '#1' and event.x < 34 and self.file_tree.xview()[0]==0:
            self.toggle_file(row)

    def space_file(self, event):
        rows = self.file_tree.selection()
        if rows:
            self.toggle_file(rows[0])
        return 'break'

    def select_visible(self, checked):
        c = self.course()
        if c:
            for u in self.visible_files():
                if self.can_select(u):
                    self.selected.add(self.key(c, u)) if checked else self.selected.discard(self.key(c, u))
        self.render_courses()
        self.render_files()

    def clear_selection(self):
        self.selected.clear()
        self.pending_courses.clear()
        self.render_courses()
        self.render_files()

    def update_summary(self):
        selected_files = [(c, u) for c in self.courses for u in c['_files'] if self.key(c, u) in self.selected]
        size = sum(u.get('size') or 0 for _, u in selected_files)
        self.summary.set(f'已选 {len({c["id"] for c, _ in selected_files})} 门课程 · {len(selected_files)} 份课件 · 已知大小 {size_text(size) if size else '0 KB'}（含被筛选隐藏的文件）')
        self.update_controls()

    def update_controls(self):
        if not hasattr(self, 'download_button'):
            return
        for button in (self.connect_button, self.import_button, self.clear_cookie_button, self.folder_button):
            button.configure(state='disabled' if self.busy else 'normal')
        self.folder_entry.configure(state='disabled' if self.busy else 'normal')
        self.cookie_text.configure(state='disabled' if self.busy else 'normal')
        self.stop_button.configure(state='normal' if self.busy and not self.stop_event.is_set() else 'disabled')
        self.download_button.configure(state='normal' if self.connected and self.selected and not self.busy and self.folder.get().strip() else 'disabled')
        self.retry_scan.configure(state='normal' if self.connected and self.current and not self.busy else 'disabled')
        retry = any(t.get('available',True) and t['state'] in ('失败', '已取消', '等待中', '需重新登录') for t in self.tasks)
        self.retry_button.configure(state='normal' if self.connected and not self.busy and retry else 'disabled')

    def start(self, work):
        self.busy = True
        self.stop_event = threading.Event()
        self.update_controls()

        def wrapper():
            try:
                work()
            except Cancelled:
                self.events.put(('notice', '操作已停止，已保留探测结果和完成文件。'))
            except Exception as exc:
                self.events.put(('error', friendly_error(exc), isinstance(exc, LoginExpired)))
            finally:
                self.events.put(('idle',))
        self.thread = threading.Thread(target=wrapper, daemon=True)
        self.thread.start()

    def connect(self):
        if self.busy:
            return
        raw = self.cookie_text.get('1.0', 'end').strip()
        try:
            result = extract_cookies(raw)
            raw = result.normalized()
            self.cookie_info.set(result.summary)
        except ValueError as exc:
            self.cookie_info.set(str(exc))
            messagebox.showerror('Cookie 无效', str(exc))
            return
        # Revalidating an expired Cookie preserves pending tasks. Once the new
        # catalog arrives, discard tasks from courses this session cannot access.
        self.raw_cookie = raw
        self.cookie_text.delete('1.0','end')
        self.cookie_text.insert('1.0',raw)
        self.connected = False
        self.courses = []
        self.current = None
        self.clear_selection()
        self.status.set('正在验证并读取全部课程……')
        if self.cookie_visible:
            self.toggle_cookie()
        self.start(lambda: self.scan(raw))

    def scan(self, raw, single_id=None):
        client = Client(raw, self.stop_event)
        try:
            courses = client.courses() if single_id is None else [{'id': single_id}]
            if single_id is None:
                self.events.put(('courses', courses))
            for i, c in enumerate(courses, 1):
                check_cancel(self.stop_event)
                self.events.put(('scan_state', c['id'], '探测中', f'正在探测课程 {i}/{len(courses)}'))
                try:
                    files = client.files(c['id'])
                    self.events.put(('files', c['id'], files))
                except (Cancelled, LoginExpired):
                    raise
                except Exception as exc:
                    self.events.put(('scan_state', c['id'], '探测失败', friendly_error(exc)))
            self.events.put(('notice', f'探测完成：{len(courses)} 门课程。可勾选课件并开始下载。'))
        finally:
            client.close()

    def rescan(self):
        if self.busy or not self.current:
            return
        cid = int(self.current)
        self.start(lambda: self.scan(self.raw_cookie, cid))

    def choose_folder(self):
        path = filedialog.askdirectory(initialdir=self.folder.get() if Path(self.folder.get()).exists() else str(Path.home()))
        if path:
            self.folder.set(path)

    def open_folder(self):
        folder = Path(self.folder.get()).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError:
            messagebox.showerror('无法打开', '请检查下载目录是否可用。')

    def prepare_directory(self):
        import tempfile
        folder = Path(self.folder.get()).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as f:
            f.write(b'test')
        self.folder.set(str(folder))
        self.save_settings()
        return folder

    def download_selected(self):
        if self.busy or not self.connected:
            return
        plan = [(c, dict(u)) for c in self.courses for u in c['_files'] if self.key(c, u) in self.selected]
        self.tasks = [dict(course=c['name'], course_id=c['id'], upload=u, state='等待中', progress='', detail='', folder='') for c, u in plan]
        self.launch_download()

    def launch_download(self):
        try:
            folder = self.prepare_directory()
        except OSError:
            messagebox.showerror('目录不可用', '无法写入目录或保存设置，请选择其他文件夹。')
            return
        todo = []
        for i, task in enumerate(self.tasks):
            if task.get('available',True) and task['state'] in ('失败', '已取消', '等待中', '需重新登录'):
                task.update(state='等待中', progress='', detail='')
                task['folder'] = task['folder'] or str(folder / str(task['course_id']))
                todo.append(i)
        if not todo:
            return
        self.tabs.select(1)
        self.render_tasks()
        raw = self.raw_cookie
        self.start(lambda: self.run_download(raw, todo))

    def retry_tasks(self):
        if not self.busy and self.connected:
            self.launch_download()

    def run_download(self, raw, todo):
        client = Client(raw, self.stop_event)
        try:
            for position, index in enumerate(todo):
                check_cancel(self.stop_event)
                task = self.tasks[index]
                self.events.put(('task', index, '解析地址', '', ''))
                last = [0.0]

                def progress(done, total):
                    now = time.monotonic()
                    if now - last[0] < .12 and done != total:
                        return
                    last[0] = now
                    text = f'{done * 100 / total:.0f}%' if total else size_text(done)
                    self.events.put(('task', index, '下载中', text, f'{size_text(done)} / {size_text(total)}'))
                try:
                    for attempt in range(3):
                        try:
                            state, path = client.download(task['upload'], task['folder'], progress)
                            self.events.put(('task', index, state, '100%', str(path)))
                            break
                        except (requests.Timeout, requests.ConnectionError):
                            if attempt == 2:
                                raise
                            self.events.put(('task', index, '重试中', '', f'网络重试 {attempt + 1}/2'))
                            if self.stop_event.wait(2 * (attempt + 1)):
                                raise Cancelled()
                except LoginExpired:
                    self.events.put(('task', index, '需重新登录', '', '更新 Cookie 并验证后，可重试未完成任务。'))
                    raise
                except Cancelled:
                    self.events.put(('task', index, '已取消', '', '停止时清理本次临时文件。'))
                    raise
                except Exception as exc:
                    self.events.put(('task', index, '失败', '', friendly_error(exc)))
                self.events.put(('overall', (position + 1) * 100 / len(todo)))
            self.events.put(('notice', '下载处理完成。详情见任务列表；失败项可以重试。'))
        finally:
            client.close()

    def render_tasks(self):
        self.task_tree.delete(*self.task_tree.get_children())
        for i, t in enumerate(self.tasks):
            self.task_tree.insert('', 'end', iid=str(i), values=(t['upload']['name'], t['course'], t['state'], t['progress'], t['detail']))
        if self.tasks:
            success = sum(t['state'] == '已完成' for t in self.tasks)
            skip = sum(t['state'] == '已跳过' for t in self.tasks)
            fail = sum(t['state'] in ('失败', '需重新登录') for t in self.tasks)
            self.progress_text.set(f'共 {len(self.tasks)} 份 · 完成 {success} · 已跳过 {skip} · 失败/需登录 {fail}')
        self.update_controls()

    def stop(self):
        self.stop_event.set()
        self.status.set('正在停止……等待当前网络请求结束，已完成的文件会保留。')
        self.stop_button.configure(state='disabled')

    def poll(self):
        for _ in range(150):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind, *data = event
            if kind == 'update':
                result = data[0]
                self.update_checking = False
                manual = self.update_manual_pending
                self.update_manual_pending = False
                # Retain a known update marker after a transient network failure.
                if result['state'] != 'error':
                    self.update_info = result
                available = self.update_info and self.update_info.get('state') == 'available'
                self.update_dot.configure(text='●' if available else '')
                self.update_button.configure(text='有更新 · 点击查看' if available else '检查更新')
                if manual:
                    if result['state'] == 'available':
                        self.show_update()
                    elif result['state'] == 'error':
                        messagebox.showwarning('检查更新', result['message'])
                    else:
                        messagebox.showinfo('检查更新', result['message'])
            elif kind == 'courses':
                self.connected = True
                self.courses = []
                accessible = {c['id'] for c in data[0]}
                self.tasks = [t for t in self.tasks if t['course_id'] in accessible]
                self.render_tasks()
                for c in data[0]:
                    semester = c.get('semester') or {}
                    c.update(_files=[], _state='未探测', _semester=semester.get('name') or semester.get('code') or '未标注学期')
                    self.courses.append(c)
                self.semester_box.configure(values=['全部学期'] + sorted({c['_semester'] for c in self.courses}, reverse=True))
                self.semester.set('全部学期')
                self.current = self.courses[0]['id'] if self.courses else None
                self.render_courses()
                self.render_files()
                self.tabs.select(0)
                self.status.set(f'已验证，发现 {len(self.courses)} 门课程。连接设置已收起，可从标签页修改。')
            elif kind == 'files':
                cid, files = data
                c = next(c for c in self.courses if c['id'] == cid)
                keys = {self.key(c, u) for u in files}
                self.selected = {k for k in self.selected if k[0] != cid or k in keys}
                c.update(_files=files, _state=f'{len(files)} 份' if files else '无附件')
                by_id = {u['id']:u for u in files}
                for task in self.tasks:
                    if task['course_id']==cid and task['state'] not in ('已完成','已跳过'):
                        task['available'] = task['upload']['id'] in by_id
                        if task['available']:
                            task['upload'] = dict(by_id[task['upload']['id']])
                        else:
                            task.update(state='失败',detail='此课件已移除或当前账号不可访问。')
                if cid in self.pending_courses:
                    self.selected.update(self.key(c, u) for u in files if self.can_select(u))
                    self.pending_courses.discard(cid)
                self.render_courses()
                self.render_files()
            elif kind == 'scan_state':
                cid, state, msg = data
                c = next(c for c in self.courses if c['id'] == cid)
                c['_state'] = state
                self.status.set(msg)
                self.render_courses()
            elif kind == 'notice':
                self.status.set(data[0])
            elif kind == 'error':
                self.status.set(data[0])
                if data[1]:
                    self.connected = False
                messagebox.showerror('操作未完成', data[0])
            elif kind == 'task':
                index, state, progress, detail = data
                self.tasks[index].update(state=state, progress=progress, detail=detail)
                t = self.tasks[index]
                self.task_tree.item(str(index), values=(t['upload']['name'], t['course'], state, progress, detail))
            elif kind == 'overall':
                self.progress_bar['value'] = data[0]
            elif kind == 'idle':
                self.busy = False
                for c in self.courses:
                    if c['_state'] == '探测中':
                        c['_state'] = '未探测'
                for t in self.tasks:
                    if t['state'] in ('等待中', '解析地址', '下载中', '重试中'):
                        t['state'] = '已取消'
                self.pending_courses.clear()
                self.render_courses()
                self.render_tasks()
                self.write_report()
        self.update_controls()
        if self.closing and not self.busy:
            self.save_settings()
            self.root.destroy()
            return
        self.root.after(80, self.poll)

    def write_report(self):
        if not self.tasks:
            return
        try:
            self.settings_dir.mkdir(parents=True, exist_ok=True)
            report = [{'course_id': t['course_id'], 'file_id': t['upload']['id'], 'name': t['upload']['name'], 'state': t['state'], 'detail': t['detail']} for t in self.tasks]
            (self.settings_dir / 'last_download.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            self.status.set('任务已结束，但无法保存本机任务记录。')

    def close(self):
        if self.busy:
            if messagebox.askyesno('正在工作', '停止当前操作并退出？将保留已完成的文件。'):
                self.closing = True
                self.stop()
        else:
            self.save_settings()
            self.root.destroy()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()
