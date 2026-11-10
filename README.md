# 智慧南雍课件助手

## Windows 单文件桌面应用

已实现可联网使用的图形应用，可打包为单个 **ZhihuiNanyong.exe**。使用者双击 EXE 即可，无需安装 Python，也无需携带 cookie.txt、源码或资源文件夹。

1. 点击“Cookie 获取帮助”，按 **F12 → 应用程序 / Application → 存储 → Cookie → 学校域名** 找到并复制 Cookie。
2. 粘贴到连接设置，点击“验证并探测全部课程”；也可以导入自己导出的 Cookie 文件。
3. 左侧点课程名称查看，点首列复选框选择整门课；右侧可单选课件或全选筛选结果。课程显示部分选中状态，切换课程保留选择。
4. 点击“浏览…”选择保存目录，再点击“下载已勾选课件”。
5. “下载任务”页查看进度和错误，可停止、重试失败/未完成、打开文件夹。扫描时同样可以停止，已探测内容会保留。

支持课程搜索、学期筛选、课件搜索、类型筛选、只看已选、单课程重新探测。PDF 先取原件，原件不可下载时尝试当前账号可访问的预览 PDF；其他类型下载可访问原件。文件按课程 ID 建子目录。

Cookie 教程为分步图文窗口，包含两张已脱敏截图。点击图片可查看原始大小或适应宽度，支持上/下一步与“回到应用粘贴 Cookie”。脱敏图片已打包进 EXE，无需外置图片目录。

### 检查更新

启动后在后台检查项目的最新 GitHub 正式 Release。有比当前版本新的发布时，右上角更新按钮旁显示红点；自动检查失败不会弹窗或中断下载。也可点击“检查更新”手动查询。发现更新后，可查看说明、打开发布页面或下载新版 EXE，再退出旧版运行新版。

更新以仓库 **Releases** 中的正式版本为准，标签格式为 `v主版本.次版本.修订号`（如 v1.1.0）；普通源码提交和 Actions 构建不是发布版本。尚未发布 Release 时，手动检查提示“仓库尚未发布正式版本”。维护者发布 Release 并附加名为 `ZhihuiNanyong.exe` 的文件后，下载按钮即可提供该文件入口。检查服务不使用学校 Cookie，GitHub 请求失败时可稍后重试。

1.1.1 起，API 不可用或匿名请求额度用尽时会自动尝试 GitHub 正式发布页面，减少对 API 的依赖。限流恢复前不反复请求 API；两条通道都失败才显示手动检查错误，不将访问拦截页误认为“没有更新”。无需向应用提供 GitHub Token。

Cookie 只保存在本次运行内存中；隐藏输入框不等于保存登录。退出后需要重新粘贴或导入。应用目录偏好和本次任务结果保存在 `%LOCALAPPDATA%/ZhihuiNanyong/`，不含 Cookie 和签名 URL。目录无写权限会提示重新选择，已有不完整文件不覆盖。停止后重试会从文件开头下载；已经完成的文件保留。重试任务保留原任务目录，重新勾选开始下载则使用当前目录。

### 从源码启动与打包

```powershell
python -m pip install -r requirements.txt
python app.py
```

开发者在 Windows、Python 3.13 环境安装构建依赖并执行：

```powershell
python -m pip install -r requirements-build.txt
.\build.ps1
```

产物是 `dist/ZhihuiNanyong.exe`（Windows x64）。仓库也提供 GitHub Actions 的 **Build Windows EXE** 工作流；成功运行后可在该次运行的 Artifacts 中下载 `ZhihuiNanyong-Windows-x64`，其中包含 EXE、SHA256 校验信息和隔离验证报告。界面使用 Python 内置 Tkinter/ttk，网络任务在后台线程运行，使用 PyInstaller onefile 打包运行环境和内置教程。首次启动需要解压到系统临时目录，可能比后续操作稍慢。该 EXE 不适用于 macOS/Linux。

### 验证

```powershell
python -m unittest discover -s tests -v
python app.py --smoke-test smoke_source.json
.\dist\ZhihuiNanyong.exe --smoke-test smoke_exe.json
```

`--smoke-test` 是离线诊断入口：使用本地模拟服务器验证课程探测、真实下载服务、跨课程选择、中文路径、完整文件跳过与打包教程。它不会连接学校，也不会使用个人 Cookie。退出后读取 JSON 中的 `ok`。

## Cookie 获取与应用设计

Cookie 获取路径：浏览器 **F12 → 应用程序 / Application → 存储 → Cookie / Cookies → https://lms.nju.edu.cn**。
找不到“应用程序”时，点击开发者工具标签栏的 **»**，或打开开发者工具右上角 **⋮ → 更多工具 → 应用程序**。

完整的打开面板、复制表格和逐项复制教程见 [Cookie 获取指南](docs/COOKIE_GUIDE.md)。当前脚本将复制内容保存为 UTF-8 的 cookie.txt；桌面应用直接粘贴到输入框。

图形应用已实现；以下保留设计阶段资料：[功能设计](docs/APP_DESIGN.md)、[交互原型](docs/app_prototype.html)。原型使用示例数据，不连接学校或下载文件，请勿向原型粘贴真实 Cookie。

## 启动并选择下载

```powershell
python -m pip install -r requirements.txt
python decode.py
```

也可以显式指定课程列表网页：

```powershell
python decode.py "https://lms.nju.edu.cn/user/courses#/"
```

程序使用本目录 cookie.txt 的登录状态，访问课程入口并逐页取得课程，然后探测各课程的附件课件。屏幕输出课程编号、课程名称、课程 ID，以及各课程下的课件编号、文件名、下载方式和所属教学活动。空课程和探测失败会分别说明。

完成探测后按提示选择：

1. 输入课程编号，例如 `1,3-5`；输入 `all` 选择全部课程。
2. 程序依次列出所选课程的课件。为每门课程输入课件编号，例如 `2,4-6`；输入 `all` 下载该课程全部课件。
3. 课程选择时输入 `q` 或空行退出；课件选择时输入 `q` 或空行跳过该课程。

编号对应本次屏幕显示顺序，重新探测后可能变化。输入无效时会提示重选，不会下载。

文件保存在 `downloads/课程ID/`，与旧版本目录一致。相同课程内同名课件会附加文件 ID。

## 只探测、不下载

```powershell
python decode.py --list
```

全部课程与课件的探测结果写入 `downloads/catalog.json`（不保存 Cookie 或临时签名链接）。探测包括所有可见学期；它会读取课件元数据，不会批量下载文件。只探测模式下，如有课程探测失败，程序返回非零退出状态。

可以用 `--output "D:\课件"` 指定输出目录。`--limit 2` 在交互模式下限制每个所选课程最多下载前两份被选中的课件。

## 原有网址下载方式

```powershell
python decode.py "https://lms.nju.edu.cn/course/12245/courseware#/"
python decode.py "https://lms.nju.edu.cn/course/12245/courseware#/" --list
```

直接提供单个课程网址时，仍按旧方式下载该课程全部 PDF，不进入选择界面。旧 pdf-viewer 链接和 PDF 直链也可作为参数传入。

## 下载范围和验证

课程选择模式探测所有附件类型。PDF 优先下载原件；原件不可下载时尝试当前账号可访问的预览 PDF。其他类型（如 PPT、Word、ZIP）在原件接口允许下载时保存原文件，不进行格式转换。没有可访问原件的非 PDF 会记录失败。视频流、外部网页及没有附件的教学活动不在下载范围内。预览 PDF 可能是转换版本。

PDF 检查文件头，文件传输检查响应长度，原件还核对列表中的大小。完整下载后才正式保存，已有且通过检查的文件会跳过。不完整的已有文件需先移走再重试。失败项写入 `downloads/failed.json`；重新选择相应文件即可重试。程序不会修改学校网站的权限或课件设置。

cookie.txt 支持浏览器开发者工具复制的表格、Cookie 请求头、JSON 和 Netscape 格式。登录过期时重新导出。请妥善保存此文件，不要公开分享。

最初的旧版脚本备份为 decode_legacy.py。
