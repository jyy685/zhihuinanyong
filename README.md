# 智慧南雍课件下载工具

## Cookie 获取与应用设计

Cookie 获取路径：浏览器 **F12 → 应用程序 / Application → 存储 → Cookie / Cookies → https://lms.nju.edu.cn**。
找不到“应用程序”时，点击开发者工具标签栏的 **»**，或打开开发者工具右上角 **⋮ → 更多工具 → 应用程序**。

完整的打开面板、复制表格和逐项复制教程见 [Cookie 获取指南](docs/COOKIE_GUIDE.md)。当前脚本将复制内容保存为 UTF-8 的 cookie.txt；正式图形应用设计为直接粘贴到输入框。

图形应用当前处于设计阶段：[功能设计](docs/APP_DESIGN.md)、[交互原型](docs/app_prototype.html)。原型使用示例数据，不连接学校或下载文件，请勿向原型粘贴真实 Cookie。

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
