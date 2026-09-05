# 二进制分发第三方声明

[English](THIRD_PARTY_NOTICES.md)

各组件版权归其作者。应用的 `Contents/Resources/licenses/` 保存上游声明全文，对应源码包包含同样的声明和源码、配方。下表描述实际选用的运行组件，不代表上游源码归档内的每个工具或组件。

| 组件 | 运行范围及许可 |
| --- | --- |
| QEMU 9.1.3 与 N00 移植 | 组合程序采用 GPLv2，保留各文件具体声明；包含编入的 DTC/libfdt 等子项目 |
| DGLES 1.4.2 宿主库 | 上游 X11 风格授权及 MIT 标记的 Cocoa 新增代码；归档中的 GPL 内核模块未包含在宿主库中 |
| 项目启动器、控制器、客体辅助程序 | 除文件另有说明外采用 GPL-2.0-or-later；外框视图标记为 MIT |
| CPython 3.12.14 | Python Software Foundation 许可及其包含的第三方声明；仅内置标准库子集，没有 pip/site-packages |
| GLib 2.88.2 | LGPL-2.1-or-later，包含 GLib/GObject/GIO/GModule 动态库 |
| gettext 1.0 | 仅打包 LGPL-2.1-or-later 的 `libintl`，不包含 GPLv3 gettext 工具 |
| Pixman 0.46.4 | 各文件的 MIT 风格声明 |
| libpng 1.6.58 | libpng-2.0 声明 |
| PCRE2 10.47 | BSD-3-Clause 及保留的第三方声明 |
| Zstandard 1.5.7 | 选择 BSD-3-Clause 许可，并保留相关声明 |
| macOS 系统框架、系统库 | 由操作系统提供，不复制进应用 |

打包不会限制许可授予接收者的源码获取、修改或再分发权利。动态库保持可替换。重定位会修改 install name 并施加 ad-hoc 签名；源码包保存打包脚本和构建配方。重新构建并在本地签名修改版本不需要开发者签名密钥。

Nokia、N9、Harmattan 和 QEMU 名称用于标识研究的软件，本项目是独立保存项目。默认外框由项目原创代码绘制，未使用 Livven 图片。本发行版不授予零售固件、Nokia Pure 字体或另行提供的外壳素材权利。
