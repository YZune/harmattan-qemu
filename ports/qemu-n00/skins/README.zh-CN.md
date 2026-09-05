# 可选机身素材

[English](README.md)

本目录不分发 PNG 或 PSD。默认运行及原生几何测试均不依赖素材。

可选集成基于 Liwen Guo / Livven 的 Nokia N9 PSD（2011）开发，记录中的原作者页面为 [Nokia N9 PSD](http://livven.me/psds/nokia-n9-psd/)。其使用条款独立于本仓库代码许可，尚未确认采用开源素材许可；使用或再分发前应确认权限。

已取得权限和原 PSD 的用户，可使用 `export-n9-livven.py` 在本地导出。该可选工具需要独立 Python 环境中的 `psd-tools==1.19.0`、Pillow 和 NumPy，输出符合开孔几何的 1240×2320 PNG。用法见 `--help`；不要提交生成的图像。

将获准使用的本地结果放到 `ports/qemu-n00/skins/n9-black-livven.png`，重新构建 `--cocoa-interaction`，再为启动器显式设置 `HARMATTAN_UI_SKIN=black`。构建会将本署名说明与提供的图像一同放入应用包。默认值为 `HARMATTAN_UI_SKIN=off`。

视图代码标记为 MIT，不代表素材采用 MIT；合成测试图也不验证原 PSD 的渲染或真实性。
