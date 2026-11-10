"""Step-by-step illustrated Cookie guide. Uses redacted assets only."""
import math
import tkinter as tk
from tkinter import ttk
from .ui_support import Flow, fit_window

STEPS = [
    ('打开“应用程序”', '先登录学校网站，然后打开开发者工具。', [
        '进入“我的课程”，确认能看到自己的课程。按 F12（部分笔记本为 Fn+F12）或 Ctrl+Shift+I。',
        '在开发者工具顶部寻找“应用程序 / Application”。没有显示时，点击顶部的“+”添加工具按钮，在菜单中选择“应用程序”（见图）。',
        '其他入口：标签栏 »、开发者工具 ⋮ → 更多工具 → 应用程序，或 Ctrl+Shift+P 搜索 Show Application。'],
     'open-application.png', '图 1 · 从工具菜单中打开“应用程序”'),
    ('找到学校的 Cookie', '选择正确域名，保留所有登录 Cookie。', [
        '在“应用程序”左侧找到“存储”，展开 Cookie / Cookies，选择 https://lms.nju.edu.cn。',
        '清空筛选框，并取消“仅显示有问题的 Cookie”，右侧应出现名称、值、域、路径等列。',
        '找到 session，以及存在的 role_token。它们是名称；右侧“值”列才是需要复制的内容。图中所有 Cookie 值均已遮盖。'],
     'school-cookies-redacted.png', '图 2 · 选择学校域名，查看 Cookie 表格（已脱敏）'),
    ('复制并回到应用验证', '优先复制表格；无法整表复制时，逐项复制完整值。', [
        '方式 A：点击 Cookie 表格的一行，让焦点落在表格中，按 Ctrl+A、Ctrl+C。回到应用粘贴，应得到多行表格文本。',
        '方式 B：选择 session，在底部 Cookie Value 区域复制完整值；如果存在 role_token，也复制它的完整值。不要照抄带省略号的截断内容。',
        '按下方格式拼接后粘贴到应用，再点击“验证并探测全部课程”。若提示登录失效，重新登录学校网站后再复制。',
        '格式示例（请替换示例文字）：\nsession=你的完整session值; role_token=你的完整role_token值',
        'Cookie 仅用于本地登录会话，不要发给他人，也不要上传 GitHub。只复制 _ga 等统计 Cookie 无法登录。'],
     'school-cookies-redacted.png', '可点击图片放大，定位底部 Cookie Value 区域'),
    ('常见问题', '遇到问题时，先检查下面几项。', [
        '找不到“应用程序”：它在 F12 打开的开发者工具中，不是电脑设置里的“应用”。优先点击开发者工具顶部 + 按钮。',
        '没有学校域名：先正常登录并刷新“我的课程”，再展开 Cookie。不要选择其他网站的域名。',
        '看不到 session：清空筛选框，取消“仅显示有问题的 Cookie”，确认域名为 lms.nju.edu.cn。',
        '只能复制一项、粘贴成网页正文：焦点可能不在表格中，改用步骤 3 的逐项复制方式。',
        '登录失效：重新登录后复制新的 Cookie，回到应用清空旧内容并重新验证。网络连接失败则检查网络或校园访问条件。'],
     None, '')
]


class CookieGuide(tk.Toplevel):
    def __init__(self, parent, assets, on_return=None):
        super().__init__(parent)
        self.title('Cookie 获取教程 · 图文指引')
        fit_window(self,default=(1130,850))
        self.configure(bg='#f1f5f9')
        self.assets = assets
        self.on_return = on_return
        self.step = 0
        self.originals = {}
        self.thumbnail = None
        header = tk.Frame(self, bg='#eff6ff', padx=24, pady=16)
        header.pack(fill='x')
        self.heading = tk.Label(header, text='Cookie 获取教程', font=('Microsoft YaHei UI', 16, 'bold'), bg='#eff6ff', fg='#172d50')
        self.heading.pack(anchor='w')
        self.description = tk.Label(header, text='打开应用程序 → 选择学校域名 → 复制并验证', font=('Microsoft YaHei UI', 10), bg='#eff6ff', fg='#526782',justify='left')
        self.description.pack(anchor='w',pady=4)
        self.step_select = ttk.Combobox(header,values=[f'{i+1}. {s[0]}' for i,s in enumerate(STEPS)],state='readonly')
        self.step_select.pack(fill='x')
        self.step_select.bind('<<ComboboxSelected>>',lambda e:self.show_step(self.step_select.current()))
        bar = tk.Frame(self, bg='#fff7e6', padx=24, pady=8)
        bar.pack(fill='x')
        self.privacy = tk.Label(bar,text='截图已脱敏；真实 Cookie 仅粘贴到应用中。', bg='#fff7e6', fg='#815c16',font=('Microsoft YaHei UI',10),justify='left')
        self.privacy.pack(anchor='w')
        footer = self.footer = Flow(self,padding=(8,4))
        footer.pack(side='bottom', fill='x')
        self.previous = ttk.Button(footer, text='← 上一步', command=lambda: self.show_step(self.step-1))
        footer.add(self.previous)
        self.counter = ttk.Label(footer)
        footer.add(self.counter)
        self.next_button = ttk.Button(footer, text='下一步 →', command=lambda: self.show_step(self.step+1))
        footer.add(self.next_button)
        footer.add(ttk.Button(footer,text='回到应用粘贴 Cookie',command=self.return_to_app))
        main = tk.Frame(self, bg='#f1f5f9')
        main.pack(fill='both', expand=True, padx=16, pady=14)
        sidebar = self.sidebar = tk.Frame(main, bg='#f1f5f9', width=205)
        sidebar.pack(side='left', fill='y', padx=(0, 14))
        self.nav = []
        for i, (title, *_) in enumerate(STEPS):
            b = tk.Button(sidebar, text=f'{i+1:02d}  {title}', command=lambda n=i: self.show_step(n),
                          anchor='w', font=('Microsoft YaHei UI', 10), relief='flat', bd=0, padx=10, pady=13, cursor='hand2')
            b.pack(fill='x', pady=(0, 6))
            self.nav.append(b)
        area = self.area = ttk.Frame(main)
        area.pack(side='left', fill='both', expand=True)
        self.canvas = tk.Canvas(area, bg='white', highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg='white', padx=22, pady=18)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.content.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self.resize)
        self.bind('<MouseWheel>', self.wheel)
        self.wrap_labels = []
        self.bind('<Configure>',self.resize_outer,add='+')
        self.show_step(0)

    def resize_outer(self,event):
        if event.widget is not self:
            return
        width = max(200,self.winfo_width()-48)
        for label in (self.heading,self.description,self.privacy):
            label.configure(wraplength=width)
        if width < 950:
            self.sidebar.pack_forget()
        elif not self.sidebar.winfo_manager():
            self.sidebar.pack(side='left',fill='y',padx=(0,14),before=self.area)

    def wheel(self, event):
        if self.winfo_containing(event.x_root, event.y_root) is not None:
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def image(self, name):
        if name not in self.originals:
            self.originals[name] = tk.PhotoImage(master=self, file=str(self.assets / name))
        return self.originals[name]

    def resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        for label in self.wrap_labels:
            label.configure(wraplength=max(280, event.width-48))
        if getattr(self, 'image_label', None) is not None and self.image_label.winfo_exists():
            original = self.image(STEPS[self.step][3])
            factor = max(1, math.ceil(original.width()/max(280, event.width-48)))
            self.thumbnail = original.subsample(factor, factor)
            self.image_label.configure(image=self.thumbnail)

    def show_step(self, index):
        if not 0 <= index < len(STEPS):
            return
        self.step = index
        self.step_select.current(index)
        self.wrap_labels = []
        self.image_label = None
        for child in self.content.winfo_children():
            child.destroy()
        for i, button in enumerate(self.nav):
            button.configure(bg='#dbeafe' if i == index else '#f1f5f9', fg='#174ba0' if i == index else '#475569')
        title, subtitle, paragraphs, image_name, caption = STEPS[index]
        tk.Label(self.content, text=title, bg='white', fg='#172d50', font=('Microsoft YaHei UI', 16, 'bold'), anchor='w').pack(fill='x')
        for text, color, size in [(subtitle, '#64748b', 11)]+[(f'{i+1}.  {p}', '#334155', 11) for i, p in enumerate(paragraphs)]:
            label = tk.Label(self.content, text=text, bg='white', fg=color, font=('Microsoft YaHei UI', size), wraplength=600, justify='left', anchor='w')
            label.pack(fill='x', pady=(10, 0))
            self.wrap_labels.append(label)
        if image_name:
            caption_label = tk.Label(self.content,text=caption+' · 点击放大',bg='white',fg='#2563eb',font=('Microsoft YaHei UI',10),wraplength=500,justify='left')
            caption_label.pack(anchor='w',pady=(18,6))
            self.wrap_labels.append(caption_label)
            original = self.image(image_name)
            factor = max(1, math.ceil(original.width()/max(280, self.canvas.winfo_width()-48)))
            self.thumbnail = original.subsample(factor, factor)
            self.image_label = tk.Label(self.content, image=self.thumbnail, bg='#202020', cursor='hand2', borderwidth=1, relief='solid')
            self.image_label.pack(fill='x')
            self.image_label.bind('<Button-1>', lambda e: self.zoom(image_name))
        self.previous.configure(state='normal' if index else 'disabled')
        self.next_button.configure(state='normal' if index < len(STEPS)-1 else 'disabled')
        self.counter.configure(text=f'{index+1} / {len(STEPS)}')
        self.canvas.yview_moveto(0)
        self.update_idletasks()

    def zoom(self, name):
        viewer = tk.Toplevel(self)
        viewer.title('教程截图 · 原图已脱敏，可滚动查看')
        fit_window(viewer,default=(1200,850))
        tools = Flow(viewer,padding=8)
        tools.pack(fill='x')
        tools.add(ttk.Label(tools,text='滚动查看截图细节'))
        pane = ttk.Frame(viewer)
        pane.pack(fill='both', expand=True)
        canvas = tk.Canvas(pane, bg='#202020', highlightthickness=0)
        sy = ttk.Scrollbar(pane, orient='vertical', command=canvas.yview)
        sx = ttk.Scrollbar(pane, orient='horizontal', command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        canvas.grid(row=0, column=0, sticky='nsew');sy.grid(row=0, column=1, sticky='ns');sx.grid(row=1, column=0, sticky='ew')
        pane.rowconfigure(0, weight=1);pane.columnconfigure(0, weight=1)
        original = self.image(name)
        viewer.display_image = original
        item = canvas.create_image(0, 0, image=original, anchor='nw')

        def fit(full):
            factor = 1 if full else max(1, math.ceil(original.width()/max(300, canvas.winfo_width())))
            viewer.display_image = original.subsample(factor, factor)
            canvas.itemconfigure(item, image=viewer.display_image)
            canvas.configure(scrollregion=canvas.bbox('all'))
        tools.add(ttk.Button(tools,text='适应宽度',command=lambda:fit(False)))
        tools.add(ttk.Button(tools,text='原始大小',command=lambda:fit(True)))
        canvas.configure(scrollregion=canvas.bbox('all'))
        viewer.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units'))
        return viewer

    def return_to_app(self):
        self.destroy()
        if self.on_return:
            self.on_return()
