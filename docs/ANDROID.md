# Android 预览版

基于 `feature/client-design` 的提交 `006aa43`，在 `feature/android-apk` 中增加 Android 主体。手机内置 Python 3.12 后端和现有前端，通过本机 `127.0.0.1:8765` 通信，不需要电脑在线。后端继续使用原有 Markdown、JSON、SQLite 派生索引和同步协议。

## 安装与使用

- 支持 Android 7.0（API 24）及以上的 64 位 ARM 手机，以及 x86_64 模拟器。32 位 Android 暂不支持。
- 下载 APK，在手机文件管理器中打开，按系统提示允许对应来源安装应用。
- 首次打开会初始化一个空的手机 Workspace。电脑资料不会自动包含在安装包中。
- 底部提供概览、待办、笔记和更多。点击“更多”可访问项目、实验记录、文献、Agent、设置等全部功能。
- 手机笔记采用列表与编辑器分开显示；返回时沿用原有的“保存并继续 / 不保存 / 继续编辑”提示。
- PDF 可通过系统文件选择器导入，PDF.js 及其 Worker 已随应用打包，阅读本机 PDF 无需联网。
- Agent、天气、RSS 和同步需要相应网络服务。Agent 的模型/API 配置仍在设置中填写，安装包不包含任何账号或密钥。

## 与电脑或服务器同步

1. 电脑或服务器运行本次分支兼容版本，将监听地址设为可供手机访问的地址，例如 `0.0.0.0`。
2. 手机进入设置 → 同步，填写电脑或服务器地址，例如 `http://192.168.1.100:8765`；不能把手机的 `127.0.0.1` 当成电脑地址。
3. 测试连接后，选择手动或自动同步。合并、冲突、附件断点等规则与桌面版一致，详见 [SYNC.md](SYNC.md)。

当前同步接口沿用单人方案，没有鉴权；适用于可信局域网或受控私有网络，不能直接暴露到公网。

## 数据、备份与生命周期

- `261018.2` 修复部分 Android 内置 SQLite 缺少 FTS5 导致启动失败的问题。自动使用普通表和 LIKE 检索，仍支持完整正文搜索；支持 FTS5 的桌面环境继续使用原有检索方式。兼容模式的大规模搜索可能较慢。
- 修复包提高了 versionCode，使用原签名，可直接覆盖安装上一预览版，无需卸载或清除数据。
- 数据保存在应用私有目录 `files/workbench/`，静态资源在独立缓存目录。更新 APK 不会覆盖 Workspace。
- 设置 → 服务与存储 → 导出数据备份，可通过系统文件选择器把 ZIP 保存到指定位置。
- 备份包含 Workspace、文献 `Index/library.json` 和通用配置；跳过索引缓存、PDF 预览缓存、同步运行状态及 `config/secret.json`、`secrets.json`。
- 备份可解压到电脑版数据目录恢复。Android 预览版暂未实现直接导入备份，可通过双向同步将资料传回手机。
- 卸载应用或清除应用数据会删除本机资料，请先同步或备份。
- Android 可能回收后台进程；当前没有前台常驻服务。后台持续同步和专注结束通知暂不作保证，返回前台后可继续同步。
- Windows 托盘、窗口控制、VS Code/Typora 打开原文件等桌面专用能力不适用于 Android。
- 当前交付为调试签名预览包。正式分发时应使用自己保管的签名密钥；覆盖更新需要相同签名。

## 云端或本机构建

需要完整 JDK 17（包含 `javac` 和 `jlink`）、Python 3.12、Android SDK Platform 35 / Build Tools 35.0.0，以及访问 Google Maven、Maven Central 和 Gradle 分发站点的网络。构建不需要 Android NDK。Gradle Wrapper、AGP 8.9.1 和 Chaquopy 17.0.0 已固定版本。

配置 `JAVA_HOME`、`ANDROID_HOME` 或 `ANDROID_SDK_ROOT` 后，在仓库根目录执行：

```bash
python tools/build_android.py
```

输出 `build/android/ResearchWorkbench-Android-preview.apk`。

预览包保留后端 Python 源码以便查看错误栈。构建脚本会逐文件核验 APK 内的后端源码与仓库一致，防止交付旧缓存；需要完全重建时使用 `python tools/build_android.py --clean`。

也可直接调用 Gradle 编译（交付前建议使用上面的构建脚本核验）：

```bash
cd android
./gradlew assembleDebug lintDebug
```

Windows 使用 `gradlew.bat`。源码、静态前端和 VERSION 由 Gradle 从仓库生成打包输入；配置、Workspace、API 密钥、桌面构建环境不会打入 APK。

## 验证

```bash
python tools/test_android.py
python tools/test_desktop.py
python tools/test_sync_engine.py
node tools/test_android_ui.js
```

界面测试需要 Playwright 和 Chromium；可用 `CHROMIUM_PATH` 指向本机 Chrome，`ANDROID_QA_OUTPUT` 指定截图目录。测试使用独立临时数据，不读取用户 Workspace。浏览器测试覆盖 360/393/768/1280 宽度、抽屉导航、返回、未保存拦截、笔记保存/预览、备份入口、深色模式、阻断外网后的 PDF 阅读以及桌面界面隔离。
