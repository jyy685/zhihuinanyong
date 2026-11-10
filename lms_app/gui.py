import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

import requests
from .core import Client, Cancelled, LoginExpired, parse_cookies, check_cancel, friendly_error

if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass

APP_NAME = '智慧南雍课件助手'
VERSION = '1.0.0'
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ZhihuiNanyong'


def resource(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / name


def size_text(size):
    if not size:
        return '未知'
    return f'{size / 1024 / 1024:.1f} MB' if size >= 1024 * 1024 else f'{size / 1024:.1f} KB'


class Application:
    def __init__(self, root, settings_dir=DATA_DIR):
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
            self.folder.set(settings.get('folder') or self.folder.get())
        except (OSError, ValueError, TypeError):
            pass
        self.build()
        self.root.after(80, self.poll)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def build(self):
        r = self.root
        r.title(f'{APP_NAME} {VERSION}')
        r.geometry('1250x850')
        r.minsize(930, 680)
        style = ttk.Style(r)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Treeview', rowheight=31, font=('Microsoft YaHei UI', 10))
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10))
        top = ttk.Frame(r, padding=(16, 10))
        top.pack(fill='x')
        ttk.Label(top, text=APP_NAME, font=('Microsoft YaHei UI', 18, 'bold')).pack(side='left')
        ttk.Button(top, text='Cookie 获取帮助', command=self.help).pack(side='right')
        ttk.Button(top, text='打开学校网站', command=lambda: webbrowser.open('https://lms.nju.edu.cn/user/courses#/')).pack(side='right', padx=8)
        self.auth = ttk.LabelFrame(r, text='连接设置 · Cookie 仅保存在本次运行内存中', padding=10)
        self.auth.pack(fill='x', padx=16, pady=(0, 8))
        self.cookie_hint = ttk.Label(self.auth, text='F12 → 应用程序（找不到时点 » 或 更多工具）→ 存储 → Cookie → 学校域名；复制表格后粘贴。')
        self.cookie_hint.pack(anchor='w')
        self.cookie_text = tk.Text(self.auth, height=3, wrap='none', font=('Consolas', 10), undo=False)
        self.cookie_text.pack(fill='x', pady=6)
        auth_buttons = ttk.Frame(self.auth)
        auth_buttons.pack(fill='x')
        self.connect_button = ttk.Button(auth_buttons, text='验证并探测全部课程', command=self.connect)
        self.connect_button.pack(side='left')
        self.import_button = ttk.Button(auth_buttons, text='导入 Cookie 文件', command=self.import_cookie)
        self.import_button.pack(side='left', padx=6)
        self.clear_cookie_button = ttk.Button(auth_buttons, text='清空 Cookie', command=self.clear_cookie)
        self.clear_cookie_button.pack(side='left')
        ttk.Button(auth_buttons, text='显示 / 隐藏输入框', command=self.toggle_cookie).pack(side='right')
        ttk.Label(r, textvariable=self.status, padding=(18, 3)).pack(fill='x')
        self.tabs = ttk.Notebook(r)
        self.tabs.pack(fill='both', expand=True, padx=16, pady=6)
        catalog = ttk.Frame(self.tabs, padding=8)
        tasks = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(catalog, text='课程与课件')
        self.tabs.add(tasks, text='下载任务')
        pane = ttk.Panedwindow(catalog, orient='horizontal')
        pane.pack(fill='both', expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        ttk.Entry(left, textvariable=self.course_query).pack(fill='x', padx=(0, 8), pady=(0, 6))
        self.semester_box = ttk.Combobox(left, textvariable=self.semester, values=['全部学期'], state='readonly')
        self.semester_box.pack(fill='x', padx=(0, 8), pady=(0, 6))
        self.course_tree = self.tree(left, ('name', 'count'), ('勾选 / 课程名称', '课件状态'), (230, 90))
        self.course_tree.bind('<Button-1>', self.click_course)
        self.course_tree.bind('<space>', self.space_course)
        self.course_tree.bind('<<TreeviewSelect>>', self.course_focus)
        self.retry_scan = ttk.Button(left, text='重新探测当前课程', command=self.rescan)
        self.retry_scan.pack(fill='x', padx=(0, 8), pady=6)
        self.title = ttk.Label(right, text='请连接后选择课程', font=('Microsoft YaHei UI', 12, 'bold'))
        self.title.pack(anchor='w')
        filters = ttk.Frame(right)
        filters.pack(fill='x', pady=6)
        ttk.Entry(filters, textvariable=self.file_query, width=24).pack(side='left', fill='x', expand=True)
        ttk.Combobox(filters, textvariable=self.file_type, width=12, state='readonly', values=['全部类型', 'PDF', 'PPT/PPTX', 'DOC/DOCX', 'ZIP/RAR', '其他']).pack(side='left', padx=6)
        ttk.Checkbutton(filters, text='只看已选', variable=self.only_selected, command=self.render_files).pack(side='left')
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=(0, 6))
        ttk.Button(actions, text='全选当前结果', command=lambda: self.select_visible(True)).pack(side='left')
        ttk.Button(actions, text='清空当前结果', command=lambda: self.select_visible(False)).pack(side='left', padx=6)
        ttk.Button(actions, text='清空全部选择', command=self.clear_selection).pack(side='right')
        self.file_tree = self.tree(right, ('name', 'size', 'mode', 'activity'), ('勾选 / 课件名称', '大小', '下载方式', '教学活动'), (340, 85, 135, 220))
        self.file_tree.bind('<Button-1>', self.click_file)
        self.file_tree.bind('<space>', self.space_file)
        ttk.Label(right, text='点击课程查看；点击首列复选框勾选。空格可切换选择。暂不可下载的附件仍会列出。', foreground='#64748b').pack(anchor='w', pady=5)
        task_actions = ttk.Frame(tasks)
        task_actions.pack(fill='x', pady=(0, 8))
        self.retry_button = ttk.Button(task_actions, text='重试失败 / 未完成', command=self.retry_tasks)
        self.retry_button.pack(side='left')
        ttk.Button(task_actions, text='打开下载文件夹', command=self.open_folder).pack(side='left', padx=6)
        self.task_tree = self.tree(tasks, ('name', 'course', 'state', 'progress', 'detail'), ('课件', '课程', '状态', '进度', '说明'), (290, 190, 110, 100, 350))
        bottom = ttk.Frame(r, padding=(16, 6))
        bottom.pack(fill='x')
        ttk.Label(bottom, textvariable=self.summary).pack(anchor='w')
        path_row = ttk.Frame(bottom)
        path_row.pack(fill='x', pady=6)
        ttk.Label(path_row, text='保存到：').pack(side='left')
        self.folder_entry = ttk.Entry(path_row, textvariable=self.folder)
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.folder_button = ttk.Button(path_row, text='浏览…', command=self.choose_folder)
        self.folder_button.pack(side='left', padx=6)
        self.download_button = ttk.Button(path_row, text='下载已勾选课件', command=self.download_selected)
        self.download_button.pack(side='left')
        self.stop_button = ttk.Button(path_row, text='停止', command=self.stop)
        self.stop_button.pack(side='left', padx=(6, 0))
        ttk.Label(bottom, text='文件按课程 ID 建子文件夹；完整文件跳过，同名或不完整文件会提示。', foreground='#64748b').pack(anchor='w')
        self.progress_bar = ttk.Progressbar(bottom, maximum=100)
        self.progress_bar.pack(fill='x', pady=(6, 0))
        ttk.Label(bottom, textvariable=self.progress_text).pack(anchor='w')
        for var in (self.course_query, self.semester):
            var.trace_add('write', lambda *_: self.render_courses())
        for var in (self.file_query, self.file_type):
            var.trace_add('write', lambda *_: self.render_files())
        self.folder.trace_add('write', lambda *_: self.update_controls())
        self.update_controls()

    def tree(self, parent, columns, headings, widths):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        vs = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        hs = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for col, title, width in zip(columns, headings, widths):
            tree.heading(col, text=title)
            tree.column(col, width=width, minwidth=60, stretch=False)
        return tree

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
        self.connected = False
        self.status.set('Cookie 已清空，请重新验证。')
        self.update_controls()

    def help(self):
        win = tk.Toplevel(self.root)
        win.title('如何找到应用程序并复制 Cookie')
        win.geometry('800x650')
        text = tk.Text(win, wrap='word', padx=18, pady=14, font=('Microsoft YaHei UI', 11))
        scroll = ttk.Scrollbar(win, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        try:
            guide = resource('docs/COOKIE_GUIDE.md').read_text(encoding='utf-8-sig')
        except OSError:
            guide = 'F12 → 应用程序（或 » / 更多工具）→ 存储 → Cookie → https://lms.nju.edu.cn\n复制表格，粘贴后验证。'
        guide = guide.replace('**', '').replace('```text', '').replace('```', '')
        guide = re.sub(r'^#+ ', '', guide, flags=re.M)
        guide = guide.replace('交互设计原型不处理真实登录，请勿向原型粘贴真实 Cookie。', '')
        text.insert('1.0', guide)
        text.configure(state='disabled')

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
        for c in self.courses:
            if self.course_query.get().lower() not in c['name'].lower():
                continue
            if self.semester.get() != '全部学期' and c['_semester'] != self.semester.get():
                continue
            eligible = [u for u in c['_files'] if self.can_select(u)]
            n = sum(self.key(c, u) in self.selected for u in eligible)
            box = '☑' if eligible and n == len(eligible) else ('◩' if n else '☐')
            if c['id'] in self.pending_courses:
                box = '☑'
            self.course_tree.insert('', 'end', iid=str(c['id']), values=(f"{box} {c['name']}", c['_state']))
        if self.current and self.course_tree.exists(str(self.current)):
            self.course_tree.selection_set(str(self.current))
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
        return result

    def render_files(self):
        self.file_tree.delete(*self.file_tree.get_children())
        c = self.course()
        self.title.configure(text=c['name'] if c else '选择课程查看课件')
        if c:
            for u in self.visible_files():
                selectable = self.can_select(u)
                box = ('☑' if self.key(c, u) in self.selected else '☐') if selectable else '—'
                mode = '原件' if u.get('allow_download') else ('尝试预览 PDF' if selectable else '暂不可下载')
                self.file_tree.insert('', 'end', iid=str(u['id']), values=(f"{box} {u['name']}", size_text(u.get('size')), mode, u.get('activity_title', '')))
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
        if self.course_tree.identify_column(event.x) == '#1' and event.x < 34:
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
        if row and self.file_tree.identify_column(event.x) == '#1' and event.x < 34:
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
        self.summary.set(f'已选 {len({c["id"] for c, _ in selected_files})} 门课程 · {len(selected_files)} 份课件 · 已知大小 {size_text(size)}（含被筛选隐藏的文件）')
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
        retry = any(t['state'] in ('失败', '已取消', '等待中', '需重新登录') for t in self.tasks)
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
            parse_cookies(raw)
        except ValueError as exc:
            messagebox.showerror('Cookie 无效', str(exc))
            return
        # Revalidating an expired Cookie preserves pending tasks. Once the new
        # catalog arrives, discard tasks from courses this session cannot access.
        self.raw_cookie = raw
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
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        (self.settings_dir / 'settings.json').write_text(json.dumps({'folder': str(folder)}, ensure_ascii=False), encoding='utf-8')
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
            if task['state'] in ('失败', '已取消', '等待中', '需重新登录'):
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
            if kind == 'courses':
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
                self.status.set(f'已验证，发现 {len(self.courses)} 门课程。')
            elif kind == 'files':
                cid, files = data
                c = next(c for c in self.courses if c['id'] == cid)
                keys = {self.key(c, u) for u in files}
                self.selected = {k for k in self.selected if k[0] != cid or k in keys}
                c.update(_files=files, _state=f'{len(files)} 份' if files else '无附件')
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
            self.root.destroy()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()
